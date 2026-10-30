import copy
import queue
import threading
import time

import pytest
from PySide6.QtTest import QTest

from atelier.analysis import finalize, propose, reselect
from atelier.app import Window
from atelier.pipeline import export_job, run_job, selection_job
from atelier.selection import rates
from atelier.store import default_profile, uid


def cached_batch(store, value=.5):
    profile = store.create_profile("Sélectivité")
    snapshot = store.snapshot(profile, "cached-test")
    batch = store.create_batch(profile, "Lot", snapshot, value)
    for i in range(30):
        stats = {"luma": .5, "spread": .2, "saturation": .2, "sharpness": .01,
                 "peak": .02, "noise": .001, "black": 0., "white": 0., "rgb": [.5, .5, .5]}
        data = propose(stats, [1., 0.], snapshot, value)
        data.update(features=stats, embedding=[1., 0.], digest=str(i), time=i * 1000.)
        # No source files exist: selection must use only the cached analysis.
        store.save_photo(uid(), batch, f"missing/photo-{i:02}.jpg", data)
    store.save_photos(finalize(store.photos(batch), snapshot, value))
    return batch


def execute(store, identifier, cancel=None):
    def no_encoder():
        raise AssertionError("A new image analysis must not be started")
    run_job(store.root, identifier, queue.SimpleQueue(), cancel or threading.Event(), no_encoder)
    return store.job(identifier)


def test_selection_changes_existing_batch_and_requires_revalidation(store, tmp_path):
    batch = cached_batch(store)
    store.validate(batch)
    initial = store.photos(batch)
    counts = []
    for value in (0., 1., 0.):
        task = selection_job(store, batch, value)
        assert not store.batch_ready(batch)
        with pytest.raises(ValueError, match="Terminez"):
            export_job(store, batch, tmp_path)
        job = execute(store, task)
        assert job["state"] == "done", job["error"]
        assert store.batch_ready(batch)
        assert store.batch(batch)["selectivity"] == value
        rows = store.photos(batch)
        counts.append(sum(row["data"]["decision"] == "keep" for row in rows))
        assert all(not row["data"]["validated"] for row in rows)
        for before, after in zip(initial, rows, strict=True):
            for key in ("recipe", "initial_recipe", "base_recipe", "style", "features", "embedding"):
                assert before["data"][key] == after["data"][key]
        with pytest.raises(ValueError, match="Validez"):
            export_job(store, batch, tmp_path)
    assert counts[0] == counts[2] > counts[1]
    store.validate(batch)
    assert store.learning_count(store.batch(batch)["profile"]) == 0
    assert export_job(store, batch, tmp_path)


def test_manual_choices_and_retouched_photos_survive_repeated_selection(store):
    batch = cached_batch(store)
    rows = store.photos(batch)
    # An older manual correction and a new explicit confirmation of a proposal.
    rows[0]["data"]["decision"] = "reject" if rows[0]["data"]["proposed"] == "keep" else "keep"
    rows[1]["data"]["manual_decision"] = True
    rows[2]["data"]["recipe"]["exposure"] = .3
    store.save_photos(rows)
    store.validate(batch)
    store.set_filter(batch, False)
    before = store.photos(batch)
    feedback = store.rows("SELECT * FROM feedback")
    for value in (1., 0., 1.):
        job = execute(store, selection_job(store, batch, value))
        assert job["state"] == "done", job["error"]
        after = store.photos(batch)
        for i in (0, 1):
            assert after[i]["data"]["decision"] == before[i]["data"]["decision"]
            assert after[i]["data"]["manual_decision"]
            assert after[i]["data"]["reasons"].count("Votre choix manuel est conservé") == 1
        assert after[2]["data"]["recipe"] == before[2]["data"]["recipe"]
        assert not store.batch(batch)["filter_enabled"]
        assert store.rows("SELECT * FROM feedback") == feedback
    store.validate(batch)
    assert store.learning_count(store.batch(batch)["profile"]) == 3


def test_reselection_refreshes_technical_verdict_and_does_not_duplicate_reasons(store):
    batch = cached_batch(store)
    snapshot = store.batch(batch)["snapshot"]
    rows = store.photos(batch)
    rows[0]["data"]["features"].update(peak=.0002, sharpness=.0002)
    rows[1]["data"]["digest"] = rows[2]["data"]["digest"]
    rows.append({"id": "error", "data": {"decision": "error", "error": "Illisible"}})
    initial = copy.deepcopy(rows)
    strict = reselect(rows, snapshot, 1.)
    assert strict[0]["data"]["blocked"]
    relaxed = reselect(strict, snapshot, 0.)
    assert not relaxed[0]["data"]["blocked"]
    expected = reselect(initial, snapshot, 0.)
    assert relaxed == expected
    assert relaxed[2]["data"]["decision"] == "reject"
    assert relaxed[-1] == initial[-1]


def test_paused_selection_preserves_batch_and_can_resume(store):
    batch = cached_batch(store)
    before = (store.batch(batch), store.photos(batch))
    identifier = selection_job(store, batch, 1.)
    cancel = threading.Event()
    cancel.set()
    assert execute(store, identifier, cancel)["state"] == "paused"
    assert (store.batch(batch), store.photos(batch)) == before
    assert not store.batch_ready(batch)
    assert execute(store, identifier)["state"] == "done"
    assert store.batch(batch)["selectivity"] == 1.


def test_failed_selection_leaves_database_unchanged(store, monkeypatch):
    batch = cached_batch(store)
    before = (store.batch(batch), store.photos(batch))
    identifier = selection_job(store, batch, 1.)
    def fail(*args):
        raise RuntimeError("Interrupted calculation")
    monkeypatch.setattr("atelier.analysis.finalize", fail)
    assert execute(store, identifier)["state"] == "failed"
    assert (store.batch(batch), store.photos(batch)) == before
    store.delete_job(identifier, store.batch(batch)["profile"])
    assert store.batch_ready(batch)
    assert (store.batch(batch), store.photos(batch)) == before


@pytest.mark.parametrize("kind", ["analysis", "export", "selection"])
def test_selection_refuses_unfinished_batch_tasks(store, kind):
    batch = cached_batch(store)
    identifier = store.new_job(store.batch(batch)["profile"], kind, {"batch": batch})
    store.update_job(identifier, state="paused")
    with pytest.raises(ValueError, match="Gérer les tâches"):
        selection_job(store, batch, 1.)
    assert store.batch(batch)["selectivity"] == .5


def test_slider_loads_batch_setting_without_recalculating_and_launches_on_change(qapp, store, monkeypatch):
    batch = cached_batch(store, .2)
    profile = store.batch(batch)["profile"]
    other = store.create_batch(profile, "Autre", store.batch(batch)["snapshot"], .8)
    monkeypatch.setattr(Window, "request_preview", lambda *_: None)
    launched = []
    monkeypatch.setattr(Window, "launch", lambda self, identifier: launched.append(identifier))
    window = Window(store.root)
    try:
        assert window.current_batch == other and window.selectivity.value() == 80
        window.batches.setCurrentRow(1)
        assert window.current_batch == batch and window.selectivity.value() == 20
        assert not launched
        window.selectivity.setValue(75)
        assert len(launched) == 1
        job = store.job(launched[0])
        assert job["kind"] == "selection"
        assert job["payload"] == {"batch": batch, "selectivity": .75}
        assert store.batch(other)["selectivity"] == .8
    finally:
        window.close()


def test_window_recalculates_in_worker_and_restores_selected_batch(qapp, store, monkeypatch):
    batch = cached_batch(store)
    profile = store.batch(batch)["profile"]
    store.create_batch(profile, "Plus récent", store.batch(batch)["snapshot"], .8)
    monkeypatch.setattr(Window, "request_preview", lambda *_: None)
    errors = []
    monkeypatch.setattr(Window, "error", lambda self, error: errors.append(str(error)))
    window = Window(store.root)
    try:
        window.batches.setCurrentRow(1)
        window.selectivity.setValue(0)
        assert window.busy() and not window.selectivity.isEnabled()
        deadline = time.monotonic() + 15
        while window.busy() and time.monotonic() < deadline:
            QTest.qWait(20)
        assert not window.busy() and not errors
        assert window.current_batch == batch
        assert window.selectivity.value() == 0 and window.selectivity.isEnabled()
        assert window.rows == store.photos(batch)
        assert "Validez à nouveau" in window.progress_label.text()
        assert "10 retenues" in window.summary.text()
    finally:
        if window.busy():
            window.process.terminate()
            window.process.join()
            window.poll()
        window.close()


@pytest.mark.parametrize("source", ["profil par défaut", "défaut", None, "profil"])
def test_default_target_is_independent_of_corpus_but_personal_rate_is_preserved(source):
    selector = copy.deepcopy(default_profile()["selector"]) if source else None
    if selector:
        selector.update(source=source, rate=.8)
    snapshot = {"model": selector["encoder"] if selector else "no-model",
                "selector": selector, "references": [], "feedback": []}
    stats = {"luma": .5, "spread": .2, "saturation": .2, "sharpness": .01,
             "peak": .02, "noise": .001, "black": 0., "white": 0., "rgb": [.5] * 3}
    rows = []
    for i in range(100):
        embedding = [1.] + [0.] * 383
        data = propose(stats, embedding, snapshot)
        data.update(features=stats, embedding=embedding, digest=str(i), time=i * 1000.)
        rows.append({"id": str(i), "path": str(i), "data": data})
    result = finalize(rows, snapshot)
    kept = sum(row["data"]["decision"] == "keep" for row in result)
    assert kept == (90 if source == "profil" else 16)
    reviewed = sum(row["data"]["decision"] == "review" for row in result)
    assert reviewed == (10 if source == "profil" else 35)


def test_default_selectivity_target_is_monotonic_and_centered_on_requested_range():
    keep = [rates(None, value / 100)[0] for value in range(101)]
    assert all(a >= b for a, b in zip(keep[:-1], keep[1:], strict=True))
    assert keep[50] == pytest.approx(.16)
    assert keep[0] == pytest.approx(.32)
    assert keep[-1] == pytest.approx(.08)
    assert all(rates(None, value / 100)[1] == pytest.approx(.35) for value in range(101))


@pytest.mark.parametrize("uncertain_count", [10, 30])
def test_technical_doubts_share_review_budget_and_never_become_automatic_keeps(store, uncertain_count):
    batch = cached_batch(store)
    rows = store.photos(batch)
    # Local sharpness is questionable, without the whole-frame blur rejection.
    for row in rows[:uncertain_count]:
        row["data"]["features"]["sharpness"] = .0001
    result = reselect(rows, store.batch(batch)["snapshot"], .5)
    assert all(row["data"]["decision"] != "keep" for row in result[:uncertain_count])
    assert sum(row["data"]["decision"] == "keep" for row in result) == (5 if uncertain_count == 10 else 0)
    assert sum(row["data"]["decision"] == "review" for row in result) == 10
    assert any("Netteté incertaine" in reason for row in result for reason in row["data"]["reasons"])


def test_review_cap_does_not_overwrite_manual_choices(store):
    batch = cached_batch(store)
    rows = store.photos(batch)
    for row in rows[:15]:
        row["data"].update(decision="review", manual_decision=True)
    result = reselect(rows, store.batch(batch)["snapshot"], .5)
    assert all(row["data"]["decision"] == "review" for row in result[:15])
    assert sum(row["data"]["decision"] == "review" for row in result) >= 15
