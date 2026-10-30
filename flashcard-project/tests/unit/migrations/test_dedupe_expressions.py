"""
Unit tests for the expression dedupe migration against the in-memory Mongo fake.
"""
from datetime import datetime, timezone

import pytest
from pymongo.errors import DuplicateKeyError

from flashcard.migrations.dedupe_expressions import DedupeReport, dedupe_expressions
from flashcard.services.expression import ExpressionService
from flashcard.services.review_state import ReviewStateStore
from tests.integration.helpers import make_cols


def _card(_id, value, *, user_id="42", reps=0, reverse_reps=None, created="2026-01-01T00:00:00Z", pending=None):
    card = {"_id": _id, "user_id": user_id, "value": value, "reps": reps, "created_at": created,
            "pending_message_id": pending}
    if reverse_reps is not None:
        card["reverse_stats"] = {"reps": reverse_reps}
    return card


async def _run(cols, *, apply=True):
    return await dedupe_expressions(cols, ExpressionService(expressions=cols["expression"]),
                                    ReviewStateStore(users=cols["users"]), apply=apply)


def _ids(cols):
    return sorted(card["_id"] for card in cols["expression"].docs)


class TestWhichCardStays:

    async def test_values_differing_only_in_case_are_duplicates(self):
        cols = make_cols(expressions=[_card("a", "Ciao"), _card("b", "ciao", reps=3)])

        report = await _run(cols)

        assert _ids(cols) == ["b"]
        assert report.duplicate_groups == 1 and report.removed == 1

    async def test_reverse_reviews_count(self):
        cols = make_cols(expressions=[_card("a", "ciao", reps=2), _card("b", "Ciao", reps=1, reverse_reps=2)])

        await _run(cols)

        assert _ids(cols) == ["b"]

    async def test_tie_keeps_the_oldest(self):
        cols = make_cols(expressions=[_card("new", "ciao", created="2026-02-01T00:00:00Z"),
                                      _card("old", "Ciao", created="2026-01-01T00:00:00Z")])

        await _run(cols)

        assert _ids(cols) == ["old"]

    async def test_accents_and_slashes_stay_distinct(self):
        cols = make_cols(expressions=[_card("a", "perché"), _card("b", "perche"), _card("c", "tavolo/a")])

        report = await _run(cols)

        assert _ids(cols) == ["a", "b", "c"]
        assert report.duplicate_groups == 0

    async def test_grouping_follows_the_index_collation_not_python_casefold(self):
        # Checked on MongoDB 7: "ß" != "ss" at strength 2, while NFC and NFD "é" are equal.
        cols = make_cols(expressions=[_card("a", "Straße"), _card("b", "strasse"),
                                      _card("c", "perché"), _card("d", "PERCHÉ", reps=1)])

        report = await _run(cols)

        assert _ids(cols) == ["a", "b", "d"]
        assert report.duplicate_groups == 1

    async def test_tie_compares_text_forms_as_times(self):
        """Offsets and fractions are compared as instants, not as text."""
        cols = make_cols(expressions=[
            _card("new", "ciao", created="2026-01-01T00:30:00.5Z"),
            _card("old", "Ciao", created="2026-01-01T01:00:00+01:00"),  # 00:00 UTC
            _card("bad", "CIAO", created=datetime(2026, 1, 2, tzinfo=timezone.utc))])

        await _run(cols)

        assert _ids(cols) == ["old"]

    async def test_mixed_created_at_types_do_not_crash_the_tie_break(self):
        cols = make_cols(expressions=[_card("new", "ciao", created="2026-02-01T00:00:00Z"),
                                      _card("old", "Ciao", created=datetime(2026, 1, 1, tzinfo=timezone.utc)),
                                      _card("none", "CIAO", created=None)])

        await _run(cols)

        assert _ids(cols) == ["none"]  # a missing date sorts as oldest

    async def test_other_users_values_are_not_duplicates(self):
        cols = make_cols(expressions=[_card("a", "ciao", user_id="1"), _card("b", "ciao", user_id="2")])

        await _run(cols)

        assert _ids(cols) == ["a", "b"]


class TestReviewState:

    async def test_removed_pending_card_clears_the_legacy_pause(self):
        cols = make_cols(users=[{"user_id": "42", "has_pending": True}],
                         expressions=[_card("a", "ciao", reps=5), _card("b", "Ciao", pending=777)])

        report = await _run(cols)

        assert cols["users"].docs[0]["has_pending"] is False
        assert report.pending_cleared == 1

    async def test_pause_kept_when_the_kept_card_is_the_pending_one(self):
        cols = make_cols(users=[{"user_id": "42", "has_pending": True}],
                         expressions=[_card("a", "ciao", reps=5, pending=777), _card("b", "Ciao")])

        report = await _run(cols)

        assert cols["users"].docs[0]["has_pending"] is True
        assert report.pending_cleared == 0

    async def test_pause_kept_when_another_remaining_card_is_pending(self):
        # The removed copy holds an older, never-graded message; the kept one is the live pending card.
        cols = make_cols(users=[{"user_id": "42", "has_pending": True}],
                         expressions=[_card("a", "ciao", reps=5, pending=900), _card("b", "Ciao", pending=100)])

        report = await _run(cols)

        assert cols["users"].docs[0]["has_pending"] is True
        assert report.pending_cleared == 0

    async def test_pause_counted_once_per_user_and_only_when_paused(self):
        cols = make_cols(users=[{"user_id": "42", "has_pending": True}, {"user_id": "7", "has_pending": False}],
                         expressions=[_card("a", "ciao", reps=5), _card("b", "Ciao", pending=1),
                                      _card("c", "andare", reps=5), _card("d", "Andare", pending=2),
                                      _card("e", "casa", user_id="7", reps=5), _card("f", "Casa", user_id="7", pending=3)])

        report = await _run(cols)

        assert report.pending_cleared == 1
        assert [doc["has_pending"] for doc in cols["users"].docs] == [False, False]

    async def test_current_review_on_a_removed_card_is_cleared(self):
        review = {"expression_id": "b", "direction": "forward", "message_id": 777, "sent_at": "2026-01-02T00:00:00Z"}
        cols = make_cols(users=[{"user_id": "42", "current_review": review}],
                         expressions=[_card("a", "ciao", reps=5), _card("b", "Ciao")])

        report = await _run(cols)

        assert "current_review" not in cols["users"].docs[0]
        assert report.current_review_cleared == 1

    async def test_current_review_on_the_kept_card_stays(self):
        review = {"expression_id": "a", "direction": "forward", "message_id": 777, "sent_at": "2026-01-02T00:00:00Z"}
        cols = make_cols(users=[{"user_id": "42", "current_review": review}],
                         expressions=[_card("a", "ciao", reps=5), _card("b", "Ciao")])

        await _run(cols)

        assert cols["users"].docs[0]["current_review"] == review


class TestRun:

    async def test_dry_run_counts_without_writing(self):
        review = {"expression_id": "b", "direction": "forward", "message_id": 1, "sent_at": "2026-01-02T00:00:00Z"}
        cols = make_cols(users=[{"user_id": "42", "has_pending": True, "current_review": review}],
                         expressions=[_card("a", "ciao", reps=5), _card("b", "Ciao", pending=1)])

        report = await _run(cols, apply=False)

        assert _ids(cols) == ["a", "b"]
        assert cols["users"].docs[0]["has_pending"] is True
        assert cols["expression"].unique_indexes == []
        assert report == DedupeReport(expressions=2, duplicate_groups=1, removed=1, pending_cleared=1,
                                      current_review_cleared=1)

    async def test_apply_builds_the_index_and_a_second_run_finds_nothing(self):
        cols = make_cols(expressions=[_card("a", "ciao"), _card("b", "Ciao")])

        await _run(cols)
        second = await _run(cols)

        assert second.duplicate_groups == 0 and second.index_built
        with pytest.raises(DuplicateKeyError):
            await cols["expression"].insert_one(_card("c", "CIAO"))

    async def test_unexpected_ids_and_values_are_reported_not_grouped(self):
        cols = make_cols(expressions=[_card("a", "ciao", user_id=42), _card("c", "ciao", user_id="abc"),
                                      {"_id": "b", "user_id": "42", "value": None}])

        report = await _run(cols, apply=False)

        assert (report.invalid_user_id, report.non_string_value, report.duplicate_groups) == (2, 1, 0)
