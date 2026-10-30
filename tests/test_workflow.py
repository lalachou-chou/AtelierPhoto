import queue
import shutil
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from atelier.analysis import propose
from atelier.imaging import NEUTRAL, decode, digest, features, render
from atelier.pipeline import (
    analysis_job,
    export_job,
    export_one,
    reference_job,
    run_job,
)
from atelier.store import Store


def execute(store, job, encoder, cancel=None):
    events = queue.Queue()
    run_job(store.root, job, events, cancel or threading.Event(), encoder)
    return store.job(job)


def prepared(store, photos, encoder):
    profile = store.create_profile("Mariage")
    result = execute(store, reference_job(store, profile, photos[:2]), encoder)
    assert result["state"] == "done", result["error"]
    job = execute(store, analysis_job(store, profile, photos), encoder)
    assert job["state"] == "done", job["error"]
    return profile, job["payload"]["batch"]


def test_complete_pipeline_preserves_originals_and_colors(store, photos, encoder, tmp_path):
    before = {p: digest(p) for p in photos}
    profile, batch = prepared(store, photos, encoder)
    rows = store.photos(batch)
    for row in rows:
        row["data"]["decision"] = "keep"
        store.save_photo(row["id"], batch, row["path"], row["data"])
    store.validate(batch)
    for fmt in ("JPEG", "PNG"):
        job = execute(store, export_job(store, batch, tmp_path / "exports", fmt), encoder)
        assert job["state"] == "done", job["error"]
        assert len(job["payload"]["outputs"]) == 5
        with Image.open(job["payload"]["outputs"][0]) as image:
            assert image.size == (128, 96)
            assert image.info["icc_profile"]
    assert before == {p: digest(p) for p in photos}


def test_feedback_only_explicit_idempotent_and_frozen_batches(store, photos, encoder):
    profile, batch = prepared(store, photos, encoder)
    initial = store.batch(batch)["snapshot"]
    store.validate(batch)
    assert store.snapshot(profile, encoder.version)["feedback"] == []
    row = store.photos(batch)[0]
    row["data"]["recipe"]["exposure"] += .3
    row["data"]["decision"] = "reject"
    store.save_photo(row["id"], batch, row["path"], row["data"])
    store.validate(batch)
    snapshot = store.snapshot(profile, encoder.version)
    assert len(snapshot["feedback"]) == 1
    version = snapshot["version"]
    store.validate(batch)
    assert store.snapshot(profile, encoder.version)["version"] == version
    assert store.batch(batch)["snapshot"] == initial
    proposal = propose(row["data"]["features"], row["data"]["embedding"], snapshot)
    assert proposal["recipe"]["exposure"] == pytest.approx(.3)
    row["data"]["recipe"] = dict(row["data"]["initial_recipe"])
    row["data"]["decision"] = row["data"]["proposed"]
    store.save_photo(row["id"], batch, row["path"], row["data"])
    store.validate(batch)
    assert store.snapshot(profile, encoder.version)["feedback"] == []


def test_reset_isolated_and_removes_internal_memory(store, photos, encoder):
    first, batch = prepared(store, photos, encoder)
    second = store.create_profile("Voyage")
    execute(store, reference_job(store, second, photos), encoder)
    store.wipe(first)
    assert store.references(first) == []
    assert store.batches(first) == []
    assert store.snapshot(first, encoder.version)["feedback"] == []
    assert not (store.root / "profiles" / first).exists()
    assert len(store.references(second)) == 5
    assert all(Path(p).exists() for p in photos)
    store.wipe(first, delete=True)
    assert [p["id"] for p in store.profiles()] == [second]


def test_duplicate_references_and_restart(store, photos, encoder):
    profile = store.create_profile("Portrait")
    execute(store, reference_job(store, profile, photos + photos), encoder)
    again = Store(store.root)
    assert len(again.references(profile)) == 5
    assert again.profiles()[0]["count"] == 5
    again.close()


def test_cancel_and_resume_without_duplicate_work(store, photos, encoder):
    profile = store.create_profile("Test")
    cancel = threading.Event()
    cancel.set()
    job_id = reference_job(store, profile, photos)
    paused = execute(store, job_id, encoder, cancel)
    assert paused["state"] == "paused"
    assert paused["cursor"] == 0
    assert execute(store, job_id, encoder)["state"] == "done"
    assert len(store.references(profile)) == 5
    assert execute(store, job_id, encoder)["state"] == "done"
    assert len(store.references(profile)) == 5


def test_cancel_between_files_commits_progress(store, photos, encoder):
    profile = store.create_profile("Test")
    cancel = threading.Event()
    class CancellingEncoder(encoder):
        def encode(self, image):
            cancel.set()
            return super().encode(image)
    identifier = reference_job(store, profile, photos)
    assert execute(store, identifier, CancellingEncoder, cancel)["cursor"] == 1
    assert len(store.references(profile)) == 1
    assert execute(store, identifier, encoder)["state"] == "done"
    assert len(store.references(profile)) == 5


def test_corrupt_unknown_files_and_exact_duplicates(store, photos, encoder, tmp_path):
    duplicate = tmp_path / "copy.png"
    shutil.copyfile(photos[0], duplicate)
    corrupt = tmp_path / "broken.png"
    corrupt.write_bytes(b"not an image")
    unknown = tmp_path / "unknown.heic"
    unknown.write_bytes(b"unsupported")
    profile, _ = prepared(store, photos, encoder)
    job = execute(store, analysis_job(store, profile, [photos[0], str(duplicate), str(corrupt), str(unknown)]), encoder)
    rows = store.photos(job["payload"]["batch"])
    assert sum("error" in r["data"] for r in rows) == 2
    valid = [r for r in rows if "error" not in r["data"]]
    assert valid[0]["data"]["group"] == valid[1]["data"]["group"]
    assert sum(r["data"]["decision"] == "reject" for r in valid) == 1


def test_export_requires_validation_and_never_overwrites(store, photos, encoder, tmp_path):
    _, batch = prepared(store, photos, encoder)
    rows = store.photos(batch)
    row = rows[0]
    row["data"]["decision"] = "keep"
    store.save_photo(row["id"], batch, row["path"], row["data"])
    with pytest.raises(ValueError, match="Validez"):
        export_job(store, batch, tmp_path)
    first = export_one(row, tmp_path, "PNG")
    checksum = digest(first)
    second = export_one(row, tmp_path, "PNG")
    assert first != second
    assert digest(first) == checksum
    Image.new("RGB", (16, 16)).save(row["path"])
    with pytest.raises(ValueError, match="changé"):
        export_one(row, tmp_path, "PNG")


def test_disk_full_is_resumable_and_cleans_partial_exports(store, photos, encoder, tmp_path, monkeypatch):
    _, batch = prepared(store, photos, encoder)
    row = store.photos(batch)[0]
    row["data"]["decision"] = "keep"
    store.save_photo(row["id"], batch, row["path"], row["data"])
    store.validate(batch)
    job_id = export_job(store, batch, tmp_path / "full")
    original_save = Image.Image.save
    def fail(*args, **kwargs):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(Image.Image, "save", fail)
    job = execute(store, job_id, encoder)
    assert job["state"] == "failed"
    assert job["cursor"] == 0
    assert list((tmp_path / "full").iterdir()) == []
    monkeypatch.setattr(Image.Image, "save", original_save)
    assert execute(store, job_id, encoder)["state"] == "done"


@pytest.mark.parametrize("format", ["JPEG", "PNG", "RAW"])
def test_export_pause_resumes_after_completed_photo_without_duplicates(store, photos, encoder, tmp_path, monkeypatch, format):
    from atelier import pipeline

    _, batch = prepared(store, photos, encoder)
    rows = store.photos(batch)
    for row in rows:
        row["data"]["decision"] = "keep"
        if format == "RAW":
            source = Path(row["path"]).with_suffix(".NEF")
            source.write_bytes(b"RAW copy fixture: " + Path(row["path"]).read_bytes())
            row["path"] = str(source)
            row["data"]["digest"] = digest(source)
            with store.db:
                store.db.execute("UPDATE photos SET path=? WHERE id=?", (row["path"], row["id"]))
        store.save_photo(row["id"], batch, row["path"], row["data"])
    store.validate(batch)
    destination = tmp_path / "paused-export"
    identifier = export_job(store, batch, destination, format)
    cancel = threading.Event()
    exported = []

    def pause_after_photo(*args, **kwargs):
        output = export_one(*args, **kwargs)
        exported.append(args[0]["id"])
        cancel.set()
        return output

    monkeypatch.setattr(pipeline, "export_one", pause_after_photo)
    for cursor in range(1, len(rows) + 1):
        cancel.clear()
        job = execute(store, identifier, encoder, cancel)
        assert job["cursor"] == cursor
        assert job["state"] == ("done" if cursor == len(rows) else "paused")
        assert len(job["payload"]["outputs"]) == cursor
        assert len(list(destination.iterdir())) == cursor * (2 if format == "RAW" else 1)
        if format == "RAW":
            output = Path(job["payload"]["outputs"][-1])
            assert output.with_suffix(".xmp").exists()
            assert digest(output) == rows[cursor - 1]["data"]["digest"]
        # Read through a fresh connection, as after restarting the application.
        reopened = Store(store.root)
        assert reopened.job(identifier)["cursor"] == cursor
        reopened.close()
    assert exported == [row["id"] for row in rows]
    assert len(set(job["payload"]["outputs"])) == len(rows)
    execute(store, identifier, encoder)
    assert len(exported) == len(rows)


def test_style_is_deterministic_and_resolution_independent():
    pixels = np.random.default_rng(42).random((80, 100, 3), dtype=np.float32)
    recipe = dict(NEUTRAL, exposure=.3, contrast=.2)
    style = {"exposure": -.2, "temperature": .1, "contrast": .1, "saturation": -.1}
    full = np.asarray(render(pixels, recipe, style))
    proxy = np.asarray(render(pixels[::2, ::2], recipe, style))
    np.testing.assert_array_equal(full[::2, ::2], proxy)
    np.testing.assert_array_equal(full, np.asarray(render(pixels, recipe, style)))


def test_healthy_unfamiliar_subject_never_auto_rejected():
    pixels = np.random.default_rng(4).random((100, 100, 3), dtype=np.float32)
    stats = features(pixels)
    snapshot = {"references": [{"embedding": [1., 0.], "features": stats}], "feedback": []}
    result = propose(stats, [0., 1.], snapshot)
    assert result["decision"] == "review"


def test_blank_and_blur_are_distinguished():
    black = features(np.zeros((80, 80, 3), dtype=np.float32))
    smooth = features(np.full((80, 80, 3), .5, dtype=np.float32))
    snapshot = {"references": [], "feedback": []}
    assert propose(black, [1., 0.], snapshot)["decision"] == "reject"
    assert propose(smooth, [1., 0.], snapshot)["decision"] == "review"


def test_exif_orientation_and_profile(tmp_path):
    image = Image.new("RGB", (120, 80), "orange")
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "Test photographer"
    path = tmp_path / "rotate.jpg"
    image.save(path, exif=exif)
    pixels, meta = decode(path)
    assert pixels.shape == (120, 80, 3)
    output = Image.Exif()
    output.load(meta["exif"])
    assert 274 not in output
    assert output[315] == "Test photographer"


def test_model_change_prevents_incompatible_analysis(store, photos, encoder):
    profile, _ = prepared(store, photos, encoder)
    class DifferentEncoder(encoder):
        version = "different"
    job = execute(store, analysis_job(store, profile, photos), DifferentEncoder)
    assert job["state"] == "failed"
    assert "modèle" in job["error"]


def test_200_references_and_1000_file_batch(store, encoder, tmp_path):
    paths = []
    generator = np.random.default_rng(10)
    for i in range(1000):
        path = tmp_path / f"bulk_{i:04}.png"
        Image.fromarray(generator.integers(20, 235, (32, 48, 3), dtype=np.uint8)).save(path)
        paths.append(str(path))
    profile = store.create_profile("Volume")
    assert execute(store, reference_job(store, profile, paths[:200]), encoder)["state"] == "done"
    reopened = Store(store.root)
    assert len(reopened.references(profile)) == 200
    reopened.close()
    job = execute(store, analysis_job(store, profile, paths), encoder)
    assert job["state"] == "done", job["error"]
    rows = store.photos(job["payload"]["batch"])
    assert len(rows) == 1000
    assert all("error" not in r["data"] for r in rows)


def test_corrupt_reference_does_not_abort_valid_references(store, photos, encoder, tmp_path):
    corrupt = tmp_path / "bad.png"
    corrupt.write_bytes(b"invalid")
    profile = store.create_profile("References")
    job = execute(store, reference_job(store, profile, [str(corrupt), *photos]), encoder)
    assert job["state"] == "done"
    assert len(job["payload"]["errors"]) == 1
    assert len(store.references(profile)) == 5


def test_paused_batch_requires_completion_and_keeps_snapshot(store, photos, encoder):
    profile = store.create_profile("Reprise")
    execute(store, reference_job(store, profile, photos[:2]), encoder)
    cancel = threading.Event()
    class CancellingEncoder(encoder):
        def encode(self, image):
            cancel.set()
            return super().encode(image)
    identifier = analysis_job(store, profile, photos)
    job = execute(store, identifier, CancellingEncoder, cancel)
    batch = job["payload"]["batch"]
    snapshot = store.batch(batch)["snapshot"]
    assert job["state"] == "paused"
    assert len(store.photos(batch)) == 1
    with pytest.raises(ValueError, match="terminée"):
        store.validate(batch)
    execute(store, reference_job(store, profile, photos[2:]), encoder)
    resumed = execute(store, identifier, encoder)
    assert resumed["state"] == "done"
    assert len(store.photos(batch)) == 5
    assert store.batch(batch)["snapshot"] == snapshot


def test_selection_feedback_does_not_dilute_retouch_learning(store, photos, encoder):
    profile, batch = prepared(store, photos, encoder)
    rows = store.photos(batch)
    rows[0]["data"]["recipe"]["temperature"] = .2
    rows[1]["data"]["decision"] = "reject"
    for row in rows[:2]:
        store.save_photo(row["id"], batch, row["path"], row["data"])
    store.validate(batch)
    snapshot = store.snapshot(profile, encoder.version)
    result = propose(rows[0]["data"]["features"], rows[0]["data"]["embedding"], snapshot)
    assert result["recipe"]["temperature"] == pytest.approx(.2)

