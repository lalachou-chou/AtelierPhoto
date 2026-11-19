import queue
import threading

import numpy as np
from PIL import Image

from atelier import performance
from atelier.pipeline import run_job, training_update_job

GB = 1024 ** 3


class Encoder:
    version = "performance-test"

    def encode(self, image):
        vector = np.asarray(image, dtype=np.float64).mean(axis=(0, 1)) + 1
        return (vector / np.linalg.norm(vector)).tolist()


def test_plan_uses_large_computers_and_protects_modest_ones():
    big = performance.plan("fast", 28, 64 * GB)
    assert (big.workers, big.threads, big.modest) == (8, 2, False)
    assert performance.plan("balanced", 28, 64 * GB).workers == 7
    light = performance.plan("light", 28, 64 * GB)
    assert (light.workers, light.threads) == (1, 1)
    # Typical 8-core laptop: one core stays free for the interface.
    laptop = performance.plan("fast", 8, 16 * GB)
    assert (laptop.workers, laptop.threads, laptop.modest) == (3, 2, False)
    assert performance.plan("balanced", 8, 16 * GB).workers == 2
    # Many cores but little memory: prepared photos must fit in 30 % of it.
    tight = performance.plan("fast", 16, 4 * GB)
    assert tight.workers == 2 and tight.modest
    # Dual core: one photo at a time whatever the load.
    for mode in performance.MODES:
        small = performance.plan(mode, 2, 4 * GB)
        assert small.workers == 1 and small.modest
    assert performance.plan("fast", 1, None).workers == 1
    assert performance.plan("unknown", 28, 64 * GB).mode == performance.DEFAULT_MODE


def test_read_mode_follows_a_shared_value():
    class Shared:
        value = 2

    assert performance.read_mode(Shared()) == "light"
    assert performance.read_mode("balanced") == "balanced"
    assert performance.read_mode(None) == performance.DEFAULT_MODE
    Shared.value = 99
    assert performance.read_mode(Shared()) == performance.DEFAULT_MODE


def test_raw_preview_integer_division_keeps_the_same_bytes():
    values = np.arange(65536, dtype=np.uint16)
    assert np.array_equal((values / 257).astype(np.uint8), (values // 257).astype(np.uint8))


def references(store, profile):
    return sorted((r["name"], r["digest"], r["data"]["embedding"], r["data"]["features"])
                  for r in store.references(profile))


def test_parallel_references_and_live_load_change_store_the_same_results(store, tmp_path):
    rng = np.random.default_rng(4)
    paths = []
    for i in range(9):
        path = tmp_path / f"reference-{i}.png"
        Image.fromarray(rng.integers(20, 235, (40, 56, 3), dtype=np.uint8)).save(path)
        paths.append(str(path))
    duplicate = tmp_path / "copy.png"
    duplicate.write_bytes((tmp_path / "reference-2.png").read_bytes())
    paths.append(str(duplicate))

    class Load:
        """The user switches to the light load in the middle of the task."""

        reads = 0

        @property
        def value(self):
            self.reads += 1
            return 0 if self.reads < 5 else 2

    results = []
    for name, workers, load in (("Séquentiel", 0, None), ("Parallèle", 4, None), ("Auto", None, Load())):
        profile = store.create_profile(name)
        job = training_update_job(store, profile, [], [{"name": "Exemples", "paths": paths}])
        run_job(store.root, job, queue.SimpleQueue(), threading.Event(), Encoder, workers, load)
        assert store.job(job)["state"] == "done"
        results.append(references(store, profile))
    # The copy is linked to the reference it duplicates, never prepared twice.
    assert len(results[0]) == len({r[1] for r in results[0]}) == len(paths) - 1
    assert results[0] == results[1] == results[2]


def test_priority_note_only_where_priority_cannot_rise_again():
    assert performance.priority_note("win32") == ""
    assert "tâche suivante" in performance.priority_note("darwin")
