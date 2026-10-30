from atelier.store import pack
import queue
import threading

from atelier.pipeline import analysis_job, run_job


def test_new_snapshots_exclude_old_feedback_and_selector_without_deleting_them(store):
    profile = store.create_profile("Migration")
    old = {"embedding": [1.] * 512, "decision": "keep", "delta": {}}
    current = {"embedding": [1.] * 384, "model": "dino448", "decision": "keep", "delta": {}}
    for key, data in (("legacy", old), ("other-model", dict(current, model="dino224")), ("new", current)):
        store.db.execute("INSERT INTO feedback VALUES(?,?,?)", (profile, key, pack(data)))
    store.set_model(profile, {"selector": {"encoder": "clip", "dimension": 512}, "look": {"preserved": True}})
    snapshot = store.snapshot(profile, "dino448")
    assert snapshot["feedback"] == [current]
    assert snapshot["selector"] is None
    assert snapshot["look"] == {"preserved": True}
    assert store.learning_count(profile) == 3
    assert store.model(profile)["selector"]["encoder"] == "clip"


def test_old_references_require_reimport_before_analysis(store, photos, encoder):
    profile = store.create_profile("Old references")
    store.add_reference(profile, "old-ref", "digest", "reference.jpg",
                        {"model": "clip", "embedding": [1.] * 512})
    identifier = analysis_job(store, profile, photos)
    run_job(store.root, identifier, queue.Queue(), threading.Event(), encoder)
    job = store.job(identifier)
    assert job["state"] == "failed"
    assert "Réimportez" in job["error"]
    assert job["payload"]["batch"] is None


def test_old_paused_batch_is_not_resumed_with_new_encoder(store, photos, encoder):
    profile = store.create_profile("Paused CLIP batch")
    identifier = analysis_job(store, profile, photos)
    batch = store.create_batch(profile, "Old", {"model": "clip"}, .5)
    payload = store.job(identifier)["payload"]
    payload["batch"] = batch
    store.update_job(identifier, payload=payload)
    run_job(store.root, identifier, queue.Queue(), threading.Event(), encoder)
    assert store.job(identifier)["state"] == "failed"
    assert "version du modèle" in store.job(identifier)["error"]
    assert store.photos(batch) == []
