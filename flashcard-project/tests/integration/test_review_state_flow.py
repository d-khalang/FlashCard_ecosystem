"""
Characterization tests for review state across send, grade, save and remove.

They pin the current `has_pending` / cooldown behaviour before review state
moves to its own model, so the migration can prove it preserves it.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from bson import ObjectId

from flashcard.scheduler.scheduler import find_users_due_for_review
from flashcard.telegram.ui.factories.grade_callback import GradeCallback
from flashcard.telegram.ui.factories.inline_remove_callback import InlineRemoveCallback
from flashcard.utils.time import iso_z, now_utc

from .helpers import make_callback_update, make_message_update

USER_ID = 42


async def _feed(env, update):
    await env["dp"].feed_update(env["bot"], update, **env["dispatcher_data"])


async def _insert_card(env, value="andare", **fields):
    expression_id = ObjectId()
    await env["cols"]["expression"].insert_one({
        "_id": expression_id,
        "user_id": str(USER_ID),
        "value": value,
        "created_at": "2000-01-01T00:00:00Z",
        "status": "active",
        **fields,
    })
    return expression_id


async def _set_user(env, **fields):
    await env["cols"]["users"].update_one(
        {"user_id": str(USER_ID)}, {"$set": {"is_active": True, **fields}}, upsert=True)


async def _user_doc(env):
    return await env["cols"]["users"].find_one({"user_id": str(USER_ID)})


async def _due_ids(env):
    return [user.user_id for user in await find_users_due_for_review(env["user_service"])]


class TestSchedulerPause:

    async def test_unanswered_review_pauses_scheduler(self, dispatcher_env):
        await _insert_card(dispatcher_env)
        await _set_user(dispatcher_env, has_pending=False, last_reviewed_at=None)

        await _feed(dispatcher_env, make_message_update(text="/get"))

        assert (await _user_doc(dispatcher_env))["has_pending"] is True
        assert USER_ID not in await _due_ids(dispatcher_env)

    async def test_saving_a_word_resumes_scheduler_while_review_is_unanswered(self, dispatcher_env):
        """Intentional: an active user should not be left without scheduled reviews."""
        await _insert_card(dispatcher_env, pending_message_id=555)
        await _set_user(dispatcher_env, has_pending=True, last_reviewed_at=None)

        await _feed(dispatcher_env, make_callback_update(data="save:mangiare", text="Preview card"))

        assert (await _user_doc(dispatcher_env))["has_pending"] is False
        assert USER_ID in await _due_ids(dispatcher_env)

    async def test_removing_the_pending_card_resumes_scheduler(self, dispatcher_env):
        expression_id = await _insert_card(dispatcher_env, pending_message_id=555)
        await _set_user(dispatcher_env, has_pending=True, last_reviewed_at=None)

        callback = InlineRemoveCallback(action="confirm", expression_id=str(expression_id)).pack()
        await _feed(dispatcher_env, make_callback_update(data=callback, text="andare", message_id=88))

        assert (await _user_doc(dispatcher_env))["has_pending"] is False
        assert USER_ID in await _due_ids(dispatcher_env)


# Stored dates and the legacy ISO text (until `convert_dates` has run) must behave the same.
STORED_FORMS = [pytest.param(lambda dt: dt, id="date"), pytest.param(iso_z, id="legacy_text")]


@pytest.mark.parametrize("stored", STORED_FORMS)
class TestCandidateCooldown:

    async def test_sent_card_is_not_a_candidate_within_12_hours(self, dispatcher_env, stored):
        recent = stored(now_utc() - timedelta(hours=1))
        await _insert_card(dispatcher_env, last_activity_at=recent, pending_message_id=555)

        assert await dispatcher_env["expression_service"].get_review_candidate(USER_ID, "standard") is None

    async def test_new_card_waits_12_hours_after_creation(self, dispatcher_env, stored):
        await _insert_card(dispatcher_env, created_at=stored(now_utc() - timedelta(hours=1)))
        assert await dispatcher_env["expression_service"].get_review_candidate(USER_ID, "standard") is None

        await dispatcher_env["cols"]["expression"].update_one(
            {"user_id": str(USER_ID)}, {"$set": {"created_at": stored(now_utc() - timedelta(hours=13))}})
        assert await dispatcher_env["expression_service"].get_review_candidate(USER_ID, "standard") is not None

    async def test_ungraded_card_is_a_candidate_again_after_12_hours(self, dispatcher_env, stored):
        old = stored(now_utc() - timedelta(hours=13))
        expression_id = await _insert_card(dispatcher_env, last_activity_at=old, pending_message_id=555)

        candidate = await dispatcher_env["expression_service"].get_review_candidate(USER_ID, "standard")

        assert candidate is not None
        assert candidate.expression.id == str(expression_id)


class TestStoredDates:
    """Every write stores real dates; legacy text is only read."""

    USER_DATES = ["created_at", "last_reviewed_at", "last_seen_at", "current_review.sent_at"]
    EXPRESSION_DATES = ["created_at", "last_sent_at", "last_interaction_at", "last_activity_at",
                        "reverse_stats.last_review_at", "last_card.generated_at"]

    async def test_send_grade_and_save_write_dates(self, dispatcher_env):
        expression_id = await _insert_card(dispatcher_env, created_at=now_utc() - timedelta(days=1))
        await _feed(dispatcher_env, make_message_update(text="/get"))
        user = await _user_doc(dispatcher_env)
        assert user["current_review"]["sent_at"]  # a review was sent

        callback = GradeCallback(expression_id=str(expression_id), grade=4, direction="fwd").pack()
        await _feed(dispatcher_env, make_callback_update(data=callback, text="Review card"))
        await _feed(dispatcher_env, make_callback_update(data="save:nuovo", text="Card", update_id=3))

        written = [(f"users.{path}", _get(await _user_doc(dispatcher_env), path)) for path in self.USER_DATES]
        for doc in dispatcher_env["cols"]["expression"].docs:
            written += [(f"expression.{path}", _get(doc, path)) for path in self.EXPRESSION_DATES]
        present = {name: value for name, value in written if value is not None}
        assert {"users.created_at", "users.last_reviewed_at", "users.last_seen_at",
                "expression.last_sent_at", "expression.last_interaction_at",
                "expression.last_activity_at", "expression.last_card.generated_at"} <= set(present)
        assert {name: value for name, value in present.items() if not isinstance(value, datetime)} == {}


def _get(doc, path):
    for part in path.split("."):
        doc = (doc or {}).get(part)
    return doc


class TestCurrentReviewShadow:
    """users.current_review is written alongside the legacy fields during the migration."""

    async def test_get_sets_the_current_review_and_grade_clears_it(self, dispatcher_env):
        expression_id = await _insert_card(dispatcher_env)
        await _set_user(dispatcher_env, has_pending=False, last_reviewed_at=None)

        await _feed(dispatcher_env, make_message_update(text="/get"))

        current = (await _user_doc(dispatcher_env))["current_review"]
        assert current["expression_id"] == str(expression_id)
        assert current["direction"] == "forward"
        assert current["message_id"] is not None

        callback = GradeCallback(expression_id=str(expression_id), grade=4, direction="fwd").pack()
        await _feed(dispatcher_env, make_callback_update(data=callback, text="Review card"))

        assert "current_review" not in await _user_doc(dispatcher_env)

    async def test_removing_the_card_clears_the_current_review(self, dispatcher_env):
        expression_id = await _insert_card(dispatcher_env)
        await _set_user(dispatcher_env, has_pending=False, last_reviewed_at=None)
        await _feed(dispatcher_env, make_message_update(text="/get"))

        callback = InlineRemoveCallback(action="confirm", expression_id=str(expression_id)).pack()
        await _feed(dispatcher_env, make_callback_update(data=callback, text="andare", message_id=88))

        assert "current_review" not in await _user_doc(dispatcher_env)

    async def test_grading_a_card_sent_before_the_migration_still_works(self, dispatcher_env):
        expression_id = await _insert_card(dispatcher_env, pending_message_id=555)
        await _set_user(dispatcher_env, has_pending=True)

        callback = GradeCallback(expression_id=str(expression_id), grade=3, direction="rev").pack()
        await _feed(dispatcher_env, make_callback_update(data=callback, text="Review card"))

        user = await _user_doc(dispatcher_env)
        assert user["has_pending"] is False
        assert "current_review" not in user


class TestLastSeen:

    async def test_any_interaction_records_last_seen(self, dispatcher_env):
        await _feed(dispatcher_env, make_message_update(text="/start"))

        assert (await _user_doc(dispatcher_env))["last_seen_at"] is not None


class TestUserCreation:
    """Only the middleware's record_seen creates users; created_at is the trial start."""

    async def test_first_ever_update_creates_the_user_with_created_at(self, dispatcher_env):
        # Ordering itself is pinned in test_trace_middleware.py; the fake DB cannot show the race.
        await _feed(dispatcher_env, make_callback_update(data="save:andare", text="Preview card"))

        user = await _user_doc(dispatcher_env)
        assert user["created_at"] is not None
        assert user["created_at"] == user["last_seen_at"]

    async def test_a_seen_failure_does_not_block_the_handler(self, dispatcher_env, monkeypatch):
        async def failing_record_seen(*_):
            raise RuntimeError("mongo down")

        monkeypatch.setattr(dispatcher_env["user_service"], "record_seen", failing_record_seen)
        await _insert_card(dispatcher_env)

        await _feed(dispatcher_env, make_message_update(text="/start"))

        assert any(call.method == "SendMessage" for call in dispatcher_env["session"].calls)


class TestCurrentReviewPauseRule:
    """The same flows under REVIEW_PAUSE_RULE=current_review."""

    async def _due(self, env):
        return [user.user_id for user in await find_users_due_for_review(env["user_service"], "current_review")]

    async def test_sent_card_pauses_and_grade_resumes(self, dispatcher_env):
        expression_id = await _insert_card(dispatcher_env)
        await _set_user(dispatcher_env, last_reviewed_at=None)

        await _feed(dispatcher_env, make_message_update(text="/get"))
        assert USER_ID not in await self._due(dispatcher_env)

        callback = GradeCallback(expression_id=str(expression_id), grade=4, direction="fwd").pack()
        await _feed(dispatcher_env, make_callback_update(data=callback, text="Review card"))
        # Grading also starts the user's interval; only the pause is checked here.
        await _set_user(dispatcher_env, last_reviewed_at=None)

        assert USER_ID in await self._due(dispatcher_env)

    async def test_interaction_after_the_card_resumes(self, dispatcher_env):
        await _insert_card(dispatcher_env)
        await _set_user(dispatcher_env, last_reviewed_at=None)
        await _feed(dispatcher_env, make_message_update(text="/get"))

        later = iso_z(now_utc() + timedelta(seconds=5))
        await _set_user(dispatcher_env, last_seen_at=later)

        assert USER_ID in await self._due(dispatcher_env)
