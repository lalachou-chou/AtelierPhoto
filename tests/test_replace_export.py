"""Export option that replaces the originals instead of creating copies."""
import queue
import threading
from pathlib import Path

import pytest
from PIL import Image

from atelier.imaging import IDENTITY_RECIPE, digest
from atelier.pipeline import export_job, export_one, run_job
from atelier.store import uid


def photo(path, **recipe):
    return {"path": str(path), "data": {"digest": digest(path), "style": {},
                                        "recipe": dict(IDENTITY_RECIPE, **recipe)}}


def jpeg(path, colour=(80, 60, 40)):
    Image.new("RGB", (40, 20), colour).save(path, quality=90)
    return path


def test_jpeg_is_replaced_in_place(tmp_path):
    source = jpeg(tmp_path / "plage.JPG")
    before = source.read_bytes()
    output = export_one(photo(source, exposure=1), "", "JPEG", replace=True)
    assert Path(output) == source
    assert source.read_bytes() != before
    with Image.open(source) as edited:
        assert edited.getpixel((5, 5))[0] > 140
    assert [p.name for p in tmp_path.iterdir()] == ["plage.JPG"]  # no copy, no temporary file left


def test_unchanged_jpeg_is_left_alone(tmp_path):
    source = jpeg(tmp_path / "plage.jpg")
    before = source.read_bytes()
    assert export_one(photo(source), "", "JPEG", replace=True) == str(source)
    assert source.read_bytes() == before


def test_other_format_writes_new_file_then_removes_original(tmp_path):
    source = jpeg(tmp_path / "plage.jpg")
    output = Path(export_one(photo(source, exposure=1), "", "TIFF", replace=True))
    assert output == tmp_path / "plage.tif" and output.is_file()
    assert not source.exists()


def test_replacement_never_overwrites_another_file(tmp_path):
    source = tmp_path / "pair.png"
    Image.new("RGB", (40, 20), (80, 60, 40)).save(source)
    camera_jpeg = jpeg(tmp_path / "pair.jpg", (10, 200, 10))
    kept = camera_jpeg.read_bytes()
    output = Path(export_one(photo(source, exposure=1), "", "JPEG", replace=True))
    assert output.name == "pair_Atelier_001.jpg"
    assert camera_jpeg.read_bytes() == kept
    assert not source.exists()


def test_raw_replacement_keeps_raw_and_writes_sidecar(tmp_path):
    raw = tmp_path / "IMG_1.CR2"
    raw.write_bytes(b"raw sensor data")
    previous = tmp_path / "IMG_1.XMP"
    previous.write_text("old")
    output = export_one(photo(raw, exposure=.5), "", "RAW", replace=True)
    assert output == str(raw) and raw.read_bytes() == b"raw sensor data"
    assert "crs:Exposure2012" in previous.read_text(encoding="utf-8")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["IMG_1.CR2", "IMG_1.XMP"]


def test_failed_render_keeps_original(tmp_path, monkeypatch):
    source = jpeg(tmp_path / "plage.jpg")
    before = source.read_bytes()

    def broken(*args, **kwargs):
        raise OSError("disque plein")

    monkeypatch.setattr("atelier.pipeline.render", broken)
    with pytest.raises(OSError):
        export_one(photo(source, exposure=1), "", "PNG", replace=True)
    assert source.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["plage.jpg"]


def test_identical_copy_cannot_replace(tmp_path):
    source = jpeg(tmp_path / "plage.jpg")
    with pytest.raises(ValueError):
        export_one(photo(source), "", "SOURCE", replace=True)


class Encoder:
    version = "replace-test"

    def encode(self, image):
        return [1., 0.]


@pytest.mark.parametrize("answer", ["Yes", "No"])
def test_export_dialog_replaces_only_after_confirmation(qapp, store, tmp_path, monkeypatch, answer):
    from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QLineEdit, QMessageBox

    from atelier.app import Window
    from atelier.pipeline import analysis_job
    source = jpeg(tmp_path / "plage.jpg")
    profile = store.create_profile("Dialogue")
    job = analysis_job(store, profile, [str(source)])
    run_job(store.root, job, queue.SimpleQueue(), threading.Event(), Encoder, 0)
    batch = store.job(job)["payload"]["batch"]
    row = store.photos(batch)[0]
    row["data"].update(decision="keep", manual_recipe=dict(IDENTITY_RECIPE, exposure=.5))
    store.save_photos([row])
    store.validate(batch)
    jobs, warnings = [], []
    monkeypatch.setattr(Window, "request_preview", lambda *_: None)
    monkeypatch.setattr(Window, "launch", lambda _, identifier: jobs.append(identifier))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2])
                        or getattr(QMessageBox.StandardButton, answer))

    def choose(dialog):
        formats = dialog.findChildren(QComboBox)[0]
        replace = dialog.findChild(QCheckBox, "replaceOriginals")
        formats.setCurrentIndex(formats.findData("SOURCE"))
        assert not replace.isEnabled()
        formats.setCurrentIndex(formats.findData("JPEG"))
        replace.setChecked(True)
        assert dialog.findChild(QLineEdit).isHidden()  # no destination folder to choose
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", choose)
    window = Window(store.root)
    try:
        window.export()
    finally:
        window.close()
    assert len(warnings) == 1 and "définitivement" in warnings[0]
    if answer == "No":
        assert not jobs
        return
    [identifier] = jobs
    assert store.job(identifier)["payload"]["replace"] is True
    run_job(store.root, identifier, queue.SimpleQueue(), threading.Event(), Encoder, 0)
    assert store.job(identifier)["state"] == "done"
    assert [p.name for p in tmp_path.iterdir() if p.is_file()] == ["plage.jpg"]
    assert digest(source) != row["data"]["digest"]


def test_replace_task_marks_photos_and_blocks_second_export(store, tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    source = jpeg(folder / "plage.jpg")
    profile = store.create_profile("Remplacer")
    batch = store.create_batch(profile, "Lot", {"model": "m"}, .5)
    store.save_photo(uid(), batch, str(source), {
        "decision": "keep", "validated": True, "digest": digest(source), "style": {}, "reasons": [],
        "recipe": dict(IDENTITY_RECIPE, exposure=1), "initial_recipe": dict(IDENTITY_RECIPE)})
    with pytest.raises(ValueError):
        export_job(store, batch, "", "SOURCE", replace=True)
    job = export_job(store, batch, "", "PNG", replace=True)
    run_job(store.root, job, queue.SimpleQueue(), threading.Event())
    record = store.job(job)
    assert record["state"] == "done" and record["payload"]["outputs"] == [str(folder / "plage.png")]
    assert [p.name for p in folder.iterdir()] == ["plage.png"]
    [row] = store.photos(batch)
    assert row["data"]["replaced"] == str(folder / "plage.png")
    with pytest.raises(ValueError, match="déjà été remplacés"):
        export_job(store, batch, tmp_path / "out", "JPEG")
