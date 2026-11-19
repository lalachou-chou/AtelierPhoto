import queue
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, JpegImagePlugin
from PySide6.QtWidgets import QComboBox, QDialog, QLineEdit, QSpinBox

from atelier.analysis import propose
from atelier.app import Window
from atelier.framing import register_pair
from atelier.imaging import (
    IDENTITY_RECIPE,
    digest,
    features,
    temperature_kelvin,
    warmth_from_kelvin,
)
from atelier.pipeline import (
    analysis_job,
    export_job,
    export_one,
    run_job,
    training_update_job,
)


class Encoder:
    version = "style-test"

    def encode(self, image):
        return [1., 0.]


def execute(store, job):
    run_job(store.root, job, queue.SimpleQueue(), threading.Event(), Encoder, 0)
    result = store.job(job)
    assert result["state"] == "done", result["error"]
    return result["payload"]


def test_reference_pair_recovers_off_center_crop_and_guides_new_batch(store, tmp_path):
    profile = store.create_profile("Reportage")
    photo = Image.fromarray(np.random.default_rng(2).integers(25, 170, (64, 96, 3), dtype=np.uint8))
    source = tmp_path / "rush.png"
    photo.save(source)
    target = tmp_path / "rush-edit.png"
    photo.crop((24, 8, 80, 56)).point(lambda v: min(255, v * 1.3)).save(target)
    job = training_update_job(store, profile, [{"name": "Paire", "rush": [source], "kept": [target]}])
    summary = execute(store, job)["summary"]
    assert summary["examples"] == summary["crops"] == 1
    batch = execute(store, analysis_job(store, profile, [str(source)]))["batch"]
    data = store.photos(batch)[0]["data"]
    assert data["crop"] == pytest.approx([.25, .125, 80 / 96, .875], abs=.04)
    assert data["style"]["exposure"] > 0


def test_reference_only_guides_final_ratio_and_monochrome_render():
    pixels = np.random.default_rng(3).uniform(.1, .7, (40, 64, 3)).astype(np.float32)
    stats = features(pixels)
    reference = dict(stats, aspect=1., saturation=0.)
    snapshot = {"references": [{"embedding": [1., 0.], "features": reference}], "feedback": []}
    result = propose(stats, [1., 0.], snapshot, small=pixels)
    left, top, right, bottom = result["crop"]
    assert (right - left) * stats["aspect"] / (bottom - top) == pytest.approx(1.)
    assert result["style"]["saturation"] == -1
    flat = np.full((32, 48, 3), .5)
    assert register_pair(flat, flat[4:20]) == (None, None)


def test_kelvin_and_crop_survive_validation_export_and_new_import(qapp, store, tmp_path, monkeypatch):
    profile = store.create_profile("Manuel")
    path = tmp_path / "source.jpg"
    Image.new("RGB", (96, 64), "grey").save(path)
    batch = execute(store, analysis_job(store, profile, [str(path)]))["batch"]
    monkeypatch.setattr(Window, "request_preview", lambda *_: None)
    window = Window(store.root)
    try:
        window.filter_button.click()
        window.sliders["temperature"].setValue(7500)
        assert "7 500 K" in window.slider_labels["temperature"][0].text()
        window.decide("keep")
        row = store.photos(batch)[0]
        row["data"]["crop"] = [.2, .1, .8, .9]
        store.save_photos([row])
        store.validate(batch)
        assert store.validate(batch)["updated"] == 0
        assert execute(store, export_job(store, batch, tmp_path / "exports"))["outputs"]
        second = execute(store, analysis_job(store, profile, [str(path)]))["batch"]
        proposal = store.photos(second)[0]["data"]
        assert temperature_kelvin(proposal["recipe"]["temperature"]) == 7500
        assert proposal["recipe"]["intensity"] == 0.
        assert proposal["crop"] == row["data"]["crop"] == proposal["initial_crop"]
        assert store.validate(second)["updated"] == 0
    finally:
        window.close()


def test_raw_only_creates_sidecar_for_transferable_edits(tmp_path):
    source = tmp_path / "original.nef"
    source.write_bytes(b"RAW-copy-fixture")
    data = {"style": {"knots": [0.]}, "recipe": dict(IDENTITY_RECIPE, intensity=1.), "digest": digest(source)}
    row = {"path": str(source), "data": data}
    path = Path(export_one(row, tmp_path, "RAW", look={}))
    assert path.read_bytes() == source.read_bytes() and not path.with_suffix(".xmp").exists()
    data["recipe"]["temperature"] = warmth_from_kelvin(7500)
    path = Path(export_one(row, tmp_path, "RAW"))
    assert b'atelier:RenderedTemperatureKelvin="7500"' in path.with_suffix(".xmp").read_bytes()
    path = Path(export_one(row, tmp_path, "RAW", enabled=False))
    assert not path.with_suffix(".xmp").exists()


def test_quality_dialog_and_job_preserve_requested_encoding(qapp, store, tmp_path, monkeypatch):
    profile = store.create_profile("Qualité")
    source = tmp_path / "original.jpg"
    Image.new("RGB", (48, 32), "orange").save(source, quality=76, subsampling=2)
    batch = execute(store, analysis_job(store, profile, [str(source)]))["batch"]
    row = store.photos(batch)[0]
    row["data"].update(decision="keep", manual_recipe=dict(IDENTITY_RECIPE, exposure=.2))
    store.save_photos([row])
    store.set_filter(batch, False)
    store.validate(batch)
    output = execute(store, export_job(store, batch, tmp_path / "out", quality="source"))["outputs"][0]
    with Image.open(source) as original, Image.open(output) as image:
        assert original.quantization == image.quantization and JpegImagePlugin.get_sampling(image) == 2
    jobs = []
    monkeypatch.setattr(Window, "request_preview", lambda *_: None)
    monkeypatch.setattr(Window, "launch", lambda _, job: jobs.append(job))
    def choose(dialog):
        formats, quality = dialog.findChildren(QComboBox)
        formats.setCurrentIndex(formats.findData("PNG"))
        assert quality.isHidden()
        formats.setCurrentIndex(formats.findData("JPEG"))
        quality.setCurrentIndex(quality.findData("custom"))
        dialog.findChild(QSpinBox).setValue(54)
        dialog.findChild(QLineEdit).setText(str(tmp_path / "out"))
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(QDialog, "exec", choose)
    window = Window(store.root)
    try:
        window.export()
        result = execute(store, jobs[0])
        assert result["quality"] == 54
        with Image.open(result["outputs"][0]) as image, Image.open(output) as automatic:
            assert image.size == automatic.size and image.quantization != automatic.quantization
    finally:
        window.close()
