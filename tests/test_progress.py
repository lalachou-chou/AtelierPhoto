import queue
import threading
from types import SimpleNamespace

import pytest

from atelier.app import Window
from atelier.progress import ProgressEstimator, remaining_time_text


def test_estimate_requires_observations_and_uses_only_work_since_resume(monkeypatch):
    clock = iter([1000., 1002., 1004., 1006.])
    monkeypatch.setattr("atelier.progress.monotonic", lambda: next(clock))
    estimator = ProgressEstimator()
    assert estimator.update(900, 1000) is None
    assert estimator.update(901, 1000) is None
    assert estimator.update(902, 1000) is None
    assert estimator.update(903, 1000) == pytest.approx(194.)


def test_estimate_adapts_to_recent_speed_and_handles_fast_files(monkeypatch):
    now = [0.]
    monkeypatch.setattr("atelier.progress.monotonic", lambda: now[0])
    estimator = ProgressEstimator()
    estimator.update(0, 1000)
    for index in range(1, 5):
        now[0] += 10
        estimate = estimator.update(index, 1000)
    assert estimate == pytest.approx(9960.)
    for index in range(5, 105):
        now[0] += .1
        estimate = estimator.update(index, 1000)
    assert estimate == pytest.approx(89.6)
    assert estimator.update(1000, 1000) is None
    assert estimator.update(0, 1000) is None  # A new run cannot inherit the old rate.


@pytest.mark.parametrize("seconds,expected", [
    (None, ""), (float("nan"), ""), (float("inf"), ""), (0, ""),
    (15, "Moins d’une minute restante"), (60, "Environ 1 min restante"),
    (61, "Environ 2 min restantes"), (180, "Environ 3 min restantes"),
])
def test_remaining_minutes_are_rounded_up(seconds, expected):
    assert remaining_time_text(seconds) == expected


def test_progress_ui_hides_estimate_during_final_calculation_and_pause(qapp, store):
    window = Window(store.root)
    window.process = SimpleNamespace(is_alive=lambda: True)
    window.events = queue.SimpleQueue()
    window.cancel_event = threading.Event()
    try:
        window.events.put({"type": "progress", "current": 3, "total": 100, "label": "photo.jpg", "remaining_seconds": 180})
        window.poll()
        assert "Environ 3 min restantes" in window.progress_label.text()
        window.events.put({"type": "phase", "label": "Calcul du profil et de la retouche…"})
        window.poll()
        assert "Durée restante non estimable" in window.progress_label.text()
        assert "3 min" not in window.progress_label.text()
        window.cancel_event.set()
        window.progress_label.setText("Suspension après la photo en cours…")
        window.events.put({"type": "progress", "current": 4, "total": 100, "label": "photo.jpg", "remaining_seconds": 120})
        window.poll()
        assert window.progress_label.text() == "Suspension après la photo en cours…"
    finally:
        window.process = None
        window.close()
