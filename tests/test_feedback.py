import pytest
from PySide6.QtWidgets import QMessageBox

from atelier.app import Window
from atelier.imaging import NEUTRAL
from atelier.store import uid


def corrected_batch(store, profile):
    batch = store.create_batch(profile, "Lot corrigé", store.snapshot(profile, "test"), .5)
    store.save_photo(uid(), batch, "photo.jpg", {
        "embedding": [1., 0.], "proposed": "keep", "decision": "reject",
        "initial_recipe": dict(NEUTRAL), "base_recipe": dict(NEUTRAL),
        "recipe": dict(NEUTRAL, exposure=.25),
    })
    store.validate(batch, profile)
    return batch


def test_clear_feedback_preserves_training_batches_and_other_profiles(store):
    profile, other = store.create_profile("Un"), store.create_profile("Deux")
    reportage = uid()
    job = store.new_job(profile, "training", {
        "reportages": [{"id": reportage, "name": "Reportage"}],
        "items": [{"reportage": reportage, "role": "rush", "path": "source.jpg"}],
    })
    store.add_training(uid(), profile, reportage, "rush", "source.jpg", {})
    model = {"reportages": 1, "photos": 6, "kept": 2, "pairs": 0}
    store.complete_training(job, model, store.job(job)["payload"])
    batch = corrected_batch(store, profile)
    corrected_batch(store, other)
    frozen = store.create_batch(profile, "Lot déjà importé", store.snapshot(profile, "test"), .5)
    before = (store.model(profile), store.training(profile), store.reportages(profile),
              store.batch(frozen), store.photos(batch), store.job(job))
    version = store.snapshot(profile, "test")["version"]
    assert store.clear_feedback(profile) == 1
    assert store.learning_count(profile) == 0
    assert store.snapshot(profile, "test")["feedback"] == []
    assert store.snapshot(profile, "test")["version"] == version + 1
    assert store.learning_count(other) == 1
    assert (store.model(profile), store.training(profile), store.reportages(profile),
            store.batch(frozen), store.photos(batch), store.job(job)) == before
    assert store.clear_feedback(profile) == 0
    assert store.snapshot(profile, "test")["version"] == version + 1
    store.validate(batch, profile)
    assert store.learning_count(profile) == 1


@pytest.mark.parametrize("confirmed", [True, False])
def test_clear_feedback_button_requires_confirmation_and_updates_count(qapp, store, monkeypatch, confirmed):
    profile = store.create_profile("Interface")
    batch = corrected_batch(store, profile)
    # Avoid starting a preview worker while testing the button interaction.
    monkeypatch.setattr(Window, "request_preview", lambda *_: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes if confirmed else QMessageBox.StandardButton.No)
    window = Window(store.root)
    try:
        assert window.clear_feedback_button.isEnabled()
        assert "Valider le lot" in window.clear_feedback_button.toolTip()
        window.clear_feedback_button.click()
        assert store.learning_count(profile) == (0 if confirmed else 1)
        assert window.clear_feedback_button.isEnabled() == (not confirmed)
        assert f"{0 if confirmed else 1} corrections mémorisées" in window.profile_info.text()
        assert store.photos(batch)[0]["data"]["decision"] == "reject"
    finally:
        window.close()


def test_clear_feedback_button_disabled_without_profile_or_learning(qapp, store):
    window = Window(store.root)
    try:
        assert not window.clear_feedback_button.isEnabled()
        profile = store.create_profile("Vide")
        window.reload_profiles(profile)
        assert not window.clear_feedback_button.isEnabled()
    finally:
        window.close()
