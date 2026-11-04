"""
Prepare one card ahead: one in-memory slot per user, in this process only.

A slot holds the running task or its finished `ReviewReady` (a fresh card only: a stored one costs
nothing to derive again), for `lifetime` seconds. A restart just loses it. Nothing here is counted
against quota: usage is counted when a card is delivered (StudyUseCases). A task that does not
produce a card keeps the slot empty for `failure_hold` seconds, so failures cannot be used to spam
the LLM; when it failed (an error, not just "nothing to study"), `/study/next` honors the same hold.
"""
import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from flashcard.app.review import ReviewReady
from flashcard.app.study import GenerationFailed
from flashcard.schemas.user import UserId
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)

LIFETIME_SECONDS = 600.0
FAILURE_HOLD_SECONDS = 30.0


@dataclass
class _Slot:
    created: float
    task: Optional[asyncio.Task] = None
    ready: Optional[ReviewReady] = None
    failed_until: Optional[float] = None
    # The hold follows an error (not an empty result): generating again is refused until it ends.
    failure: bool = False


class PreparedCards:
    def __init__(
        self,
        *,
        lifetime: float = LIFETIME_SECONDS,
        failure_hold: float = FAILURE_HOLD_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.lifetime = lifetime
        self.failure_hold = failure_hold
        self._clock = clock
        self._slots: dict[UserId, _Slot] = {}

    def would_start(self, user_id: UserId) -> bool:
        """Whether `start` would begin a task now (no live slot and no hold). Changes nothing."""
        self._forget_stale(self._clock())
        return user_id not in self._slots

    def held(self, user_id: UserId) -> bool:
        """A recent failure keeps generating for this user paused."""
        slot = self._slots.get(user_id)
        return (slot is not None and slot.failure and slot.failed_until is not None
                and self._clock() < slot.failed_until)

    def hold(self, user_id: UserId) -> None:
        """Record a failure of generating outside a prepare task (`/study/next`): same hold."""
        slot = self._slots.get(user_id)
        if slot is not None and slot.task is not None:
            return  # a task is running; it will end with its own result
        self._slots[user_id] = _Slot(
            created=self._clock(), failed_until=self._clock() + self.failure_hold, failure=True)

    def start(self, user_id: UserId, make: Callable[[], Awaitable[object]]) -> bool:
        """
        Start preparing a card unless the user has a live slot or a recent failure (then a no-op).
        `make` returns a ReviewReady, or anything else when no card could be made. True if started.
        """
        now = self._clock()
        self._forget_stale(now)
        if user_id in self._slots:
            return False
        slot = _Slot(created=now)
        self._slots[user_id] = slot
        slot.task = asyncio.create_task(self._run(slot, make), name=f"prepare-card-{user_id}")
        return True

    async def take(self, user_id: UserId) -> Optional[ReviewReady]:
        """
        The prepared card, waiting for its task if it is still running; None if there is none
        (or it failed). A card is taken once. The caller must still check it is valid.
        """
        slot = self._slots.get(user_id)
        if slot is None or slot.failed_until is not None:
            return None
        task = slot.task
        if task is not None:
            try:
                # Shielded: a caller that goes away must not cancel the generation.
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.cancelled():
                    raise  # this caller was cancelled
                return None
        ready = slot.ready
        if ready is None or self._clock() - slot.created >= self.lifetime:
            return None
        if self._slots.get(user_id) is slot:
            del self._slots[user_id]
        return ready

    async def close(self) -> None:
        """Cancel running tasks (shutdown)."""
        tasks = [slot.task for slot in self._slots.values() if slot.task is not None and not slot.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._slots.clear()

    async def _run(self, slot: _Slot, make: Callable[[], Awaitable[object]]) -> None:
        try:
            outcome = await make()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Preparing a card failed", exc_info=True)
            outcome = GenerationFailed()
        slot.task = None
        if isinstance(outcome, ReviewReady) and not outcome.from_storage:
            slot.ready = outcome
        else:
            slot.failed_until = self._clock() + self.failure_hold
            # One word the LLM cannot read is deferred already; it says nothing about the next card.
            slot.failure = isinstance(outcome, GenerationFailed) and not outcome.unclear

    def _forget_stale(self, now: float) -> None:
        for user_id, slot in list(self._slots.items()):
            if slot.task is not None:
                continue
            expired = now - slot.created >= self.lifetime
            failure_over = slot.failed_until is not None and now >= slot.failed_until
            if expired or failure_over:
                del self._slots[user_id]
