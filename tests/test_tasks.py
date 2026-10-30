import pytest
from PySide6.QtWidgets import QDialog, QMessageBox

from atelier.store import uid
from atelier.task_dialog import TaskDialog


def test_delete_incomplete_analysis_removes_its_partial_batch(store, tmp_path):
    profile = store.create_profile("Analyse")
    batch = store.create_batch(profile, "Incomplet", {}, .5)
    job = store.new_job(profile, "analysis", {"batch": batch, "paths": []})
    store.update_job(job, state="paused")
    store.save_photo(uid(), batch, tmp_path / "source.jpg", {"decision": "keep"})
    cache = store.private_dir(profile, "batches", batch)
    (cache / "preview.png").write_bytes(b"preview")
    assert not store.batch_ready(batch)
    store.delete_job(job, profile)
    assert store.unfinished_jobs(profile) == []
    assert store.batches(profile) == []
    assert store.photos(batch) == []
    assert not cache.exists()


def test_delete_export_preserves_batch_and_exported_files(store, tmp_path):
    profile = store.create_profile("Export")
    batch = store.create_batch(profile, "Terminé", {}, .5)
    output = tmp_path / "export.jpg"
    output.write_bytes(b"finished export")
    job = store.new_job(profile, "export", {"batch": batch, "outputs": [str(output)]})
    store.update_job(job, state="failed")
    store.delete_job(job, profile)
    assert store.unfinished_jobs(profile) == []
    assert store.batch(batch)["name"] == "Terminé"
    assert output.read_bytes() == b"finished export"


def test_delete_training_task_preserves_profile_and_partial_samples(store):
    profile = store.create_profile("Apprentissage")
    reportage = uid()
    job = store.new_job(profile, "training", {"reportages": [{"id": reportage, "name": "Reportage"}],
                                             "items": [{"reportage": reportage, "path": "photo.jpg", "role": "rush"}]})
    store.set_model(profile, {"previous": True})
    store.add_training(uid(), profile, reportage, "rush", "photo.jpg", {})
    store.update_job(job, state="paused")
    store.delete_job(job, profile)
    assert store.model(profile) == {"previous": True}
    assert len(store.reportages(profile)) == len(store.training(profile)) == 1
    assert store.training(profile, completed_only=True) == []


def test_delete_task_rejects_other_profiles_and_running_or_finished_tasks(store):
    profile, other = store.create_profile("Un"), store.create_profile("Deux")
    job = store.new_job(profile, "analysis", {"batch": None, "paths": []})
    with pytest.raises(ValueError, match="profil"):
        store.delete_job(job, other)
    for state in ("running", "done", "superseded"):
        store.update_job(job, state=state)
        with pytest.raises(ValueError, match="Seule"):
            store.delete_job(job, profile)
    store.update_job(job, state="pending")
    store.delete_job(job, profile)
    assert store.unfinished_jobs(profile) == []


@pytest.mark.parametrize("action", ["resume", "delete"])
def test_task_dialog_returns_chosen_task_and_action(qapp, action):
    jobs = [{"id": str(i), "kind": kind, "state": "paused", "created": "2026-11-02", "cursor": i}
            for i, kind in enumerate(("analysis", "training", "export"))]
    dialog = TaskDialog(jobs)
    try:
        dialog.list.setCurrentRow(2)
        getattr(dialog, action).click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert dialog.action == action
        assert dialog.selected_job()["id"] == "2"
    finally:
        dialog.close()


def test_empty_or_running_tasks_cannot_be_selected_for_action(qapp):
    for jobs in ([], [{"id": "1", "kind": "analysis", "state": "running", "created": "", "cursor": 0}]):
        dialog = TaskDialog(jobs)
        try:
            assert not dialog.resume.isEnabled() and not dialog.delete.isEnabled()
            dialog.choose("delete")
            assert dialog.result() != QDialog.DialogCode.Accepted
        finally:
            dialog.close()


@pytest.mark.parametrize("confirmed", [True, False])
def test_window_task_deletion_confirmation_and_labels(qapp, store, monkeypatch, confirmed):
    from atelier.app import Window

    profile = store.create_profile("Interface")
    batch = store.create_batch(profile, "Lot", {}, .5)
    job = store.new_job(profile, "export", {"batch": batch, "items": [], "outputs": []})
    store.update_job(job, state="paused")
    window = Window(store.root)
    decisions = iter([QDialog.DialogCode.Accepted, QDialog.DialogCode.Rejected])

    def choose_delete(dialog):
        dialog.action = "delete"
        return next(decisions)

    monkeypatch.setattr(TaskDialog, "exec", choose_delete)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes if confirmed else QMessageBox.StandardButton.No)
    try:
        assert window.before_button.text() == "Afficher l’original (sans retouche)"
        window.before_button.setChecked(True)
        window.request_preview()
        assert window.before_button.text() == "Afficher la retouche"
        window.before_button.setChecked(False)
        window.request_preview()
        assert window.before_button.text() == "Afficher l’original (sans retouche)"
        assert window.filter_button.text() == "Retirer la retouche sur tout le lot"
        window.filter_button.click()
        assert window.filter_button.text() == "Réappliquer la retouche sur tout le lot"
        window.resume_button.click()
        assert len(store.unfinished_jobs(profile)) == (0 if confirmed else 1)
        assert window.resume_button.text() == f"Gérer les tâches ({0 if confirmed else 1})"
        assert store.batch(batch)["name"] == "Lot"
    finally:
        window.close()
