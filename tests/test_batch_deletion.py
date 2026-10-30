import json
import sqlite3

import pytest
from test_workflow import execute, prepared

from atelier.analysis import propose
from atelier.pipeline import analysis_job, export_job
from atelier.store import Store


def test_delete_batch_keeps_learning_references_originals_and_exports(store, photos, encoder, tmp_path):
    profile, batch = prepared(store, photos, encoder)
    second = store.create_profile("Autre profil")
    row = store.photos(batch)[0]
    row["data"]["recipe"]["exposure"] += .3
    row["data"]["decision"] = "keep"
    store.save_photo(row["id"], batch, row["path"], row["data"])
    result = store.validate(batch, profile)
    assert result["corrections"] == 1 and result["updated"] == 1
    assert store.learning_count(second) == 0
    exported = execute(store, export_job(store, batch, tmp_path / "exports"), encoder)
    outputs = exported["payload"]["outputs"]
    memory = store.snapshot(profile, encoder.version)
    directory = store.root / "profiles" / profile / "batches" / batch
    assert directory.exists()
    store.delete_batch(batch, profile)
    assert not directory.exists()
    assert store.photos(batch) == []
    assert store.batches(profile) == []
    assert store.rows("SELECT id FROM jobs WHERE batch=?", (batch,)) == []
    assert store.snapshot(profile, encoder.version) == memory
    assert len(store.references(profile)) == 2
    from pathlib import Path
    assert all(Path(path).exists() for path in photos + outputs)
    result = propose(row["data"]["features"], row["data"]["embedding"], memory)
    assert result["recipe"]["exposure"] == pytest.approx(.3)
    reopened = Store(store.root)
    assert reopened.learning_count(profile) == 1
    reopened.wipe(profile)
    assert reopened.learning_count(profile) == 0
    reopened.close()


def test_wrong_profile_and_running_batch_cannot_be_deleted(store, photos, encoder):
    profile, batch = prepared(store, photos, encoder)
    other = store.create_profile("Autre")
    with pytest.raises(ValueError, match="profil sélectionné"):
        store.delete_batch(batch, other)
    with pytest.raises(ValueError, match="profil sélectionné"):
        store.validate(batch, other)
    job = store.new_job(profile, "analysis", {"batch": batch})
    store.update_job(job, state="running")
    with pytest.raises(ValueError, match="Suspendez"):
        store.delete_batch(batch, profile)
    store.recover_interrupted_jobs()
    store.delete_batch(batch, profile)
    assert store.learning_count(other) == 0


def test_cache_permission_failure_does_not_delete_database(store, photos, encoder, monkeypatch):
    profile, batch = prepared(store, photos, encoder)
    from pathlib import Path
    def fail_rename(*args):
        raise PermissionError("locked")
    monkeypatch.setattr(Path, "rename", fail_rename)
    with pytest.raises(PermissionError):
        store.delete_batch(batch, profile)
    assert len(store.photos(batch)) == 5


def test_v1_migration_preserves_learned_feedback_and_job_links(store, photos, encoder):
    profile, batch = prepared(store, photos, encoder)
    row = store.photos(batch)[0]
    row["data"]["recipe"]["temperature"] += .2
    store.save_photo(row["id"], batch, row["path"], row["data"])
    store.validate(batch)
    # Reproduce the prior persisted schema, including an old full export payload.
    store.new_job(profile, "export", {"items": [row]})
    db = sqlite3.connect(store.root / "library.sqlite3")
    db.executescript("""
        ALTER TABLE feedback RENAME TO feedback_new;
        CREATE TABLE feedback(profile TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
          photo TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE, data TEXT NOT NULL,
          PRIMARY KEY(profile,photo));
        INSERT INTO feedback SELECT * FROM feedback_new;
        DROP TABLE feedback_new;
        DROP INDEX jobs_batch_state;
        ALTER TABLE jobs DROP COLUMN batch;
        PRAGMA user_version=1;
    """)
    db.close()
    migrated = Store(store.root)
    assert migrated.db.execute("PRAGMA user_version").fetchone()[0] == 4
    assert migrated.learning_count(profile) == 1
    assert len(migrated.rows("SELECT id FROM jobs WHERE batch=?", (batch,))) == 2
    migrated.delete_batch(batch, profile)
    assert migrated.learning_count(profile) == 1
    assert migrated.rows("PRAGMA foreign_key_check") == []
    migrated.close()


def test_new_batches_use_learning_without_mutating_previous_batch(store, photos, encoder):
    profile, first = prepared(store, photos, encoder)
    before = store.batch(first)["snapshot"]
    row = store.photos(first)[0]
    row["data"]["recipe"]["saturation"] = .15
    store.save_photo(row["id"], first, row["path"], row["data"])
    store.validate(first, profile)
    job = execute(store, analysis_job(store, profile, [photos[0]]), encoder)
    second = job["payload"]["batch"]
    assert store.photos(second)[0]["data"]["recipe"]["saturation"] == pytest.approx(.15)
    assert store.batch(first)["snapshot"] == before
    assert store.validate(first, profile)["updated"] == 0


def test_no_correction_does_not_train_on_its_own_proposal(store, photos, encoder):
    profile, batch = prepared(store, photos, encoder)
    assert store.validate(batch, profile) == {"corrections": 0, "updated": 0, "total": 0}
    assert store.learning_count(profile) == 0
    assert json.loads(store.db.execute("SELECT snapshot FROM batches WHERE id=?", (batch,)).fetchone()[0])["feedback"] == []
