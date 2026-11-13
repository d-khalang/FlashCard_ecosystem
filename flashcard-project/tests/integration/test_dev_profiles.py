"""
The dev runner's seed profiles and shifted clock, run against the real app (see harness.py):
each profile puts the dev user in the state its name promises.
"""
from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest

from flashcard.utils import time as clock

from .harness import USER

SPEC = importlib.util.spec_from_file_location(
    "miniapp_dev", Path(__file__).resolve().parents[2] / "dev" / "miniapp_dev.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

WORDS = ["ciao", "bene", "mare", "andare", "piacere"]


@pytest.fixture(autouse=True)
def restore_clock(monkeypatch):
    monkeypatch.setattr(clock, "_clock_offset", timedelta(0))


async def _seed(harness, profile: str) -> tuple[int, int]:
    """What `seed --profile` does, for the harness's user: (words removed, words added)."""
    return await runner.apply_profile(harness.cols, harness.app.state.core.user_service, USER, WORDS, profile,
                                      clock.now_utc())


async def _counts(harness):
    return await harness.app.state.core.expression_service.count_words(USER)


async def test_ready_has_every_word_due(harness):
    await _seed(harness, "ready")

    counts = await _counts(harness)

    assert (counts.total, counts.ready) == (5, 5)


async def test_reviewed_has_resting_words_that_come_due_a_day_later(harness):
    await _seed(harness, "reviewed")
    assert ((await _counts(harness)).total, (await _counts(harness)).ready) == (5, 3)

    clock.shift_clock(timedelta(days=1))

    assert (await _counts(harness)).ready == 5


async def test_limit_refuses_a_new_card(harness):
    await _seed(harness, "limit")

    response = await harness.post("/study/next")

    assert response.status_code == 200 and response.json()["status"] == "quota"


async def test_limit_is_lifted_the_next_day(harness):
    await _seed(harness, "limit")
    clock.shift_clock(timedelta(days=1))

    response = await harness.post("/study/next")

    assert response.json()["status"] == "ready"


async def test_empty_has_nothing_to_study(harness):
    await _seed(harness, "empty")

    response = await harness.post("/study/next")

    assert response.json() == {"status": "none"}


async def test_sign_in_uses_the_real_time_when_the_clock_runs_ahead(harness):
    await _seed(harness, "ready")
    clock.shift_clock(timedelta(days=3))

    assert (await harness.get("/me")).status_code == 200


async def test_switching_profiles_replaces_the_previous_state(harness):
    await _seed(harness, "limit")

    assert await _seed(harness, "empty") == (5, 0)
    assert (await _counts(harness)).total == 0
    assert await _seed(harness, "ready") == (0, 5)
    assert (await harness.post("/study/next")).json()["status"] == "ready"  # the used-up credits are gone
    assert await harness.cols["users"].count_documents({"user_id": str(USER)}) == 1
