"""
Unit tests for the ISO-text-to-date migration against the in-memory Mongo fake.
"""
from datetime import datetime, timezone

from flashcard.migrations.convert_dates import convert_dates
from tests.integration.helpers import make_cols

UTC = timezone.utc
SEP_1 = datetime(2026, 9, 1, 10, tzinfo=UTC)


def _cols(users=(), expressions=()):
    return make_cols(users=list(users), expressions=list(expressions))


class TestConvert:

    async def test_text_dates_become_utc_dates_nested_included(self):
        cols = _cols(
            users=[{"_id": "u", "user_id": "42", "created_at": "2026-09-01T10:00:00Z",
                    "current_review": {"expression_id": "e", "sent_at": "2026-09-01T10:00:00Z"}}],
            expressions=[{"_id": "e", "user_id": "42", "created_at": "2026-09-01T10:00:00Z",
                          "reverse_stats": {"last_review_at": "2026-09-01T10:00:00Z"},
                          "last_card": {"generated_at": "2026-09-01T10:00:00Z"}}],
        )

        report = await convert_dates(cols, apply=True)

        user, card = cols["users"].docs[0], cols["expression"].docs[0]
        assert user["created_at"] == user["current_review"]["sent_at"] == SEP_1
        assert card["created_at"] == card["reverse_stats"]["last_review_at"] == card["last_card"]["generated_at"] == SEP_1
        assert report.converted == {"users.created_at": 1, "users.current_review.sent_at": 1,
                                    "expression.created_at": 1, "expression.reverse_stats.last_review_at": 1,
                                    "expression.last_card.generated_at": 1}
        assert dict(report.documents_with_text) == {"users": 1, "expression": 1}

    async def test_text_without_timezone_is_utc(self):
        cols = _cols(users=[{"_id": "u", "last_seen_at": "2026-09-01T10:00:00"}])

        await convert_dates(cols, apply=True)

        assert cols["users"].docs[0]["last_seen_at"] == SEP_1

    async def test_empty_text_becomes_null(self):
        cols = _cols(users=[{"_id": "u", "last_reviewed_at": ""}])

        report = await convert_dates(cols, apply=True)

        assert cols["users"].docs[0]["last_reviewed_at"] is None
        assert report.emptied == {"users.last_reviewed_at": 1}

    async def test_unreadable_text_is_reported_and_left(self):
        cols = _cols(users=[{"_id": "u", "created_at": "not a date", "last_seen_at": "2026-09-01T10:00:00Z"}])

        report = await convert_dates(cols, apply=True)

        user = cols["users"].docs[0]
        assert user["created_at"] == "not a date"
        assert user["last_seen_at"] == SEP_1  # the readable field of the same document is converted
        assert report.unreadable == {"users.created_at": 1}
        assert report.unreadable_ids == ["users:u created_at='not a date'"]

    async def test_dates_and_missing_fields_are_untouched(self):
        cols = _cols(users=[{"_id": "u", "created_at": SEP_1, "last_seen_at": None}])

        report = await convert_dates(cols, apply=True)

        assert cols["users"].docs[0] == {"_id": "u", "created_at": SEP_1, "last_seen_at": None}
        assert sum(report.documents_with_text.values()) == 0

    async def test_dry_run_writes_nothing(self):
        cols = _cols(users=[{"_id": "u", "created_at": "2026-09-01T10:00:00Z"}])

        report = await convert_dates(cols, apply=False)

        assert cols["users"].docs[0]["created_at"] == "2026-09-01T10:00:00Z"
        assert report.converted == {"users.created_at": 1}

    async def test_second_run_finds_nothing(self):
        cols = _cols(users=[{"_id": "u", "created_at": "2026-09-01T10:00:00Z"}],
                     expressions=[{"_id": "e", "last_activity_at": "2026-09-01T10:00:00Z"}])
        await convert_dates(cols, apply=True)

        report = await convert_dates(cols, apply=True)

        assert sum(report.documents_with_text.values()) == 0 and not report.converted

    async def test_a_field_the_bot_changed_meanwhile_is_kept_and_the_rest_converted(self):
        """A user interacts during the run: record_seen rewrites last_seen_at as a date."""
        cols = _cols(users=[{"_id": "u", "created_at": "", "last_reviewed_at": "2026-09-01T10:00:00Z",
                             "last_seen_at": "2026-09-01T10:00:00Z"}])
        live = datetime(2026, 10, 30, tzinfo=UTC)
        update_one = cols["users"].update_one

        async def bot_writes_first(query, update, **kwargs):
            if "last_seen_at" in query:
                await update_one({"_id": "u"}, {"$set": {"last_seen_at": live}})
            return await update_one(query, update, **kwargs)

        cols["users"].update_one = bot_writes_first
        report = await convert_dates(cols, apply=True)

        user = cols["users"].docs[0]
        assert user["last_seen_at"] == live
        # Still converted, so backfill_created_at (created_at: null) finds this user next.
        assert user["created_at"] is None
        assert user["last_reviewed_at"] == SEP_1
        assert report.changed_meanwhile == 1
