"""
Unit tests for the created_at backfill against the in-memory Mongo fake.
"""
from datetime import timedelta

from flashcard.migrations.backfill_created_at import BackfillReport, backfill_created_at
from flashcard.services.user import UserService
from flashcard.utils.time import iso_z, now_utc
from tests.integration.helpers import make_cols
from tests.helpers import TEST_LANGUAGE


def _ago(days):
    return iso_z(now_utc() - timedelta(days=days))


def _cols(users, expressions=()):
    return make_cols(users=list(users), expressions=list(expressions))


def _word(created_at, user_id="42"):
    return {"user_id": user_id, "value": created_at, "created_at": created_at}


async def _run(cols, *, apply=True):
    return await backfill_created_at(cols, UserService(users=cols["users"], defaults=TEST_LANGUAGE.user_defaults), apply=apply)


def _created(cols, user_id="42"):
    return next(doc for doc in cols["users"].docs if doc["user_id"] == user_id).get("created_at")


class TestBackfillCreatedAt:

    async def test_oldest_expression_becomes_the_trial_start(self):
        oldest = _ago(30)
        cols = _cols([{"user_id": "42"}], [_word(_ago(3)), _word(oldest), _word(_ago(10))])

        report = await _run(cols)

        assert _created(cols) == oldest
        assert report == BackfillReport(missing=1, from_oldest_expression=1, trial_ends_now=1)

    async def test_recent_oldest_expression_keeps_the_trial(self):
        cols = _cols([{"user_id": "42"}], [_word(_ago(3))])

        report = await _run(cols)

        assert report.trial_ends_now == 0

    async def test_user_without_expressions_starts_now(self):
        cols = _cols([{"user_id": "42"}])

        report = await _run(cols)

        assert _created(cols) is not None
        assert report == BackfillReport(missing=1, from_run_time=1)

    async def test_explicit_null_is_treated_as_missing(self):
        cols = _cols([{"user_id": "42", "created_at": None}], [_word(_ago(5))])

        await _run(cols)

        assert _created(cols) is not None

    async def test_existing_created_at_is_never_changed(self):
        existing = _ago(1)
        cols = _cols([{"user_id": "42", "created_at": existing}], [_word(_ago(30))])

        report = await _run(cols)

        assert _created(cols) == existing
        assert report.missing == 0

    async def test_other_users_expressions_are_not_used(self):
        cols = _cols([{"user_id": "42"}], [_word(_ago(30), user_id="7")])

        report = await _run(cols)

        assert report.from_run_time == 1

    async def test_non_string_user_id_is_reported_and_skipped(self):
        cols = _cols([{"user_id": 42}], [_word(_ago(30))])

        report = await _run(cols)

        assert _created(cols, 42) is None
        assert report == BackfillReport(missing=1, non_string_user_id=1)

    async def test_dry_run_writes_nothing(self):
        cols = _cols([{"user_id": "42"}], [_word(_ago(30))])

        report = await _run(cols, apply=False)

        assert _created(cols) is None
        assert report.from_oldest_expression == 1

    async def test_second_run_changes_nothing(self):
        cols = _cols([{"user_id": "42"}], [_word(_ago(30))])
        await _run(cols)
        first = _created(cols)

        report = await _run(cols)

        assert _created(cols) == first
        assert report == BackfillReport()


class TestUnusualExpressionDates:

    async def test_unreadable_dates_are_skipped_and_counted(self):
        good = _ago(20)
        cols = _cols([{"user_id": "42"}], [_word("not a date"), _word(good)])

        report = await _run(cols)

        assert _created(cols) == good
        assert report.unreadable_expression_dates == 1

    async def test_only_unreadable_dates_falls_back_to_run_time(self):
        cols = _cols([{"user_id": "42"}], [_word("garbage")])

        report = await _run(cols)

        assert _created(cols) is not None
        assert report.from_run_time == 1

    async def test_naive_and_aware_dates_compare_as_utc(self):
        cols = _cols([{"user_id": "42"}], [_word("2026-09-01T10:00:00"), _word("2026-09-02T10:00:00Z")])

        await _run(cols)

        assert _created(cols) == "2026-09-01T10:00:00Z"

    async def test_bson_datetime_values_are_accepted(self):
        from datetime import datetime, timezone
        cols = _cols([{"user_id": "42"}], [{"user_id": "42", "value": "x",
                                            "created_at": datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)}])

        await _run(cols)

        assert _created(cols) == "2026-08-01T12:00:00Z"


class TestBackfillCreatedAtWrite:

    async def test_never_overwrites(self):
        cols = _cols([{"user_id": "42", "created_at": "2026-01-01T00:00:00Z"}])

        assert await UserService(users=cols["users"], defaults=TEST_LANGUAGE.user_defaults).backfill_created_at(42, "2025-01-01T00:00:00Z") is False
        assert _created(cols) == "2026-01-01T00:00:00Z"
