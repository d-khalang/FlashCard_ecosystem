"""
The prepare-ahead slot: one task or ready card per user, ten-minute life, 30 s failure hold.
"""
import asyncio

import pytest

from flashcard.app.quota import Allowed
from flashcard.app.review import NoCandidate, ReviewReady
from flashcard.miniapp.prefetch import PreparedCards
from flashcard.schemas.expression import CardSettings
from tests.integration.study_helpers import make_card

SETTINGS = CardSettings(level="A2", primary_language="en", secondary_language=None)


def _ready(expression_id="e1") -> ReviewReady:
    return ReviewReady(expression_id=expression_id, value="andare", direction="forward", card=make_card(),
                       settings=SETTINGS, quota=Allowed(uses_own_key=False))


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Maker:
    """A prepare task that finishes when released."""

    def __init__(self, result=None, error=None):
        self.calls = 0
        self.result = result if result is not None else _ready()
        self.error = error
        self.release = asyncio.Event()

    async def __call__(self):
        self.calls += 1
        await self.release.wait()
        if self.error:
            raise self.error
        return self.result


async def test_take_waits_for_the_running_task_and_returns_its_card():
    prepared, maker = PreparedCards(), Maker()
    prepared.start(1, maker)
    taking = asyncio.create_task(prepared.take(1))
    await asyncio.sleep(0)
    assert not taking.done()

    maker.release.set()

    assert (await taking).expression_id == "e1"


async def test_a_card_is_taken_once():
    prepared, maker = PreparedCards(), Maker()
    maker.release.set()
    prepared.start(1, maker)

    assert await prepared.take(1) is not None
    assert await prepared.take(1) is None


async def test_repeated_starts_are_no_ops_while_a_task_or_card_exists():
    prepared, maker = PreparedCards(), Maker()

    assert prepared.start(1, maker) is True
    assert prepared.start(1, maker) is False
    maker.release.set()
    await asyncio.sleep(0.01)
    assert prepared.start(1, maker) is False
    assert maker.calls == 1


async def test_nothing_to_take_without_a_start():
    assert await PreparedCards().take(1) is None


async def test_each_user_has_a_slot():
    prepared, maker = PreparedCards(), Maker()
    maker.release.set()

    assert prepared.start(1, maker) and prepared.start(2, maker)
    await asyncio.sleep(0.01)
    assert maker.calls == 2


async def test_a_card_expires_after_ten_minutes():
    clock = Clock()
    prepared, maker = PreparedCards(clock=clock), Maker()
    maker.release.set()
    prepared.start(1, maker)
    await asyncio.sleep(0.01)

    clock.now = 601

    assert await prepared.take(1) is None
    assert prepared.start(1, maker) is True


async def _no_candidate():
    return NoCandidate()


async def _llm_down():
    raise RuntimeError("llm down")


@pytest.mark.parametrize("make", [_no_candidate, _llm_down])
async def test_a_task_that_makes_no_card_holds_the_slot_empty_for_30_seconds(make):
    clock = Clock()
    prepared = PreparedCards(clock=clock)
    prepared.start(1, make)
    await asyncio.sleep(0.01)

    assert await prepared.take(1) is None
    clock.now = 29
    assert prepared.start(1, make) is False
    clock.now = 31
    assert prepared.start(1, make) is True


async def test_a_cancelled_taker_does_not_cancel_the_preparation():
    prepared, maker = PreparedCards(), Maker()
    prepared.start(1, maker)
    taking = asyncio.create_task(prepared.take(1))
    await asyncio.sleep(0)

    taking.cancel()
    with pytest.raises(asyncio.CancelledError):
        await taking
    maker.release.set()

    assert (await prepared.take(1)).expression_id == "e1"


async def test_close_cancels_running_tasks():
    prepared, maker = PreparedCards(), Maker()
    prepared.start(1, maker)
    await asyncio.sleep(0)

    await prepared.close()

    assert await prepared.take(1) is None


async def _stored_card():
    return _ready_stored()


def _ready_stored() -> ReviewReady:
    return ReviewReady(expression_id="e1", value="andare", direction="forward", card=make_card(),
                       settings=SETTINGS, quota=None)


async def test_a_stored_card_is_not_kept_in_the_slot():
    clock = Clock()
    prepared = PreparedCards(clock=clock)
    prepared.start(1, _stored_card)
    await asyncio.sleep(0.01)

    assert await prepared.take(1) is None
    assert prepared.held(1) is False  # nothing failed: it is not a reason to refuse generating


async def test_only_a_failure_holds_generating():
    clock = Clock()
    prepared = PreparedCards(clock=clock)
    prepared.start(1, _no_candidate)
    prepared.start(2, _llm_down)
    await asyncio.sleep(0.01)

    assert (prepared.held(1), prepared.held(2)) == (False, True)
    clock.now = 31
    assert prepared.held(2) is False


async def test_hold_marks_a_failure_found_elsewhere_and_start_respects_it():
    clock = Clock()
    prepared = PreparedCards(clock=clock)

    prepared.hold(1)

    assert prepared.held(1) is True and prepared.start(1, _no_candidate) is False
    clock.now = 30
    assert prepared.start(1, _no_candidate) is True


async def test_hold_does_not_disturb_a_running_task():
    prepared, maker = PreparedCards(), Maker()
    prepared.start(1, maker)

    prepared.hold(1)
    maker.release.set()

    assert (await prepared.take(1)).expression_id == "e1"
