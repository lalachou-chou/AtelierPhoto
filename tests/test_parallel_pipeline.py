import queue
import threading
from pathlib import Path

from atelier.pipeline import analysis_job, run_job, training_job


def execute(store, identifier, encoder, workers, cancel=None, events=None):
    run_job(store.root, identifier, events or queue.Queue(), cancel or threading.Event(), encoder, workers)
    return store.job(identifier)


def test_parallel_learning_and_analysis_match_serial(store, photos, encoder):
    extra = Path(photos[0]).with_name("extra.png")
    extra.write_bytes(Path(photos[-1]).read_bytes())
    photos = photos + [str(extra)]
    results = []
    for workers in (0, 2):
        profile = store.create_profile(str(workers))
        # Distinct paths for edited copies, as in a delivered reportage.
        kept = []
        for path in photos[:3]:
            source = Path(path)
            target = source.parent / "kept" / source.name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(source.read_bytes())
            kept.append(str(target))
        trained = execute(store, training_job(store, profile, photos, kept), encoder, workers)
        assert trained["state"] == "done", trained["error"]
        analyzed = execute(store, analysis_job(store, profile, photos), encoder, workers)
        assert analyzed["state"] == "done", analyzed["error"]
        rows = store.photos(analyzed["payload"]["batch"])
        results.append((store.model(profile), [
            {key: row["data"][key] for key in ("features", "embedding", "digest", "recipe", "style", "decision")}
            for row in rows
        ]))
    assert results[0] == results[1]


def test_prefetch_failure_does_not_advance_cursor_and_can_resume(store, photos, encoder, tmp_path):
    missing = tmp_path / "missing.png"
    profile = store.create_profile("Resume")
    identifier = analysis_job(store, profile, [photos[0], str(missing), photos[1]])
    failed = execute(store, identifier, encoder, 2)
    assert failed["state"] == "failed"
    assert failed["cursor"] == 1
    assert len(store.photos(failed["payload"]["batch"])) == 1
    missing.write_bytes(Path(photos[2]).read_bytes())
    resumed = execute(store, identifier, encoder, 2)
    assert resumed["state"] == "done", resumed["error"]
    assert len(store.photos(resumed["payload"]["batch"])) == 3


def test_pause_only_commits_current_photo_despite_prefetch(store, photos, encoder):
    profile = store.create_profile("Pause")
    cancel = threading.Event()

    class Events(queue.Queue):
        def put(self, event):
            if event["type"] == "progress":
                cancel.set()
            super().put(event)

    identifier = analysis_job(store, profile, photos)
    paused = execute(store, identifier, encoder, 2, cancel, Events())
    assert paused["state"] == "paused"
    assert paused["cursor"] == 1
    assert len(store.photos(paused["payload"]["batch"])) == 1
    resumed = execute(store, identifier, encoder, 2)
    assert resumed["state"] == "done"
    assert len(store.photos(resumed["payload"]["batch"])) == len(photos)
