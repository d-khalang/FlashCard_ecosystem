"""
Unit tests for the index migration against the in-memory Mongo fake.
"""
import pytest
from pymongo.errors import DuplicateKeyError

from flashcard.migrations.ensure_indexes import ensure_indexes
from flashcard.services.expression import ExpressionService
from flashcard.services.user import UserService
from tests.helpers import TEST_LANGUAGE
from tests.integration.helpers import make_cols

USER_INDEXES = {("user_id",), ("is_active", "has_pending", "last_reviewed_at")}
CARD_INDEXES = {("user_id", "value"), ("user_id", "last_activity_at", "created_at"), ("user_id", "created_at")}


async def _run(cols, *, apply=True):
    return await ensure_indexes(
        cols,
        UserService(users=cols["users"], defaults=TEST_LANGUAGE.user_defaults),
        ExpressionService(expressions=cols["expression"]),
        apply=apply,
    )


async def test_builds_every_index_on_a_new_database():
    cols = make_cols()

    report = await _run(cols)

    assert report.indexes_built
    assert cols["users"].indexes == USER_INDEXES
    assert cols["expression"].indexes == CARD_INDEXES


async def test_dry_run_builds_nothing():
    cols = make_cols()

    report = await _run(cols, apply=False)

    assert not report.indexes_built
    assert not cols["users"].indexes and not cols["expression"].indexes


async def test_second_run_changes_nothing():
    cols = make_cols()

    await _run(cols)
    report = await _run(cols)

    assert report.indexes_built and cols["users"].indexes == USER_INDEXES


async def test_user_id_becomes_unique():
    cols = make_cols()
    await _run(cols)
    await cols["users"].insert_one({"user_id": "7"})

    with pytest.raises(DuplicateKeyError):
        await cols["users"].insert_one({"user_id": "7"})


async def test_duplicate_user_ids_stop_the_run_before_any_index():
    cols = make_cols(users=[{"user_id": "7"}, {"user_id": "7"}, {"user_id": "8"}])

    report = await _run(cols)

    assert report.duplicate_user_ids == 1 and not report.indexes_built
    assert not cols["users"].indexes and not cols["expression"].indexes


async def test_card_duplicates_fail_loudly():
    cols = make_cols(expressions=[{"user_id": "7", "value": "Ciao"}, {"user_id": "7", "value": "ciao"}])

    with pytest.raises(DuplicateKeyError):
        await _run(cols)
