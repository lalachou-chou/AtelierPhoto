import os
import queue

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from atelier.app import Window
from atelier.imaging import IDENTITY_RECIPE


def test_window_empty_and_profile_persistence(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = Window(tmp_path / "ui-library")
    window.show()
    app.processEvents()

    assert window.profile() is None
    identifier = window.store.create_profile("Voyage")
    window.reload_profiles(identifier)
    assert window.profile() == identifier
    assert "0 corrections mémorisées" in window.profile_info.text()
    assert window.model.rowCount() == 0
    window.close()
    app.processEvents()


def test_global_filter_survives_batch_changes(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = Window(tmp_path / "filter-ui")
    monkeypatch.setattr(window, "request_preview", lambda: None)
    profile = window.store.create_profile("Profil")
    batch = window.store.create_batch(profile, "Lot", {}, .5)
    window.reload_profiles(profile)
    assert window.current_batch == batch
    assert "Retirer" in window.filter_button.text()
    assert not hasattr(window, "manage_button")
    window.filter_button.click()
    assert not window.store.batch(batch)["filter_enabled"]
    assert "Réappliquer" in window.filter_button.text()
    window.reload_profiles(profile)
    assert not window.filter_enabled()
    window.filter_button.click()
    assert window.store.batch(batch)["filter_enabled"]
    window.close()
    app.processEvents()


def test_delete_button_removes_selected_batch_after_confirmation(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = Window(tmp_path / "delete-ui")
    profile = window.store.create_profile("Profil")
    batch = window.store.create_batch(profile, "Lot de test", {}, .5)
    window.reload_profiles(profile)
    assert window.current_batch == batch
    assert window.delete_batch_button.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.delete_selected_batch()
    assert len(window.store.batches(profile)) == 1
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.delete_selected_batch()
    assert window.store.batches(profile) == []
    assert not window.delete_batch_button.isEnabled()
    window.close()
    app.processEvents()


def test_variants_double_click_returns_to_origin_and_scrolls(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = Window(tmp_path / "variants-ui")
    monkeypatch.setattr(window, "request_preview", lambda: None)
    profile = window.store.create_profile("Profil")
    batch = window.store.create_batch(profile, "Grand lot", {}, .5)
    for i in range(240):
        window.store.save_photo(str(i), batch, f"photo_{i:03}.jpg", {
            "decision": "keep" if i == 175 else "reject", "reasons": [],
            "group": "scene" if i in (174, 175, 176) else None,
            "recipe": dict(IDENTITY_RECIPE),
        })
    window.reload_profiles(profile)
    window.show()
    QTest.qWait(50)
    try:
        # Enter from a decision filter, on a photo far beyond the first layout batch.
        window.filter.setCurrentIndex(1)
        QTest.qWait(20)
        index = window.model.index(0)
        point = window.gallery.visualRect(index).center()
        QTest.mouseClick(window.gallery.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseDClick(window.gallery.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.qWait(20)
        assert window.group_filter == "scene"
        assert window.current_photo["id"] == "175"
        assert window.model.rowCount() == 3
        window.gallery.setCurrentIndex(window.model.index(2))
        window.show_variants()  # Reopening must not lose the original anchor.
        window.all_button.click()
        QTest.qWait(50)
        assert window.model.rowCount() == 240
        assert window.current_photo["id"] == "175"
        assert [r["id"] for r in window.selected_rows()] == ["175"]
        rect = window.gallery.visualRect(window.gallery.currentIndex())
        assert window.gallery.viewport().rect().contains(rect.center())
        assert window.gallery.verticalScrollBar().value() > 0
        # A photo without variants leaves the gallery untouched.
        window.gallery.setCurrentIndex(window.model.index(0))
        window.show_variants()
        assert window.group_filter is None
        assert window.model.rowCount() == 240
    finally:
        window.close()
        app.processEvents()


def test_export_pause_resume_controls_preserve_progress_and_batch(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    root = tmp_path / "export-ui"
    window = Window(root)
    profile = window.store.create_profile("Profil")
    batch = window.store.create_batch(profile, "Exporté", {}, .5)
    window.store.create_batch(profile, "Autre lot", {}, .5)
    job_id = window.store.new_job(profile, "export", {
        "batch": batch, "items": [{}, {}, {}], "outputs": ["first.jpg"],
        "destination": str(tmp_path), "format": "JPEG", "errors": [],
    })
    window.reload_profiles(profile)
    for i in range(window.batches.count()):
        if window.batches.item(i).data(Qt.ItemDataRole.UserRole) == batch:
            window.batches.setCurrentRow(i)

    class Process:
        alive = True

        def start(self):
            window.store.update_job(job_id, state="running")

        def is_alive(self):
            return self.alive

        def join(self):
            pass

        def close(self):
            pass

    class Events(queue.Queue):
        def close(self):
            pass

    monkeypatch.setattr(window.context, "Process", lambda **kwargs: Process())
    window.launch(job_id)
    window.events.close()
    window.events = Events()
    assert window.cancel_button.text() == "Mettre l’export en pause"
    window.cancel_button.click()
    assert window.cancel_event.is_set()
    assert not window.cancel_button.isEnabled()
    window.events.put({"type": "progress", "current": 1, "total": 3, "label": "second.jpg"})
    window.poll()
    assert "Suspension après" in window.progress_label.text()
    window.store.update_job(job_id, state="paused", cursor=1)
    window.process.alive = False
    window.poll()
    assert window.current_batch == batch
    assert window.cancel_button.text() == "Reprendre l’export"
    assert window.cancel_button.isEnabled()
    assert window.progress.value() == 1 and window.progress.maximum() == 3
    window.cancel_button.click()
    assert window.active_job == job_id
    assert window.progress.value() == 1
    assert window.store.job(job_id)["payload"]["outputs"] == ["first.jpg"]
    window.store.update_job(job_id, state="paused")
    window.process.alive = False
    window.poll()
    window.close()

    reopened = Window(root)
    try:
        for i in range(reopened.batches.count()):
            if reopened.batches.item(i).data(Qt.ItemDataRole.UserRole) == batch:
                reopened.batches.setCurrentRow(i)
        assert reopened.resumable_export == job_id
        assert reopened.cancel_button.isEnabled()
        assert reopened.progress.value() == 1
    finally:
        reopened.close()
        app.processEvents()
