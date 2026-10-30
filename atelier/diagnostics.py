"""Opt-in packaged-app smoke test. Writes only to its requested report directory."""
import json
import multiprocessing as mp
import os
import tempfile
import time
from pathlib import Path


def self_test(report_path):
    import numpy as np
    from PIL import Image

    from .imaging import digest
    from .pipeline import analysis_job, export_job, reference_job, run_job, training_job
    from .store import Store

    report_path = Path(report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="atelier-self-test-", dir=report_path.parent))
    paths = []
    generator = np.random.default_rng(21)
    for index in range(3):
        path = root / f"test-{index}.png"
        Image.fromarray(generator.integers(20, 235, (64, 96, 3), dtype=np.uint8)).save(path)
        paths.append(str(path))
    originals = [digest(p) for p in paths]
    store = Store(root / "library")
    profile = store.create_profile("Diagnostic")
    context = mp.get_context("spawn")

    def execute(identifier):
        events, cancel = context.Queue(), context.Event()
        process = context.Process(target=run_job, args=(str(store.root), identifier, events, cancel))
        process.start()
        process.join(timeout=120)
        if process.is_alive():
            process.terminate()
            process.join()
            raise RuntimeError("Le processus de diagnostic n’a pas terminé.")
        code = process.exitcode
        process.close()
        events.close()
        job = store.job(identifier)
        if code or job["state"] != "done":
            raise RuntimeError(f"Diagnostic du moteur : {job['error']} (code {code})")
        return job

    # Learning from a sorted reportage: six rush photos, two delivered edits.
    rush = paths + []
    for index in range(3, 6):
        path = root / f"test-{index}.png"
        Image.fromarray(generator.integers(20, 235, (64, 96, 3), dtype=np.uint8)).save(path)
        rush.append(str(path))
    (root / "kept").mkdir()
    kept = []
    for path in rush[:2]:
        target = root / "kept" / Path(path).name
        with Image.open(path) as image:
            Image.fromarray(np.clip(np.asarray(image, dtype=np.float32) * 1.05, 0, 255).astype(np.uint8)).save(target)
        kept.append(str(target))
    execute(training_job(store, profile, rush, kept, "Diagnostic"))
    assert store.model(profile)["kept"] == 2
    execute(reference_job(store, profile, paths))
    job = execute(analysis_job(store, profile, paths))
    batch = job["payload"]["batch"]
    rows = store.photos(batch)
    assert len(rows) == 3 and all("error" not in r["data"] for r in rows)
    for row in rows:
        row["data"]["decision"] = "keep"
        store.save_photo(row["id"], batch, row["path"], row["data"])
    rows[0]["data"]["recipe"]["exposure"] += .2
    store.save_photos(rows)
    validation = store.validate(batch, profile)
    assert validation["updated"] >= 1 and validation["total"] >= 1
    exported = execute(export_job(store, batch, root / "exports"))
    assert len(exported["payload"]["outputs"]) == 3
    assert [digest(p) for p in paths] == originals
    model_version = store.batch(batch)["snapshot"]["model"]
    store.close()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from .app import Window
    app = QApplication.instance() or QApplication([])
    window = Window(root / "library")
    window.show()
    limit = time.monotonic() + 30
    while window.pixmap is None and time.monotonic() < limit:
        app.processEvents()
        time.sleep(.03)
    assert window.pixmap is not None, "Le processus d’aperçu ne répond pas"
    assert window.model.rowCount() == 3
    window.stop_preview()
    window.store.delete_batch(batch, profile)
    assert window.store.batches(profile) == []
    assert window.store.learning_count(profile) == validation["total"]
    window.close()
    report = {"ok": True, "model": model_version, "references": 3, "analyzed": 3, "exported": 3, "trained": True,
              "originals_unchanged": True, "spawn_workers": True, "qt_preview": True,
              "batch_deleted": True, "learning_preserved": True}
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
