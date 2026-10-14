"""
Unit tests for the current_review backfill against the in-memory Mongo fake.
"""
from flashcard.migrations.backfill_current_review import BackfillReport, backfill_current_review
from flashcard.services.review_state import ReviewStateStore
from tests.integration.helpers import make_cols


def _cols(users, expressions=()):
    return make_cols(users=list(users), expressions=list(expressions))


async def _run(cols, *, apply=True):
    return await backfill_current_review(cols, ReviewStateStore(cols=cols), apply=apply)


def _user(cols, user_id="42"):
    return next(doc for doc in cols["users"].docs if doc["user_id"] == user_id)


def _card(_id, *, pending=555, sent="2026-10-01T10:00:00Z", user_id="42"):
    return {"_id": _id, "user_id": user_id, "value": _id, "pending_message_id": pending, "last_sent_at": sent}


class TestBackfill:

    async def test_pending_user_gets_the_pending_card(self):
        cols = _cols([{"user_id": "42", "has_pending": True}], [_card("e1")])

        report = await _run(cols)

        assert _user(cols)["current_review"] == {
            "expression_id": "e1", "direction": "unknown", "message_id": 555, "sent_at": "2026-10-01T10:00:00Z"}
        assert report == BackfillReport(pending_users=1, backfilled=1)

    async def test_latest_sent_card_wins(self):
        cols = _cols([{"user_id": "42", "has_pending": True}],
                     [_card("old", pending=1, sent="2026-10-01T10:00:00Z"),
                      _card("new", pending=2, sent="2026-10-02T10:00:00Z")])

        await _run(cols)

        assert _user(cols)["current_review"]["expression_id"] == "new"

    async def test_graded_cards_with_null_pending_are_ignored(self):
        cols = _cols([{"user_id": "42", "has_pending": True}], [_card("e1", pending=None)])

        report = await _run(cols)

        assert "current_review" not in _user(cols)
        assert report.no_pending_card == 1

    async def test_string_message_id_is_converted(self):
        cols = _cols([{"user_id": "42", "has_pending": True}], [_card("e1", pending="555")])

        await _run(cols)

        assert _user(cols)["current_review"]["message_id"] == 555

    async def test_invalid_message_id_is_skipped(self):
        cols = _cols([{"user_id": "42", "has_pending": True}], [_card("e1", pending="abc")])

        report = await _run(cols)

        assert "current_review" not in _user(cols)
        assert report.invalid_message_id == 1

    async def test_existing_current_review_is_never_overwritten(self):
        existing = {"expression_id": "live", "direction": "forward", "message_id": 9, "sent_at": "2026-10-03T00:00:00Z"}
        cols = _cols([{"user_id": "42", "has_pending": True, "current_review": existing}], [_card("e1")])

        report = await _run(cols)

        assert _user(cols)["current_review"] == existing
        assert report.already_set == 1

    async def test_users_without_pending_are_untouched(self):
        cols = _cols([{"user_id": "42", "has_pending": False}], [_card("e1")])

        report = await _run(cols)

        assert "current_review" not in _user(cols)
        assert report.pending_users == 0

    async def test_other_users_cards_are_not_used(self):
        cols = _cols([{"user_id": "42", "has_pending": True}], [_card("e1", user_id="7")])

        report = await _run(cols)

        assert report.no_pending_card == 1

    async def test_dry_run_writes_nothing(self):
        cols = _cols([{"user_id": "42", "has_pending": True}], [_card("e1")])

        report = await _run(cols, apply=False)

        assert "current_review" not in _user(cols)
        assert report.backfilled == 1

    async def test_second_run_changes_nothing(self):
        cols = _cols([{"user_id": "42", "has_pending": True}], [_card("e1")])
        await _run(cols)

        report = await _run(cols)

        assert report == BackfillReport(pending_users=1, already_set=1)

    async def test_explicit_null_current_review_is_backfilled(self):
        cols = _cols([{"user_id": "42", "has_pending": True, "current_review": None}], [_card("e1")])

        report = await _run(cols)

        assert _user(cols)["current_review"]["expression_id"] == "e1"
        assert report.backfilled == 1

    async def test_non_string_user_id_is_reported_and_skipped(self):
        cols = _cols([{"user_id": 42, "has_pending": True}], [_card("e1")])

        report = await _run(cols)

        assert "current_review" not in _user(cols, 42)
        assert report == BackfillReport(pending_users=1, non_string_user_id=1)

    async def test_ties_without_sent_time_are_broken_deterministically(self):
        older = {"_id": "a1", "user_id": "42", "value": "a", "pending_message_id": 1, "last_activity_at": "2026-10-01T00:00:00Z"}
        newer = {"_id": "a2", "user_id": "42", "value": "b", "pending_message_id": 2, "last_activity_at": "2026-10-02T00:00:00Z"}
        for order in ([older, newer], [newer, older]):
            cols = _cols([{"user_id": "42", "has_pending": True}], order)

            await _run(cols)

            assert _user(cols)["current_review"]["expression_id"] == "a2"
