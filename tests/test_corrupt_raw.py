"""Corrupt RAW files are set aside without blocking imports or profile training."""
import io
import queue
import struct
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog

from atelier import imaging, pipeline
from atelier.app import Window, quarantine_message
from atelier.config import QUARANTINE_DIR, discover
from atelier.cr2 import broken_raw_strip, embedded_jpeg
from atelier.imaging import CorruptPhoto
from atelier.pipeline import analysis_job, run_job, training_update_job
from atelier.recovery_dialog import RecoveryDialog


class Encoder:
    version = "corrupt-test"

    def encode(self, image):
        vector = np.asarray(image).mean(axis=(0, 1)) + 1
        return (vector / np.linalg.norm(vector)).tolist()


@pytest.fixture
def corrupt_cr2(monkeypatch):
    """Files named *.CR2 decode as a damaged RAW; others decode normally."""
    real = pipeline.decode

    def decode(path):
        if Path(path).suffix.lower() == ".cr2":
            raise CorruptPhoto("RAW corrompu ou incomplet : Data error or unsupported file format")
        return real(path)

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
    job = execute(store, training_update_job(store, profile, [], [{"name": "Exemples", "paths": [str(bad), str(good)]}]))
    assert job["state"] == "done" and not job["payload"]["errors"]
    assert len(store.references(profile)) == 1
    assert (tmp_path / QUARANTINE_DIR / "bad.CR2").exists()


def cr2_with_bad_raw_offset(path):
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), "orange").save(buffer, "JPEG")
    jpeg = buffer.getvalue()

    def directory(offset, length):
        return (struct.pack("<H", 3) + struct.pack("<HHII", 259, 3, 1, 6)
                + struct.pack("<HHII", 273, 4, 1, offset)
                + struct.pack("<HHII", 279, 4, 1, length) + bytes(4))

    header = b"II*\x00" + struct.pack("<I", 16) + b"CR\x02\x00" + struct.pack("<I", 58)
    path.write_bytes(header + directory(100, len(jpeg)) + directory(100 + len(jpeg), 4) + jpeg + b"xxxx")
    return jpeg


def test_retry_joint_rush_and_references_recovers_camera_jpeg(store, tmp_path, monkeypatch):
    profile = store.create_profile("Test")
    record = reportage(tmp_path / "A", corrupt=())
    bad = tmp_path / "A" / "rush" / "bad.CR2"
    jpeg = cr2_with_bad_raw_offset(bad)
    record["rush"].append(str(bad))
    group = {"name": "Exemples", "paths": [str(bad), record["kept"][0]]}
    identifier = training_update_job(store, profile, [record], [group])
    # Reproduce a task saved by the previous decoder at the final cursor.
    with monkeypatch.context() as patch:
        patch.setattr(imaging, "broken_raw_strip", lambda path: False)
        failed = execute(store, identifier)
        assert failed["state"] == "failed" and failed["cursor"] == len(failed["payload"]["items"])
    job = execute(store, identifier)
    assert job["state"] == "done", job["error"]
    assert store.model(profile)["photos"] == 8
    assert len(store.references(profile)) == 1
    assert str(bad) not in store.reportages(profile)[0]["rush"]
    assert str(bad) not in store.reference_groups(profile)[0]["paths"]
    [entry] = job["payload"]["quarantined"]
    assert "Récupérer les photos corrompues" in quarantine_message([entry])
    assert list(Path(entry["to"]).parent.iterdir()) == [Path(entry["to"])]
    [pending] = store.quarantined(profile)
    assert pending["path"] == entry["to"] and pending["output"] is None
    identifier = pipeline.recovery_job(store, profile, [entry["to"]], tmp_path)
    done = execute(store, identifier)
    assert done["state"] == "done" and not done["payload"]["errors"]
    recovered = Path(store.quarantined(profile)[0]["output"])
    assert recovered.read_bytes() == jpeg and recovered.parent == tmp_path
    assert pipeline.recover_one(entry["to"], tmp_path) == str(recovered)


def test_cr2_with_unusable_preview_or_no_evidence_of_raw_damage(tmp_path):
    path = tmp_path / "sample.CR2"
    jpeg = cr2_with_bad_raw_offset(path)
    data = path.read_bytes()
    path.write_bytes(data.replace(jpeg, b"x" * len(jpeg)))
    assert broken_raw_strip(path) and embedded_jpeg(path) is None
    path.write_bytes(data[:-4] + b"\xff\xd8\xff\xd9")
    assert not broken_raw_strip(path)
    with pytest.raises(ValueError, match="boîtier non reconnu") as failure:
        imaging.decode(path)
    assert not isinstance(failure.value, CorruptPhoto)


def test_recovery_button_is_opt_in_and_survives_deleted_batch(qapp, store, tmp_path, monkeypatch):
    profile = store.create_profile("Import")
    good, broken, other = [tmp_path / name for name in ("good.CR2", "broken.CR2", "other.CR2")]
    jpeg = cr2_with_bad_raw_offset(good)
    cr2_with_bad_raw_offset(other)
    broken.write_bytes(good.read_bytes().replace(jpeg, bytes(len(jpeg))))
    job = execute(store, analysis_job(store, profile, [str(path) for path in (good, broken, other)]))
    store.delete_batch(job["batch"], profile)
    destination = tmp_path / "Copies"
    destination.mkdir()
    existing = destination / "good-recuperee.jpg"
    existing.write_bytes(b"existing")
    window = Window(store.root)
    launched = []
    monkeypatch.setattr(window, "launch", launched.append)
    try:
        def select(dialog):
            assert not dialog.paths() and not dialog.recover.isEnabled()
            for i in range(dialog.list.count()):
                item = dialog.list.item(i)
                if Path(item.data(Qt.ItemDataRole.UserRole)).name != other.name:
                    item.setCheckState(Qt.CheckState.Checked)
            assert dialog.recover.isEnabled()
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(RecoveryDialog, "exec", lambda dialog: QDialog.DialogCode.Rejected)
        window.recovery_button.click()
        assert not launched
        monkeypatch.setattr(RecoveryDialog, "exec", select)
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: "")
        window.recovery_button.click()
        assert not launched
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(destination))
        window.recovery_button.click()
        identifier, = launched
        result = execute(store, identifier)
        assert result["state"] == "done"
        assert [e["file"] for e in result["payload"]["errors"]] == [broken.name]
        new_file, = result["payload"]["outputs"]
        assert Path(new_file).read_bytes() == jpeg and existing.read_bytes() == b"existing"
        entries = {Path(e["original"]).name: e for e in window.store.quarantined(profile)}
        assert entries[good.name]["output"] == new_file
        assert entries[broken.name]["error"] and not entries[other.name]["output"]
        assert all(Path(e["path"]).exists() for e in entries.values())
    finally:
        window.close()




def test_recognizable_truncated_jpeg_in_references_can_be_recovered(store, tmp_path):
    profile = store.create_profile("JPEG")
    photo = tmp_path / "ref.jpg"
    Image.new("RGB", (80, 60), "orange").save(photo)
    data = photo.read_bytes()
    photo.write_bytes(data[:-2])
    job = execute(store, training_update_job(store, profile, [], [{"name": "Photos", "paths": [str(photo)]}]))
    assert job["state"] == "done" and not store.references(profile)
    entry, = store.quarantined(profile)
    assert entry["output"] is None
    done = execute(store, pipeline.recovery_job(store, profile, [entry["path"]], tmp_path))
    assert not done["payload"]["errors"]
    assert Path(done["payload"]["outputs"][0]).read_bytes() == data


def test_png_recovers_pixels_past_damaged_metadata(store, tmp_path):
    profile = store.create_profile("PNG")
    path = tmp_path / "photo.png"
    original = Image.new("RGB", (36, 40), (24, 93, 190))
    original.save(path)
    png = path.read_bytes()
    damaged_text = struct.pack(">I", 3) + b"tEXtA\x00B" + bytes(4)
    path.write_bytes(png[:33] + damaged_text + png[33:])
    job = execute(store, analysis_job(store, profile, [str(path)]))
    assert job["state"] == "done"
    entry, = store.quarantined(profile)
    assert not entry["output"]
    done = execute(store, pipeline.recovery_job(store, profile, [entry["path"]], tmp_path))
    assert not done["payload"]["errors"]
    with Image.open(done["payload"]["outputs"][0]) as recovered:
        assert recovered.tobytes() == original.tobytes()



def test_quarantine_moves_adobe_and_darktable_sidecars(tmp_path):
    photo = tmp_path / "DSC0001.NEF"
    photo.write_bytes(b"damaged")
    (tmp_path / "DSC0001.xmp").write_text("<adobe/>", encoding="utf-8")
    (tmp_path / "DSC0001.NEF.xmp").write_text("<darktable/>", encoding="utf-8")
    (tmp_path / QUARANTINE_DIR).mkdir()
    (tmp_path / QUARANTINE_DIR / "DSC0001.NEF").write_bytes(b"earlier")
    target = Path(pipeline.quarantine(photo))
    assert target == tmp_path / QUARANTINE_DIR / "DSC0001 (2).NEF"
    assert (target.parent / "DSC0001 (2).xmp").read_text(encoding="utf-8") == "<adobe/>"
    assert (target.parent / "DSC0001 (2).NEF.xmp").read_text(encoding="utf-8") == "<darktable/>"
    assert list(tmp_path.iterdir()) == [tmp_path / QUARANTINE_DIR]
