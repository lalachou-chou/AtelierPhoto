"""Repeatable real-DINOv3 benchmark on synthetic 2400x1600 JPEGs."""
import argparse
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
    from atelier.pipeline import analysis_job, run_job, training_job
    from atelier.store import Store

    parser = argparse.ArgumentParser()
    parser.add_argument("label")
    args = parser.parse_args()
    directory = ROOT / "test-output" / "workflow-benchmark"
    directory.mkdir(parents=True, exist_ok=True)
    rush, kept = [], []
    rng = np.random.default_rng(53)
    for i in range(24):
        path = directory / f"photo-{i:03}.jpg"
        if not path.exists():
            pixels = rng.integers(25, 220, (400, 600, 3), dtype=np.uint8)
            Image.fromarray(pixels).resize((2400, 1600)).save(path, quality=92)
        rush.append(str(path))
        if i < 8:
            target = directory / "kept" / path.name
            target.parent.mkdir(exist_ok=True)
            if not target.exists():
                with Image.open(path) as image:
                    Image.fromarray(np.clip(np.asarray(image).astype(float) * 1.05, 0, 255).astype(np.uint8)).save(target, quality=92)
            kept.append(str(target))
    store = Store(directory / f"library-{args.label}-{time.time_ns()}")
    profile = store.create_profile("Benchmark")
    report = {"input": "24 synthetic 2400x1600 JPEGs, 8 edited copies; real DINOv3 CPU"}
    for kind, identifier in (("training", training_job(store, profile, rush, kept)),):
        start = time.perf_counter()
        run_job(store.root, identifier, queue.Queue(), threading.Event())
        job = store.job(identifier)
        assert job["state"] == "done", job["error"]
        report[kind + "_seconds"] = time.perf_counter() - start
    identifier = analysis_job(store, profile, rush)
    start = time.perf_counter()
    run_job(store.root, identifier, queue.Queue(), threading.Event())
    job = store.job(identifier)
    assert job["state"] == "done", job["error"]
    report["analysis_seconds"] = time.perf_counter() - start
    report["errors"] = sum("error" in r["data"] for r in store.photos(job["payload"]["batch"]))
    store.close()
    (directory / f"{args.label}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
