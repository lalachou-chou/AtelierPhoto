import queue
import threading
from pathlib import Path

import numpy as np
import pytest
import tifffile
from PIL import Image
from PySide6.QtWidgets import QComboBox, QDialog, QLineEdit

from atelier.app import Window
from atelier.imaging import IDENTITY_RECIPE, SRGB, digest, render, render_pixels
from atelier.pipeline import analysis_job, export_one, run_job
from atelier.store import Store


class Encoder:
    version = "tiff-test"

    def encode(self, image):
        return [1., 0.]


@pytest.mark.parametrize("exposure", [0., 1.])
def test_raw_development_exports_real_rgb16_without_preview_quantization(tmp_path, monkeypatch, exposure):
    import rawpy

    source = tmp_path / "photo.nef"
    source.write_bytes(b"synthetic-raw-decoder-fixture")
    # Adjacent 16-bit levels would collapse if an eight-bit intermediate were used.
    values = np.arange(10000, 12048, dtype=np.uint16)
    pixels = np.broadcast_to(values[None, :, None], (4, len(values), 3)).copy()

    class Raw:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def postprocess(self, **options):
            assert options["output_bps"] == 16 and options["half_size"] is False
            return pixels

    monkeypatch.setattr(rawpy, "imread", lambda _: Raw())
    row = {"path": str(source), "data": {"digest": digest(source), "style": {},
           "recipe": dict(IDENTITY_RECIPE, exposure=exposure), "crop": [.25, 0, .75, 1]}}
    target = Path(export_one(row, tmp_path / "out", "TIFF"))
    with tifffile.TiffFile(target) as document:
        page = document.pages[0]
        actual = page.asarray()
        assert page.bitspersample == 16 and page.samplesperpixel == 3
        assert page.tags[34675].value == SRGB
        assert page.compression == 1
    expected = pixels[:, 512:1536] * int(2 ** exposure)
    assert actual.dtype == np.uint16 and actual.shape == (4, 1024, 3)
    np.testing.assert_array_equal(actual, expected)
    assert len(np.unique(actual)) == 1024
    assert target.suffix == ".tif" and digest(source) == row["data"]["digest"]
    with Image.open(target) as independent_reader:
        assert independent_reader.size == (1024, 4)


def test_tiff_respects_disabled_profile_manual_edits_and_exclusive_names(tmp_path, monkeypatch):
    source = tmp_path / "original.png"
    Image.new("RGB", (40, 20), (40, 60, 80)).save(source)
    row = {"path": str(source), "data": {"digest": digest(source),
           "style": {"exposure": 1., "knots": [0., 1.]},
           "recipe": dict(IDENTITY_RECIPE, intensity=1.),
           "manual_recipe": dict(IDENTITY_RECIPE, exposure=1.)}}
    monkeypatch.setattr("atelier.look.apply", lambda look, pixels, knots: pixels * 0.)
    dark = export_one(row, tmp_path / "out", "TIFF", look={})
    manual = export_one(row, tmp_path / "out", "TIFF", enabled=False, look={})
    assert dark != manual
    assert not tifffile.imread(dark).any()
    np.testing.assert_array_equal(tifffile.imread(manual)[0, 0], np.array([80, 120, 160]) * 257)


def test_display_and_rgb16_follow_same_edits_without_early_clipping():
    pixels = np.full((130, 2, 3), .8, dtype=np.float32)
    recipe = dict(IDENTITY_RECIPE, exposure=1., contrast=-.5)
    # 0.8 * 2 -> 1.6; contrast then returns it to 1.05, clipped only at output.
    recipe["contrast"] = -.5
    pixels[:] = .7  # 1.4 -> 0.95, which must not be clipped to 0.75 early.
    result = render_pixels(pixels, recipe, {})
    assert np.all(result == round(.95 * 65535))
    np.testing.assert_array_equal(np.asarray(render(pixels, recipe, {})), np.round(result / 257).astype(np.uint8))


def test_tiff_selected_in_export_dialog_survives_pause_and_library_reopen(qapp, store, tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGB", (48, 32), (40, 80, 120)).save(source)
    profile = store.create_profile("TIFF")
    job = analysis_job(store, profile, [str(source)])
    run_job(store.root, job, queue.SimpleQueue(), threading.Event(), Encoder, 0)
    assert store.job(job)["state"] == "done"
    batch = store.job(job)["payload"]["batch"]
    row = store.photos(batch)[0]
    row["data"].update(decision="keep", manual_recipe=dict(IDENTITY_RECIPE, exposure=.5))
    store.save_photos([row])
    store.set_filter(batch, False)
    store.validate(batch)
    jobs = []
    monkeypatch.setattr(Window, "request_preview", lambda *_: None)
    monkeypatch.setattr(Window, "launch", lambda _, identifier: jobs.append(identifier))

    def choose(dialog):
        formats, quality = dialog.findChildren(QComboBox)
        formats.setCurrentIndex(formats.findData("TIFF"))
        assert quality.isHidden()
        dialog.findChild(QLineEdit).setText(str(tmp_path / "out"))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", choose)
    window = Window(store.root)
    try:
        window.export()
    finally:
        window.close()
    cancel = threading.Event()
    cancel.set()
    run_job(store.root, jobs[0], queue.SimpleQueue(), cancel, Encoder, 0)
    assert store.job(jobs[0])["state"] == "paused"
    run_job(store.root, jobs[0], queue.SimpleQueue(), threading.Event(), Encoder, 0)
    reopened = Store(store.root)
    try:
        job = reopened.job(jobs[0])
        assert job["state"] == "done", job["error"]
        assert job["payload"]["format"] == "TIFF"
        output = tifffile.imread(job["payload"]["outputs"][0])
        assert output.dtype == np.uint16 and output.shape == (32, 48, 3)
    finally:
        reopened.close()
