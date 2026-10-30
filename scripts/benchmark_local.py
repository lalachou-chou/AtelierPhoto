"""Real DINOv3 volume test. Synthetic images exercise throughput, not photo quality."""
import json
import queue
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import numpy as np
    from PIL import Image

    from atelier.pipeline import analysis_job, reference_job, run_job
    from atelier.store import Store
    directory = ROOT / "test-output" / ("benchmark-" + str(time.time_ns()))
    directory.mkdir(parents=True)
    generator = np.random.default_rng(53)
    paths = []
    for index in range(1000):
        path = directory / f"test-{index:04}.jpg"
        Image.fromarray(generator.integers(30, 220, (96, 128, 3), dtype=np.uint8)).save(path, quality=85)
        paths.append(str(path))
    store = Store(directory / "library")
    profile = store.create_profile("Benchmark synthétique")
    events = queue.Queue()
    start = time.perf_counter()
    identifier = reference_job(store, profile, paths[:200])
    run_job(store.root, identifier, events, threading.Event())
    assert store.job(identifier)["state"] == "done", store.job(identifier)
    refs_seconds = time.perf_counter() - start
    print(f"200 references, real DINOv3: {refs_seconds:.2f}s", flush=True)
    start = time.perf_counter()
    identifier = analysis_job(store, profile, paths)
    run_job(store.root, identifier, events, threading.Event())
    analysis_seconds = time.perf_counter() - start
    job = store.job(identifier)
    assert job["state"] == "done", job["error"]
    rows = store.photos(job["payload"]["batch"])
    assert len(rows) == 1000 and all("error" not in r["data"] for r in rows)
    peak_mb = None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(k, ctypes.c_size_t) for k in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            peak_mb = counters.PeakWorkingSetSize / 1024**2
    report = {"images": 1000, "references": 200, "input": "synthetic JPEG 128x96; not a full-resolution photo benchmark", "encoder": "real DINOv3 Small 448x448 ONNX float32 CPU", "reference_seconds": refs_seconds, "analysis_seconds": analysis_seconds, "peak_process_working_set_MiB": peak_mb, "errors": 0}
    (ROOT / "test-output" / "benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    store.close()


if __name__ == "__main__":
    main()
