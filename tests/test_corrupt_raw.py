"""Corrupt RAW files are set aside without blocking imports or profile training."""
import queue
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from atelier import pipeline
from atelier.config import QUARANTINE_DIR, discover
from atelier.imaging import CorruptPhoto
from atelier.pipeline import analysis_job, reference_job, run_job, training_update_job


class Encoder:
    version = "corrupt-test"

    def encode(self, image):
        vector = np.asarray(image).mean(axis=(0, 1)) + 1
        return (vector / np.linalg.norm(vector)).tolist()


@pytest.fixture
def corrupt_cr2(monkeypatch):
    """Files named *.CR2 decode as a damaged RAW; others decode normally."""
    real = pipeline.decode

    def decode(path, preview=False):
        if Path(path).suffix.lower() == ".cr2":
            raise CorruptPhoto("RAW corrompu ou incomplet : Data error or unsupported file format")
        return real(path, preview)

    monkeypatch.setattr(pipeline, "decode", decode)


def execute(store, identifier, workers=2):
    run_job(store.root, identifier, queue.SimpleQueue(), threading.Event(), Encoder, workers)
    return store.job(identifier)


def reportage(root, corrupt=("DSC0004",)):
    (root / "rush").mkdir(parents=True)
    (root / "kept").mkdir()
    rng = np.random.default_rng(0)
    rush, kept = [], []
    for i in range(8):
        pixels = rng.integers(30, 220, (32, 48, 3), dtype=np.uint8)
        name = f"DSC{i:04}"
        source = root / "rush" / (name + (".CR2" if name in corrupt else ".png"))
        if name in corrupt:
            source.write_bytes(b"II*\x00damaged raw")
            (root / "rush" / f"{name}.xmp").write_text("<x/>", encoding="utf-8")
        else:
            Image.fromarray(pixels).save(source)
        rush.append(str(source))
        if i < 3:
            target = root / "kept" / f"{name}.png"
            Image.fromarray((pixels * .9).astype(np.uint8)).save(target)
            kept.append(str(target))
    return {"name": root.name, "rush": rush, "kept": kept}


@pytest.mark.parametrize("workers", [0, 2])
def test_training_finishes_and_moves_corrupt_raw(store, tmp_path, corrupt_cr2, workers):
    profile = store.create_profile("Mariages")
    record = reportage(tmp_path / "Rush A")
    job = execute(store, training_update_job(store, profile, [record]), workers)
    assert job["state"] == "done", job["error"]
    assert not job["payload"]["errors"]
    assert store.model(profile)["photos"] == 7  # every readable photo was learned
    assert store.unfinished_jobs(profile) == []
    moved = tmp_path / "Rush A" / "rush" / QUARANTINE_DIR / "DSC0004.CR2"
    assert moved.is_file() and moved.with_suffix(".xmp").is_file()
    assert not (tmp_path / "Rush A" / "rush" / "DSC0004.CR2").exists()
    [entry] = job["payload"]["quarantined"]
    assert entry["file"] == "DSC0004.CR2" and entry["to"] == str(moved)
    # The catalog forgets the moved file: applying again does not look for it.
    stored = store.reportages(profile)[0]
    assert len(stored["rush"]) == 7 and not any("DSC0004" in p for p in stored["rush"])
    again = execute(store, training_update_job(store, profile, store.reportages(profile)), workers)
    assert again["state"] == "done", again["error"]
    # Re-adding the folder does not scan the quarantine folder.
    assert not any(QUARANTINE_DIR in p for p in discover([tmp_path / "Rush A"]))


def test_corrupt_raw_in_new_reportage_does_not_discard_previous_profile(store, tmp_path, corrupt_cr2):
    profile = store.create_profile("Cumul")
    first = reportage(tmp_path / "A", corrupt=())
    assert execute(store, training_update_job(store, profile, [first]))["state"] == "done"
    second = reportage(tmp_path / "B", corrupt=("DSC0001", "DSC0006"))
    job = execute(store, training_update_job(store, profile, store.reportages(profile) + [second]))
    assert job["state"] == "done", job["error"]
    assert store.model(profile)["photos"] == 8 + 6
    assert len(job["payload"]["quarantined"]) == 2


def test_import_records_and_moves_corrupt_raw(store, tmp_path, corrupt_cr2):
    profile = store.create_profile("Import")
    folder = tmp_path / "Lot"
    folder.mkdir()
    for i in range(4):
        Image.new("RGB", (40, 30), (40 * i, 90, 120)).save(folder / f"IMG{i}.png")
    (folder / "IMG9.CR2").write_bytes(b"damaged")
    job = execute(store, analysis_job(store, profile, discover([folder])))
    assert job["state"] == "done", job["error"]
    rows = store.photos(job["batch"])
    assert len(rows) == 5
    [error] = [r for r in rows if "error" in r["data"]]
    assert QUARANTINE_DIR in error["data"]["error"]
    assert Path(error["path"]) == folder / QUARANTINE_DIR / "IMG9.CR2"
    assert not (folder / "IMG9.CR2").exists()
    assert store.batch_ready(job["batch"])
    assert len(discover([folder])) == 4


def test_quarantine_never_overwrites(tmp_path):
    for i in range(2):
        (tmp_path / "a.CR2").write_bytes(bytes([i]))
        pipeline.quarantine(tmp_path / "a.CR2")
    folder = tmp_path / QUARANTINE_DIR
    assert (folder / "a.CR2").read_bytes() == b"\x00"
    assert (folder / "a (2).CR2").read_bytes() == b"\x01"


def test_reference_corrupt_raw_is_set_aside(store, tmp_path, corrupt_cr2):
    profile = store.create_profile("Références")
    good, bad = tmp_path / "good.png", tmp_path / "bad.CR2"
    Image.new("RGB", (32, 32), "orange").save(good)
    bad.write_bytes(b"damaged")
    job = execute(store, reference_job(store, profile, [str(bad), str(good)]))
    assert job["state"] == "done" and not job["payload"]["errors"]
    assert len(store.references(profile)) == 1
    assert (tmp_path / QUARANTINE_DIR / "bad.CR2").exists()

