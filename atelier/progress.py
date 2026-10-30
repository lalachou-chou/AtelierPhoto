"""Estimate remaining photo-processing time from recent worker progress."""
import math
from collections import deque
from time import monotonic


class ProgressEstimator:
    def __init__(self):
        self.samples = deque(maxlen=31)
        self.total = None
        self.started = None

    def update(self, current, total):
        now = monotonic()
        if self.total != total or (self.samples and current < self.samples[-1][1]):
            self.samples.clear()
            self.started = now
        self.total = total
        if not self.samples or current > self.samples[-1][1]:
            self.samples.append((now, current))
        started, initial = self.samples[0]
        completed, elapsed = current - initial, now - started
        # Ignore model loading, previous runs and pauses: the first progress
        # event starts a fresh observation window in the worker itself.
        if completed < 3 or now - self.started < 5 or elapsed <= 0 or current >= total:
            return None
        return elapsed / completed * (total - current)


def remaining_time_text(seconds):
    if seconds is None or not math.isfinite(seconds) or seconds <= 0:
        return ""
    if seconds < 60:
        return "Moins d’une minute restante"
    minutes = math.ceil(seconds / 60)
    return f"Environ {minutes} min restante{'s' if minutes > 1 else ''}"
