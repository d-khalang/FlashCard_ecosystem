"""
Unit tests for ReviewStateStore against the in-memory Mongo fake.
"""
from flashcard.services.review_state import ReviewStateStore
from tests.integration.helpers import make_cols


def _store(*users):
    cols = make_cols(users=list(users))
    return ReviewStateStore(cols=cols), cols["users"]


def _current(users, user_id="42"):
    return next(doc for doc in users.docs if doc["user_id"] == user_id).get("current_review")


class TestRecordSent:

    async def test_sets_the_current_review(self):
        store, users = _store({"user_id": "42"})

        await store.record_sent(42, "e1", "forward", 555)

        current = _current(users)
        assert (current["expression_id"], current["direction"], current["message_id"]) == ("e1", "forward", 555)
        assert current["sent_at"]

    async def test_a_new_card_replaces_the_current_review(self):
        store, users = _store({"user_id": "42"})

        await store.record_sent(42, "e1", "forward", 555)
        await store.record_sent(42, "e2", "reverse", 556)

        assert _current(users)["expression_id"] == "e2"

    async def test_does_not_create_a_user(self):
        store, users = _store()

        await store.record_sent(42, "e1", "forward", 555)

        assert users.docs == []


class TestRecordGraded:

    async def test_grading_the_current_card_clears_it(self):
        store, users = _store({"user_id": "42"})
        await store.record_sent(42, "e1", "forward", 555)

        await store.record_graded(42, "e1", "forward")

        assert _current(users) is None

    async def test_late_grade_of_an_older_card_keeps_the_current_review(self):
        store, users = _store({"user_id": "42"})
        await store.record_sent(42, "e2", "forward", 556)

        await store.record_graded(42, "e1", "forward")

        assert _current(users)["expression_id"] == "e2"

    async def test_grade_in_the_other_direction_keeps_the_current_review(self):
        store, users = _store({"user_id": "42"})
        await store.record_sent(42, "e1", "reverse", 556)

        await store.record_graded(42, "e1", "forward")

        assert _current(users)["direction"] == "reverse"


class TestRecordRemoved:

    async def test_removing_the_current_card_clears_it(self):
        store, users = _store({"user_id": "42"})
        await store.record_sent(42, "e1", "reverse", 555)

        await store.record_removed(42, "e1")

        assert _current(users) is None

    async def test_removing_another_card_keeps_the_current_review(self):
        store, users = _store({"user_id": "42"})
        await store.record_sent(42, "e1", "forward", 555)

        await store.record_removed(42, "e2")

        assert _current(users)["expression_id"] == "e1"


class TestBackfilledReview:

    def _backfilled(self):
        review = {"expression_id": "e1", "direction": "unknown", "message_id": 555, "sent_at": "2026-10-01T10:00:00Z"}
        return _store({"user_id": "42", "current_review": review})

    async def test_grade_in_either_direction_clears_an_unknown_direction(self):
        for direction in ("forward", "reverse"):
            store, users = self._backfilled()

            await store.record_graded(42, "e1", direction)

            assert _current(users) is None

    async def test_backfill_never_overwrites(self):
        store, users = self._backfilled()

        assert await store.backfill_from_legacy(42, "e2", 1, "2026-10-02T00:00:00Z") is False
        assert _current(users)["expression_id"] == "e1"


class TestLegacyPendingAndReviewed:

    async def test_mark_pending_sets_the_flag(self):
        store, users = _store({"user_id": "42", "has_pending": False})

        await store.mark_pending(42)

        assert users.docs[0]["has_pending"] is True

    async def test_clear_pending_clears_the_flag(self):
        store, users = _store({"user_id": "42", "has_pending": True})

        await store.clear_pending(42)

        assert users.docs[0]["has_pending"] is False

    async def test_record_reviewed_starts_the_interval_and_clears_pending(self):
        store, users = _store({"user_id": "42", "has_pending": True})

        await store.record_reviewed(42)

        assert users.docs[0]["has_pending"] is False
        assert users.docs[0]["last_reviewed_at"]

    async def test_no_writer_creates_a_user(self):
        store, users = _store()

        await store.mark_pending(42)
        await store.clear_pending(42)
        await store.record_reviewed(42)

        assert users.docs == []
