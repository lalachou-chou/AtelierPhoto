"""Opt-in packaged-app smoke test. Writes only to its requested report directory."""
import json
import multiprocessing as mp
import os
import tempfile
import time
from pathlib import Path


def windows_ort_telemetry_registered():
    """Read the ML telemetry provider state for this process, without starting a trace."""
    import ctypes
    import struct
    import uuid
    from ctypes import wintypes

    guid = uuid.UUID("3a26b1ff-7484-7484-7484-15261f42614d")
    provider = (ctypes.c_ubyte * 16).from_buffer_copy(guid.bytes_le)
    query = ctypes.WinDLL("advapi32").EnumerateTraceGuidsEx
    query.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p,
                      wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    query.restype = wintypes.ULONG
    size = wintypes.ULONG()
    buffer = ctypes.create_string_buffer(4096)
    while True:
        result = query(1, ctypes.byref(provider), 16, buffer, len(buffer), ctypes.byref(size))
        if result != 122:  # ERROR_INSUFFICIENT_BUFFER
            break
        buffer = ctypes.create_string_buffer(size.value)
    if result == 4200:  # ERROR_WMI_GUID_NOT_FOUND: no registered instance
        return False
    if result:
        raise ctypes.WinError(result)
    count, _ = struct.unpack_from("<II", buffer)
    offset = 8
    for _ in range(count):
        next_offset, _, pid, _flags = struct.unpack_from("<IIII", buffer, offset)
        if pid == os.getpid():
            return True
        offset += next_offset
    return False


def self_test(report_path):
    import numpy as np
    from PIL import Image

    from .imaging import digest
    from .pipeline import (
        analysis_job,
        export_job,
        run_job,
        training_jobs,
        training_update_job,
    )
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

    # Two separate reportages exercise cumulative selection learning.
    rush = list(paths)
    for index in range(3, 12):
        path = root / f"test-{index}.png"
        Image.fromarray(generator.integers(20, 235, (64, 96, 3), dtype=np.uint8)).save(path)
        rush.append(str(path))
    (root / "kept").mkdir()
    kept = []
    for path in rush[:3] + rush[6:9]:
        target = root / "kept" / Path(path).name
        with Image.open(path) as image:
            Image.fromarray(np.clip(np.asarray(image, dtype=np.float32) * 1.05, 0, 255).astype(np.uint8)).save(target)
        kept.append(str(target))
    execute(training_jobs(store, profile, [
        {"name": "Diagnostic A", "rush": rush[:6], "kept": kept[:3]},
        {"name": "Diagnostic B", "rush": rush[6:], "kept": kept[3:]},
    ]))
    learned = store.model(profile)
    assert (learned["reportages"], learned["photos"], learned["kept"]) == (2, 12, 6)
    execute(training_update_job(store, profile, store.reportages(profile),
                                [{"name": "Références du diagnostic", "paths": paths}]))
    assert len(store.reference_groups(profile)) == 1
    assert len(store.references(profile, active_only=True)) == 3
    job = execute(analysis_job(store, profile, paths))
    batch = job["payload"]["batch"]
    rows = store.photos(batch)
    assert len(rows) == 3 and all("error" not in r["data"] for r in rows)
    for row in rows:
        row["data"].update(decision="keep", manual_decision=True)
    store.save_photos(rows)
    validation = store.validate(batch, profile)
    assert validation["updated"] >= 1 and validation["total"] >= 1
    exported = execute(export_job(store, batch, root / "exports"))
    assert len(exported["payload"]["outputs"]) == 3
    assert sorted(digest(p) for p in exported["payload"]["outputs"]) == sorted(originals)
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
    assert window.pixmap is not None, "L’aperçu de la photo ne s’affiche pas"
    assert window.model.rowCount() == 3
    window.store.delete_batch(batch, profile)
    assert window.store.batches(profile) == []
    assert window.store.learning_count(profile) == validation["total"]
    window.close()
    report = {"ok": True, "model": model_version, "references": 3, "reference_groups": 1,
              "analyzed": 3, "exported": 3, "trained": True,
              "originals_unchanged": True, "spawn_workers": True, "qt_preview": True,
              "batch_deleted": True, "learning_preserved": True,
              "training_reportages": learned["reportages"]}
    if os.name == "nt":
        from .dino import DinoEncoder

        encoder = DinoEncoder()
        with Image.open(paths[0]) as image:
            encoder.encode(image)
        if windows_ort_telemetry_registered():
            raise RuntimeError("Le moteur DINOv3 s’est inscrit à la télémétrie Windows.")
        report["onnx_telemetry_provider_registered"] = False
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
