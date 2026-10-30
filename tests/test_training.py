import queue
import sqlite3
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from atelier.pipeline import run_job, training_job, training_jobs, training_update_job
from atelier.store import Store, uid
from atelier.training import learn, match


class Encoder:
    version = "test-encoder"

    def encode(self, image):
        vector = np.asarray(image).mean(axis=(0, 1))
        return (vector / np.linalg.norm(vector)).tolist()


def reportage(tmp_path, name, seed=0):
    root = tmp_path / name
    (root / "rush").mkdir(parents=True)
    (root / "kept").mkdir()
    rng = np.random.default_rng(seed)
    rush, kept = [], []
    for i in range(6):
        pixels = rng.integers(30, 220, (32, 48, 3), dtype=np.uint8)
        source = root / "rush" / f"DSC{i:04}.png"
        Image.fromarray(pixels).save(source)
        rush.append(str(source))
        if i < 3:
            target = root / "kept" / source.name
            Image.fromarray((pixels * .9).astype(np.uint8)).save(target)
            kept.append(str(target))
    return {"name": name, "rush": rush, "kept": kept}


def execute(store, identifier, cancel=None, workers=0):
    run_job(store.root, identifier, queue.SimpleQueue(), cancel or threading.Event(), Encoder, workers)
    return store.job(identifier)


def photo(name, embedding):
    return {"name": name, "embedding": embedding}


def test_duplicate_names_use_visual_match_and_skip_ties():
    rush = [photo("DSC0001.ARW", [1., 0.]), photo("DSC0001.ARW", [0., 1.])]
    assert match(rush, [photo("DSC0001.jpg", [0., 1.])]) == {0: 1}
    rush[1]["embedding"] = [1., 0.]
    assert match(rush, [photo("DSC0001.jpg", [1., 0.])]) == {}


@pytest.mark.parametrize("name", ["DSC0001N&B.jpg", "DSC0001-Edit-2.jpg", "dsc0001.JPG"])
def test_export_suffixes(name):
    assert match([photo("DSC0001.ARW", [1., 0.])], [photo(name, [0., 1.])]) == {0: 0}


def test_number_prefix_is_not_a_filename_match():
    assert match([photo("DSC0001.ARW", [1., 0.])], [photo("DSC00012.jpg", [0., 1.])]) == {}


def test_renamed_images_need_unambiguous_visual_match():
    rush = [photo("one.png", [1., 0.]), photo("two.png", [0., 1.])]
    assert match(rush, [photo("renamed.png", [0., 1.])]) == {0: 1}
    rush[0]["embedding"] = [.01, .99995]
    assert match(rush, [photo("renamed.png", [0., 1.])]) == {}
    assert match([], [photo("one.png", [1., 0.])]) == {}


def test_selected_original_path_resolves_identical_camera_names():
    rush = [dict(photo("same.jpg", [1., 0.]), path="camera-a/same.jpg"),
            dict(photo("same.jpg", [1., 0.]), path="camera-b/same.jpg")]
    assert match(rush, [rush[1]]) == {0: 1}


def test_multiple_reportages_cumulate_selection_and_look(store, tmp_path):
    first, second = reportage(tmp_path, "A"), reportage(tmp_path, "B", 1)
    profile = store.create_profile("Progressif")
    job = execute(store, training_job(store, profile, **first), workers=2)
    assert job["state"] == "done", job["error"]
    assert store.model(profile)["reportages"] == 1
    batch = store.create_batch(profile, "Avant le deuxième reportage", store.snapshot(profile, Encoder.version), .5)
    frozen = store.batch(batch)["snapshot"]
    job = execute(store, training_job(store, profile, **second), workers=2)
    assert job["state"] == "done", job["error"]
    model = store.model(profile)
    assert (model["reportages"], model["photos"], model["kept"], model["pairs"]) == (2, 12, 6, 6)
    assert model["selector"]["rate"] == .5
    assert model["look"] is not None
    assert store.batch(batch)["snapshot"] == frozen
    # The same camera filenames in different reportages must never cross-match.
    combined = store.create_profile("En une fois")
    job = execute(store, training_jobs(store, combined, [first, second]), workers=2)
    assert job["state"] == "done", job["error"]
    assert store.model(combined) == model
    assert store.snapshot(combined, Encoder.version)["selector"] == model["selector"]
    assert store.snapshot(combined, Encoder.version)["look"] == model["look"]


class PauseAfter:
    def __init__(self, count):
        self.remaining = count

    def is_set(self):
        self.remaining -= 1
        return self.remaining < 0


def test_pause_restart_and_finished_job_are_idempotent(store, tmp_path):
    profile = store.create_profile("Reprise")
    records = [reportage(tmp_path, "A"), reportage(tmp_path, "B", 1)]
    identifier = training_jobs(store, profile, records)
    job = execute(store, identifier, PauseAfter(7), workers=2)
    assert job["state"] == "paused" and job["cursor"] == 7
    assert store.model(profile) is None
    assert len(store.training(profile)) == 7
    assert store.training(profile, completed_only=True) == []
    job = execute(store, identifier, workers=2)
    assert job["state"] == "done", job["error"]
    model = store.model(profile)
    assert len(store.training(profile)) == 18
    execute(store, identifier)
    assert store.model(profile) == model
    assert len(store.training(profile)) == 18


def test_other_incomplete_reportage_does_not_contaminate_learning(store, tmp_path):
    profile = store.create_profile("Isolation")
    pending = training_job(store, profile, **reportage(tmp_path, "Pending"))
    execute(store, pending, PauseAfter(7))
    current = training_job(store, profile, **reportage(tmp_path, "Complete", 1))
    assert execute(store, current)["state"] == "done"
    assert store.model(profile)["photos"] == 6
    assert store.model(profile)["kept"] == 3
    assert execute(store, pending)["state"] == "done"
    assert store.model(profile)["reportages"] == 2


def test_selected_originals_remain_in_rush(store, tmp_path):
    profile = store.create_profile("Originaux choisis")
    record = reportage(tmp_path, "A")
    record["kept"] = record["rush"][:3]
    identifier = training_job(store, profile, **record)
    assert execute(store, identifier)["state"] == "done"
    assert store.model(profile)["kept"] == 3
    assert store.model(profile)["photos"] == 6


def test_invalid_inputs_create_no_jobs(store, tmp_path):
    profile = store.create_profile("Invalid")
    record = reportage(tmp_path, "A")
    for records in ([], [dict(record, kept=[])], [record, record]):
        with pytest.raises(ValueError):
            training_jobs(store, profile, records)
    assert store.unfinished_jobs(profile) == []


def test_legacy_training_job_can_resume(store, tmp_path):
    profile = store.create_profile("Ancienne version")
    record = reportage(tmp_path, "A")
    payload = {"reportage": uid(), "name": "A", "errors": [], "warnings": [],
               "items": [{"path": p, "role": role} for role in ("rush", "kept") for p in record[role]]}
    identifier = store.new_job(profile, "training", payload)
    execute(store, identifier, PauseAfter(3))
    assert execute(store, identifier)["state"] == "done"
    assert store.model(profile)["photos"] == 6


def test_read_failure_preserves_profile_and_is_resumable(store, tmp_path):
    profile = store.create_profile("Disque")
    record = reportage(tmp_path, "A")
    identifier = training_job(store, profile, **record)
    assert execute(store, identifier)["state"] == "done"
    previous = store.model(profile)
    second = reportage(tmp_path, "B", 1)
    path = tmp_path / "B" / "rush" / "DSC0002.png"
    saved = path.read_bytes()
    path.unlink()
    identifier = training_job(store, profile, **second)
    job = execute(store, identifier, workers=2)
    assert job["state"] == "failed" and job["cursor"] == 2
    assert store.model(profile) == previous
    path.write_bytes(saved)
    assert execute(store, identifier, workers=2)["state"] == "done"
    assert store.model(profile)["photos"] == 12


def test_corrupt_reportage_excluded_from_current_and_future_training(store, tmp_path):
    profile = store.create_profile("Corruption")
    bad, good = reportage(tmp_path, "Bad"), reportage(tmp_path, "Good", 1)
    (tmp_path / "Bad" / "kept" / "DSC0000.png").write_bytes(b"not an image")
    identifier = training_jobs(store, profile, [bad, good])
    job = execute(store, identifier)
    assert job["state"] == "done", job["error"]
    assert job["payload"]["errors"] and job["payload"]["warnings"]
    assert store.model(profile)["photos"] == 6
    next_id = training_job(store, profile, **reportage(tmp_path, "Next", 2))
    assert execute(store, next_id)["state"] == "done"
    assert store.model(profile)["photos"] == 12


def test_no_match_or_mixed_encoder_cannot_teach_false_negatives(store, tmp_path):
    profile = store.create_profile("Correspondances")
    identifier = training_job(store, profile, **reportage(tmp_path, "A"))
    assert execute(store, identifier)["state"] == "done"
    rows = store.training(profile)
    invalid = []
    for row in rows:
        data = dict(row["data"], embedding=[1., 0., 0.])
        if row["role"] == "kept":
            data.update(name="unmatched.png", embedding=[0., 1., 0.])
        invalid.append(dict(row, reportage="unmatched", path="unmatched/" + row["id"], data=data))
    model, warnings = learn(rows + invalid, lambda _: None, Encoder.version)
    assert model["photos"] == 6 and model["kept"] == 3
    assert any("sans correspondance" in w for w in warnings)
    invalid[0]["data"]["model"] = "legacy"
    model, warnings = learn(rows + invalid, lambda _: None, Encoder.version)
    assert model["photos"] == 6
    assert any("ancien modèle" in w for w in warnings)


def test_model_and_completed_job_publish_atomically(store):
    profile = store.create_profile("Transaction")
    identifier = store.new_job(profile, "training", {})
    store.set_model(profile, {"previous": True})
    store.db.execute("CREATE TRIGGER fail_job BEFORE UPDATE ON jobs BEGIN SELECT RAISE(ABORT, 'test'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.complete_training(identifier, {"new": True}, {})
    assert store.model(profile) == {"previous": True}
    assert store.job(identifier)["state"] == "pending"


def test_catalog_selection_reuses_samples_and_removal_rebuilds_model(store, tmp_path, monkeypatch):
    first, second = reportage(tmp_path, "A"), reportage(tmp_path, "B", 1)
    profile = store.create_profile("Choix")
    assert execute(store, training_update_job(store, profile, [first, second]))["state"] == "done"
    original_model = store.model(profile)
    batch = store.create_batch(profile, "Existant", store.snapshot(profile, Encoder.version), .5)
    frozen = store.batch(batch)["snapshot"]
    records = store.reportages(profile)
    assert len(records) == 2 and all(r["ready"] and r["enabled"] for r in records)

    # Re-selection must use stored samples even when the source disk is unavailable.
    def no_decode(*args, **kwargs):
        raise AssertionError("Cached photos must not be decoded again")
    monkeypatch.setattr("atelier.pipeline.prepare_photo", no_decode)
    records[1]["enabled"] = False
    job = execute(store, training_update_job(store, profile, records))
    assert job["state"] == "done", job["error"]
    assert store.model(profile)["photos"] == 6
    assert not store.reportages(profile)[1]["enabled"]
    assert len(store.training(profile)) == 18  # Unchecked does not mean deleted.
    records[1]["enabled"] = True
    assert execute(store, training_update_job(store, profile, records))["state"] == "done"
    assert store.model(profile) == original_model

    removed_id = records[0]["id"]
    samples = store.private_dir(profile, "training", removed_id)
    assert any(samples.iterdir())
    job = execute(store, training_update_job(store, profile, records[1:]))
    assert job["state"] == "done", job["error"]
    assert store.model(profile)["photos"] == 6
    assert [r["id"] for r in store.reportages(profile)] == [records[1]["id"]]
    assert all(r["reportage"] != removed_id for r in store.training(profile))
    assert not samples.exists()
    assert store.batch(batch)["snapshot"] == frozen
    assert all(Path(p).exists() for p in first["rush"] + first["kept"])


def test_remove_last_reportage_restores_defaults_without_encoder(store, tmp_path):
    profile = store.create_profile("Dernier")
    assert execute(store, training_update_job(store, profile, [reportage(tmp_path, "A")]))["state"] == "done"
    identifier = training_update_job(store, profile, [])
    def no_encoder():
        raise AssertionError("No images to analyse")
    run_job(store.root, identifier, queue.SimpleQueue(), threading.Event(), no_encoder)
    assert store.job(identifier)["state"] == "done"
    assert store.model(profile) is None
    assert store.reportages(profile) == []
    assert store.training(profile) == []


def test_unchecked_new_reportage_is_saved_without_learning(store, tmp_path):
    profile = store.create_profile("Plus tard")
    record = dict(reportage(tmp_path, "A"), enabled=False)
    job = execute(store, training_update_job(store, profile, [record]))
    assert job["state"] == "done", job["error"]
    assert store.model(profile) is None
    saved = store.reportages(profile)
    assert len(saved) == 1 and not saved[0]["enabled"] and not saved[0]["ready"]
    saved[0]["enabled"] = True
    assert execute(store, training_update_job(store, profile, saved))["state"] == "done"
    assert store.model(profile)["photos"] == 6


def test_management_failure_preserves_model_and_catalog_choices(store, tmp_path):
    profile = store.create_profile("Échec")
    assert execute(store, training_update_job(store, profile, [reportage(tmp_path, "A")]))["state"] == "done"
    previous, records = store.model(profile), store.reportages(profile)
    broken = reportage(tmp_path, "B")
    (tmp_path / "B" / "kept" / "DSC0000.png").write_bytes(b"invalid")
    identifier = training_update_job(store, profile, [broken])  # Requests removal of A as well.
    job = execute(store, identifier)
    assert job["state"] == "failed"
    assert store.model(profile) == previous
    assert store.reportages(profile)[0] == records[0]
    assert any(r["reportage"] == records[0]["id"] for r in store.training(profile))
    assert execute(store, training_update_job(store, profile, records))["state"] == "done"
    assert store.job(identifier)["state"] == "superseded"


def test_remove_paused_reportage_prevents_resume_from_restoring_it(store, tmp_path):
    profile = store.create_profile("Suspendu")
    identifier = training_update_job(store, profile, [reportage(tmp_path, "A"), reportage(tmp_path, "B", 1)])
    assert execute(store, identifier, PauseAfter(10))["state"] == "paused"
    records = store.reportages(profile)
    records[0]["enabled"] = True
    job = execute(store, training_update_job(store, profile, records[:1]))
    assert job["state"] == "done", job["error"]
    assert store.model(profile)["photos"] == 6
    assert store.job(identifier)["state"] == "superseded"
    execute(store, identifier)
    assert len(store.reportages(profile)) == 1 and len(store.training(profile)) == 9
    assert store.unfinished_jobs(profile) == []
    # A future additive job must still see the successfully rebuilt training set.
    assert execute(store, training_job(store, profile, **reportage(tmp_path, "C", 2)))["state"] == "done"
    assert store.model(profile)["photos"] == 12


def test_catalog_migrates_existing_v4_training_and_pending_jobs(store, tmp_path):
    profile = store.create_profile("Migration")
    good = training_job(store, profile, **reportage(tmp_path, "A"))
    assert execute(store, good)["state"] == "done"
    pending = training_job(store, profile, **reportage(tmp_path, "B", 1))
    assert execute(store, pending, PauseAfter(2))["state"] == "paused"
    expected = store.reportages(profile)
    with store.db:
        store.db.execute("DELETE FROM reportages")
        store.db.execute("PRAGMA user_version=4")
    migrated = Store(store.root)
    try:
        assert migrated.reportages(profile) == expected
        assert migrated.db.execute("PRAGMA user_version").fetchone()[0] == 6
    finally:
        migrated.close()


def test_management_rejects_foreign_ids_and_duplicate_rushs(store, tmp_path):
    profile, other = store.create_profile("Un"), store.create_profile("Deux")
    source = reportage(tmp_path, "A")
    training_update_job(store, profile, [source])
    records = store.reportages(profile)
    for target, catalog in ((other, records), (profile, records + records), (profile, records + [source])):
        with pytest.raises(ValueError):
            training_update_job(store, target, catalog)


def test_removing_reportage_with_too_small_remainder_clears_old_model(store, tmp_path):
    profile = store.create_profile("Petit reste")
    first, second = reportage(tmp_path, "A"), reportage(tmp_path, "B", 1)
    second["rush"], second["kept"] = second["rush"][:3], second["kept"][:2]
    assert execute(store, training_update_job(store, profile, [first, second]))["state"] == "done"
    assert store.model(profile)["photos"] == 9
    remaining = store.reportages(profile)[1:]
    job = execute(store, training_update_job(store, profile, remaining))
    assert job["state"] == "done", job["error"]
    assert job["payload"]["warnings"]
    assert store.model(profile) is None
    assert len(store.reportages(profile)) == 1


def test_catalog_removal_and_model_publish_are_atomic(store, tmp_path):
    profile = store.create_profile("Transaction retrait")
    assert execute(store, training_update_job(store, profile, [reportage(tmp_path, "A")]))["state"] == "done"
    previous, records = store.model(profile), store.reportages(profile)
    identifier = training_update_job(store, profile, [])
    store.db.execute("CREATE TRIGGER fail_job BEFORE UPDATE ON jobs BEGIN SELECT RAISE(ABORT, 'test'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.complete_training(identifier, None, store.job(identifier)["payload"])
    assert store.model(profile) == previous
    assert store.reportages(profile) == records
    assert len(store.training(profile)) == 9


def test_changing_training_reportages_preserves_validated_user_corrections(store, tmp_path):
    from atelier.imaging import NEUTRAL

    profile = store.create_profile("Corrections conservées")
    assert execute(store, training_update_job(store, profile, [reportage(tmp_path, "A")]))["state"] == "done"
    batch = store.create_batch(profile, "Corrigé", store.snapshot(profile, Encoder.version), .5)
    store.save_photo(uid(), batch, tmp_path / "photo.jpg", {
        "embedding": [1., 0., 0.], "proposed": "keep", "decision": "reject",
        "initial_recipe": dict(NEUTRAL), "base_recipe": dict(NEUTRAL),
        "recipe": dict(NEUTRAL, exposure=.25),
    })
    assert store.validate(batch, profile)["corrections"] == 1
    before = store.snapshot(profile, Encoder.version)["feedback"]
    assert before[0]["decision"] == "reject" and before[0]["delta"]["exposure"] == .25
    assert execute(store, training_update_job(store, profile, [reportage(tmp_path, "B", 1)]))["state"] == "done"
    assert store.snapshot(profile, Encoder.version)["feedback"] == before
    assert execute(store, training_update_job(store, profile, []))["state"] == "done"
    assert store.snapshot(profile, Encoder.version)["feedback"] == before
    assert store.learning_count(profile) == 1


def test_worker_reports_remaining_time_and_final_calculation_phase(store, tmp_path, monkeypatch):
    from itertools import count

    ticks = count(0, 5)
    monkeypatch.setattr("atelier.progress.monotonic", lambda: next(ticks))
    profile = store.create_profile("Progression")
    identifier = training_job(store, profile, **reportage(tmp_path, "A"))
    events = queue.SimpleQueue()
    run_job(store.root, identifier, events, threading.Event(), Encoder, 0)
    assert store.job(identifier)["state"] == "done"
    messages = []
    while not events.empty():
        messages.append(events.get())
    progress = [m for m in messages if m["type"] == "progress"]
    assert progress[0]["remaining_seconds"] is None
    assert progress[3]["remaining_seconds"] == 30  # Six of nine photos remain at five seconds each.
    assert messages[-2]["type"] == "phase"
    assert "remaining_seconds" not in messages[-2]
    assert messages[-1]["type"] == "done"


def test_learned_reportage_survives_moving_its_source_directory(store, tmp_path):
    profile = store.create_profile("Source déplacée")
    first = reportage(tmp_path, "A")
    assert execute(store, training_update_job(store, profile, [first]))["state"] == "done"
    learned = store.model(profile)
    records = store.reportages(profile)
    source, destination = (tmp_path / "A").resolve(), (tmp_path / "A déplacé").resolve()
    assert source.is_relative_to(tmp_path.resolve()) and destination.is_relative_to(tmp_path.resolve())
    source.rename(destination)
    assert all(not Path(path).exists() for path in first["rush"] + first["kept"])
    assert store.snapshot(profile, Encoder.version)["selector"] == learned["selector"]
    job = execute(store, training_update_job(store, profile, records), workers=2)
    assert job["state"] == "done", job["error"]
    assert store.model(profile) == learned
    second = reportage(tmp_path, "B", 1)
    job = execute(store, training_update_job(store, profile, records + [second]), workers=2)
    assert job["state"] == "done", job["error"]
    assert store.model(profile)["photos"] == 12
