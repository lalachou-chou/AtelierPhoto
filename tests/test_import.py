import queue
import threading
from collections import Counter

import pytest
from PIL import Image
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from atelier.app import Window
from atelier.pipeline import analysis_job, run_job
from atelier.store import uid


def send_drop(target, urls):
    mime = QMimeData()
    mime.setUrls(urls)
    actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    enter = QDragEnterEvent(QPoint(10, 10), actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, enter)
    move = QDragMoveEvent(QPoint(10, 10), actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, move)
    drop = QDropEvent(QPointF(10, 10), actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, drop)
    return enter, move, drop


@pytest.mark.parametrize("target", ["zone", "gallery"])
def test_local_folder_drop_starts_an_import(qapp, store, tmp_path, monkeypatch, target):
    store.create_profile("Import")
    folder = tmp_path / "Photos avec espaces"
    folder.mkdir()
    source = folder / "photo.jpg"
    Image.new("RGB", (12, 12)).save(source)
    launched = []
    monkeypatch.setattr(Window, "launch", lambda self, identifier: launched.append(identifier))
    window = Window(store.root)
    try:
        window.show()
        qapp.processEvents()
        widget = window.drop_zone if target == "zone" else window.gallery.viewport()
        events = send_drop(widget, [QUrl.fromLocalFile(str(folder))])
        assert all(event.isAccepted() for event in events)
        assert events[-1].dropAction() == Qt.DropAction.CopyAction
        assert len(launched) == 1
        assert store.job(launched[0])["payload"]["paths"] == [str(source.resolve())]
        assert source.exists()
        assert not send_drop(widget, [QUrl("https://example.com/photo.jpg")])[0].isAccepted()
        assert len(launched) == 1
        widget.setEnabled(False)
        assert not send_drop(widget, [QUrl.fromLocalFile(str(folder))])[0].isAccepted()
        assert len(launched) == 1
    finally:
        window.close()


def test_interrupted_import_does_not_present_technical_proposals_as_keeps(qapp, store, monkeypatch):
    profile = store.create_profile("Import interrompu")
    batch = store.create_batch(profile, "Lot", {}, .5)
    job = store.new_job(profile, "analysis", {"batch": batch, "paths": []})
    store.update_job(job, state="failed")
    for i in range(615):
        status = "keep" if i < 569 else "review"
        store.save_photo(uid(), batch, f"photo-{i}.jpg", {"decision": status, "reasons": []})
    monkeypatch.setattr(Window, "photo_changed", lambda *_: None)
    window = Window(store.root)
    try:
        assert "0 retenues" in window.summary.text()
        assert "615 en attente de tri" in window.summary.text()
        assert "Import incomplet" in window.summary.text()
        assert "Tri en attente" in window.model.data(window.model.index(0))
        window.filter.setCurrentIndex(1)
        assert window.model.rowCount() == 0
        # Displaying an old batch must not rewrite the library.
        assert not any(r["data"].get("selection_pending") for r in store.photos(batch))
    finally:
        window.close()


class Encoder:
    version = "import-test"


class PauseAfter:
    def __init__(self, count):
        self.remaining = count

    def is_set(self):
        self.remaining -= 1
        return self.remaining < 0


def test_partial_import_obeys_quotas_and_resume_matches_uninterrupted_import(store, tmp_path, monkeypatch):
    profile = store.create_profile("Quotas")
    paths = [str(tmp_path / f"{i:04}.jpg") for i in range(700)]
    stats = {"luma": .5, "spread": .2, "saturation": .2, "sharpness": .01,
             "peak": .02, "noise": .001, "black": 0., "white": 0., "rgb": [.5] * 3}

    def prepare(path, *args):
        i = paths.index(path)
        return {"image": Image.new("RGB", (12, 12)), "features": dict(stats), "embedding": [1., 0.],
                "digest": str(i), "time": i * 1000., "sample": None}

    monkeypatch.setattr("atelier.pipeline.prepare_photo", prepare)

    def execute(identifier, cancel=None):
        run_job(store.root, identifier, queue.SimpleQueue(), cancel or threading.Event(), Encoder, 0)
        return store.job(identifier)

    identifier = analysis_job(store, profile, paths)
    for additional, total in ((615, 615), (60, 675)):
        job = execute(identifier, PauseAfter(additional))
        assert job["state"] == "paused", job["error"]
        assert job["cursor"] == total
        rows = store.photos(job["batch"])
        counts = Counter(r["data"]["decision"] for r in rows)
        assert len(rows) == total
        assert counts["keep"] == round(total * .16)
        assert counts["review"] == int(total * .35)
        assert not store.batch_ready(job["batch"])
    job = execute(identifier)
    assert job["state"] == "done", job["error"]
    resumed = store.photos(job["batch"])
    fresh = execute(analysis_job(store, profile, paths))
    assert fresh["state"] == "done", fresh["error"]
    uninterrupted = store.photos(fresh["batch"])
    for a, b in zip(resumed, uninterrupted, strict=True):
        for key in ("decision", "proposed", "reasons", "score", "recipe", "style"):
            assert a["data"][key] == b["data"][key]
