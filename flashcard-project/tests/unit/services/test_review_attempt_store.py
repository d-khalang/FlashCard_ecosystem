"""
Unit tests for ReviewAttemptStore against the in-memory Mongo fake.

The fake does not enforce indexes; the one-open-attempt rule is checked by state here.
"""
from flashcard.services.review_attempt import ReviewAttemptStore
from tests.integration.helpers import make_cols


def _store():
    cols = make_cols()
    return ReviewAttemptStore(cols=cols), cols["review_attempts"]


def _states(collection):
    return sorted((doc["expression_id"], doc["state"]) for doc in collection.docs)


class TestRecordSent:

    async def test_creates_an_open_attempt(self):
        store, attempts = _store()

        await store.record_sent(42, "e1", "forward", 555)

        [doc] = attempts.docs
        assert doc["user_id"] == "42"
        assert (doc["expression_id"], doc["direction"], doc["message_id"]) == ("e1", "forward", 555)
        assert doc["state"] == "open"
        assert doc["sent_at"] and doc["closed_at"] is None

    async def test_new_card_supersedes_the_open_one(self):
        store, attempts = _store()

        await store.record_sent(42, "e1", "forward", 555)
        await store.record_sent(42, "e2", "reverse", 556)

        assert _states(attempts) == [("e1", "superseded"), ("e2", "open")]

    async def test_other_users_are_untouched(self):
        store, attempts = _store()

        await store.record_sent(42, "e1", "forward", 555)
        await store.record_sent(7, "e2", "forward", 556)

        assert _states(attempts) == [("e1", "open"), ("e2", "open")]


class TestRecordGraded:

    async def test_closes_the_open_attempt(self):
        store, attempts = _store()
        await store.record_sent(42, "e1", "forward", 555)

        assert await store.record_graded(42, "e1", "forward", 4) is True

        [doc] = attempts.docs
        assert (doc["state"], doc["grade"]) == ("graded", 4)
        assert doc["closed_at"] is not None

    async def test_a_superseded_attempt_can_still_be_graded(self):
        store, attempts = _store()
        await store.record_sent(42, "e1", "forward", 555)
        await store.record_sent(42, "e2", "forward", 556)

        assert await store.record_graded(42, "e1", "forward", 3) is True

        assert _states(attempts) == [("e1", "graded"), ("e2", "open")]

    async def test_fills_an_unknown_direction(self):
        store, attempts = _store()
        await attempts.insert_one({"user_id": "42", "expression_id": "e1", "direction": "unknown",
                                   "message_id": 555, "state": "open", "sent_at": "2026-01-01T00:00:00Z"})

        await store.record_graded(42, "e1", "reverse", 2)

        assert attempts.docs[0]["direction"] == "reverse"

    async def test_without_an_attempt_returns_false(self):
        """Cards sent before attempts were recorded still grade through the legacy path."""
        store, attempts = _store()

        assert await store.record_graded(42, "e1", "forward", 4) is False
        assert attempts.docs == []

    async def test_a_graded_attempt_is_not_graded_again(self):
        store, attempts = _store()
        await store.record_sent(42, "e1", "forward", 555)
        await store.record_graded(42, "e1", "forward", 4)

        assert await store.record_graded(42, "e1", "forward", 1) is False
        assert attempts.docs[0]["grade"] == 4


class TestRecordRemoved:

    async def test_closes_open_and_superseded_attempts_of_the_card(self):
        store, attempts = _store()
        await store.record_sent(42, "e1", "forward", 555)
        await store.record_sent(42, "e2", "forward", 556)
        await store.record_sent(42, "e1", "reverse", 557)

        await store.record_removed(42, "e1")

        assert _states(attempts) == [("e1", "removed"), ("e1", "removed"), ("e2", "superseded")]

    async def test_graded_attempts_stay_graded(self):
        store, attempts = _store()
        await store.record_sent(42, "e1", "forward", 555)
        await store.record_graded(42, "e1", "forward", 4)

        await store.record_removed(42, "e1")

        assert attempts.docs[0]["state"] == "graded"


class TestEnsureIndexes:

    async def test_creates_the_open_attempt_index(self):
        store, attempts = _store()
        calls = []

        async def create_index(keys, **kwargs):
            calls.append((keys, kwargs))

        attempts.create_index = create_index
        await store.ensure_indexes()

        open_index = next(kwargs for _, kwargs in calls if kwargs["name"] == "one_open_attempt_per_user")
        assert open_index["unique"] is True
        assert open_index["partialFilterExpression"] == {"state": "open"}
