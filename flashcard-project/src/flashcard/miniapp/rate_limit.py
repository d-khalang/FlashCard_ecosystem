"""In-memory sliding-window rate limit per key (here: per user and kind of route). A restart resets it."""
import math
import time
from collections import deque
from typing import Callable, Hashable


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[Hashable, deque] = {}

    def hit(self, key: Hashable) -> int:
        """
        Count one request. Returns 0 when it is allowed, otherwise the whole seconds to wait
        until the oldest counted request leaves the window (refused requests are not counted).
        """
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(1, math.ceil(self.window - (now - hits[0])))
        hits.append(now)
        if len(self._hits) > 10_000:
            self._forget_idle(now)
        return 0

    def _forget_idle(self, now: float) -> None:
        for key in [k for k, hits in self._hits.items() if not hits or now - hits[-1] >= self.window]:
            del self._hits[key]
