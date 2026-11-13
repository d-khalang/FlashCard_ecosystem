"""In-memory sliding-window rate limit per key (here: per user and kind of route). A restart resets it."""
import math
import time
from collections import deque
from datetime import datetime, time as day_time, timedelta, timezone
from typing import Callable, Hashable

from flashcard.utils.time import now_utc


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


class DailyBudget:
    """
    A per-user allowance of LLM attempts per UTC day, in memory (a restart resets it).

    Quota counts only delivered results, so results nobody is charged for (an unclear word, an
    import that saves nothing, a refresh that is then undone) could otherwise repeat for free.
    Memory is bounded: only today's users are kept, everything is dropped when the day changes.
    """

    def __init__(self, limit: int, clock: Callable[[], datetime] = now_utc):
        self.limit = limit
        self._clock = clock
        self._day = None
        self._used: dict[Hashable, int] = {}

    def charge(self, key: Hashable) -> int:
        """Count one attempt. Returns 0 when allowed, otherwise the seconds until the next UTC day."""
        now = self._clock()
        if now.date() != self._day:
            self._day, self._used = now.date(), {}
        if self._used.get(key, 0) >= self.limit:
            tomorrow = datetime.combine(now.date() + timedelta(days=1), day_time.min, tzinfo=timezone.utc)
            return max(1, math.ceil((tomorrow - now).total_seconds()))
        self._used[key] = self._used.get(key, 0) + 1
        return 0
