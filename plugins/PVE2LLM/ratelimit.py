"""A tiny in-process sliding-window rate limiter for the Winky chat endpoint.

Single-process, thread-safe and dependency-free. A limit of ``<= 0`` disables
the limiter. This is a cost/abuse guard for the configured LLM provider, not a
distributed rate limiter.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, max_per_minute: int, window_seconds: float = 60.0) -> None:
        self.max_per_minute = int(max_per_minute)
        self.window_seconds = float(window_seconds)
        self._lock = threading.Lock()
        self._events: deque[float] = deque()

    def allow(self, now: float | None = None) -> bool:
        """Record one hit and return True, or False when the window is full."""
        if self.max_per_minute <= 0:
            return True
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_seconds
        with self._lock:
            while self._events and self._events[0] <= cutoff:
                self._events.popleft()
            if len(self._events) >= self.max_per_minute:
                return False
            self._events.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
