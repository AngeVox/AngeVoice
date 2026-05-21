"""Thread-safe latency tracker using a ring buffer for request durations."""

from __future__ import annotations

import threading
import time


class LatencyTracker:
    """Track recent request durations and compute percentiles.

    Uses a fixed-size ring buffer (default 10 000 entries) so memory usage
    stays constant regardless of request volume.  All public methods are
    thread-safe.
    """

    def __init__(self, max_samples: int = 10_000) -> None:
        self._max = max_samples
        self._buf: list[float] = []
        self._pos = 0
        self._count = 0
        self._lock = threading.Lock()

    # -- 录制 --------------------------------------------------------

    def record(self, duration_seconds: float) -> None:
        """Record a completed request duration (in seconds)."""
        with self._lock:
            if len(self._buf) < self._max:
                self._buf.append(duration_seconds)
            else:
                self._buf[self._pos] = duration_seconds
            self._pos = (self._pos + 1) % self._max
            self._count += 1

    def start(self) -> float:
        """Convenience: return a perf_counter start value."""
        return time.perf_counter()

    def record_start(self) -> _TimerContext:
        """Context-manager style tracking.

        Usage::

            with tracker.measure() as t:
                ...
            # elapsed is auto-recorded when exiting the block.
        """
        return _TimerContext(self)

    # -- 查询 ----------------------------------------------------------

    def count(self) -> int:
        with self._lock:
            return self._count

    def percentiles(self) -> dict[str, float | None]:
        """Return p50 / p95 / p99 latency values (seconds).

        Returns ``None`` for a percentile when fewer than 2 samples exist.
        """
        with self._lock:
            data = sorted(self._buf)
        n = len(data)
        if n < 2:
            return {"p50": None, "p95": None, "p99": None}

        def _pct(p: float) -> float:
            idx = int(p * (n - 1))
            return round(data[idx], 4)

        return {"p50": _pct(0.50), "p95": _pct(0.95), "p99": _pct(0.99)}

    def summary(self) -> dict:
        """Return a combined dict: percentiles + sample count."""
        info = self.percentiles()
        info["samples"] = self.count()
        return info


class _TimerContext:
    """Helper returned by ``LatencyTracker.record_start()``."""

    __slots__ = ("_tracker", "_start", "elapsed")

    def __init__(self, tracker: LatencyTracker) -> None:
        self._tracker = tracker
        self._start = time.perf_counter()
        self.elapsed: float = 0.0

    def __enter__(self) -> _TimerContext:
        return self

    def __exit__(self, *exc_info) -> None:
        self.elapsed = time.perf_counter() - self._start
        self._tracker.record(self.elapsed)
