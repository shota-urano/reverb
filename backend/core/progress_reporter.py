from __future__ import annotations

import threading
import time
from typing import Callable, Optional

_PROGRESS_EPSILON = 0.000001


class _EstimatedProgressReporter:
    def __init__(
        self,
        *,
        progress_cb: Callable[[float], None],
        estimated_total_seconds: float,
        base_progress: float,
        ceiling_progress: float,
        interval_seconds: float,
        thread_name: str,
    ) -> None:
        self.progress_cb = progress_cb
        self.estimated_total_seconds = estimated_total_seconds
        self.base_progress = _clamp_progress(base_progress)
        self.ceiling_progress = _clamp_progress(ceiling_progress)
        self.interval_seconds = interval_seconds
        self.thread_name = thread_name
        self._stop = threading.Event()
        self._last_progress = self.base_progress
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if (
            self.estimated_total_seconds <= 0
            or self.interval_seconds <= 0
            or self.ceiling_progress <= self.base_progress
        ):
            return
        self._thread = threading.Thread(
            target=self._run,
            name=self.thread_name,
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        started_at = time.monotonic()
        progress_span = self.ceiling_progress - self.base_progress
        while not self._stop.wait(self.interval_seconds):
            elapsed = time.monotonic() - started_at
            estimated_fraction = elapsed / self.estimated_total_seconds
            self._report(self.base_progress + (progress_span * estimated_fraction))

    def _report(self, progress: float) -> None:
        ceiling_limit = max(
            self.base_progress,
            min(1.0, self.ceiling_progress) - _PROGRESS_EPSILON,
        )
        clamped = max(self.base_progress, min(progress, ceiling_limit))
        if clamped <= self._last_progress:
            return
        self._last_progress = clamped
        self.progress_cb(clamped)


def _clamp_progress(progress: float) -> float:
    return max(0.0, min(progress, 1.0))
