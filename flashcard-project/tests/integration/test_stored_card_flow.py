"""
The latest delivered card is stored on its expression and sent, free of quota,
when card generation fails or the user is over quota.
"""
from __future__ import annotations

from bson import ObjectId
import pytest

from flashcard.schemas.expression import ExpressionCard, StoredCard
from tests.helpers import TEST_I18N as i18n
from flashcard.utils.time import now_utc

from .helpers import make_message_update

USER_ID = "42"
UNCLEAR = ExpressionCard(success=False, norm="andare", learning_definition=None, translations=[],
                         learning_example=None, note="Not clear", suggestions=[])


async def _feed(env, update):
    await env["dp"].feed_update(env["bot"], update, **env["dispatcher_data"])


async def _setup(env):
    expression_id = ObjectId()
    await env["cols"]["expression"].insert_one({
        "_id": expression_id, "user_id": USER_ID, "value": "andare",
        "created_at": "2000-01-01T00:00:00Z", "status": "active",
    })
    await env["cols"]["users"].update_one(
        {"user_id": USER_ID}, {"$set": {"is_active": True, "target_level": "B1"}}, upsert=True)
    return expression_id


async def _get_again(env, expression_id):
    """Make the card a candidate again (12-hour cooldown) and ask for it."""
    await env["cols"]["expression"].update_one(
        {"_id": expression_id}, {"$set": {"last_activity_at": "2000-01-01T00:00:00Z"}})
    await _feed(env, make_message_update(text="/get", update_id=2, message_id=11))


async def _cards_generated(env) -> int:
    user = await env["cols"]["users"].find_one({"user_id": USER_ID})
    return sum(bucket.get("cards_generated", 0) for bucket in user.get("consumption", {}).values()
               if isinstance(bucket, dict))


async def _use_up_quota(env):
    """More cards today than any tier allows."""
    await env["cols"]["users"].update_one({"user_id": USER_ID}, {"$set": {"consumption": {
        "consumption_date": now_utc().date().isoformat(), "system_api": {"cards_generated": 999}}}})


def _fail_generation(env, failure):
    if failure == "provider_error":
        env["llm_service"].raise_card_error = True
    else:
        env["llm_service"].card = UNCLEAR


def _sent_texts(env) -> list[str]:
    return [call.payload["text"] for call in env["session"].calls if call.method == "SendMessage"]


class TestStoredCard:

    async def test_get_stores_the_delivered_card(self, dispatcher_env):
        expression_id = await _setup(dispatcher_env)

        await _feed(dispatcher_env, make_message_update(text="/get"))

        doc = await dispatcher_env["cols"]["expression"].find_one({"_id": expression_id})
        stored = StoredCard.model_validate(doc["last_card"])
        assert stored.card == dispatcher_env["llm_service"].card
        assert stored.settings.level == "B1"

    @pytest.mark.parametrize("failure", ["provider_error", "unclear_card"])
    async def test_failed_generation_sends_the_stored_card_free(self, dispatcher_env, failure):
        expression_id = await _setup(dispatcher_env)
        await _feed(dispatcher_env, make_message_update(text="/get"))
        used = await _cards_generated(dispatcher_env)

        _fail_generation(dispatcher_env, failure)
        await _get_again(dispatcher_env, expression_id)

        last = _sent_texts(dispatcher_env)[-1]
        assert last.startswith(f"<i>{i18n.get('messages.saved_card')}</i>\n")
        assert "muoversi verso un luogo" in last
        assert await _cards_generated(dispatcher_env) == used

    async def test_changed_level_is_shown_on_the_stored_card(self, dispatcher_env):
        expression_id = await _setup(dispatcher_env)
        await _feed(dispatcher_env, make_message_update(text="/get"))
        await dispatcher_env["cols"]["users"].update_one({"user_id": USER_ID}, {"$set": {"target_level": "C1"}})

        dispatcher_env["llm_service"].raise_card_error = True
        await _get_again(dispatcher_env, expression_id)

        last = _sent_texts(dispatcher_env)[-1]
        assert last.startswith(f"<i>{i18n.get('messages.saved_card_older_settings')}</i>\n")

    async def test_over_quota_sends_the_stored_card_without_generating(self, dispatcher_env):
        expression_id = await _setup(dispatcher_env)
        await _feed(dispatcher_env, make_message_update(text="/get"))
        await _use_up_quota(dispatcher_env)
        dispatcher_env["llm_service"].raise_card_error = True  # would fail the test if called

        await _get_again(dispatcher_env, expression_id)

        last = _sent_texts(dispatcher_env)[-1]
        assert last.startswith(f"<i>{i18n.get('messages.saved_card')}</i>\n")
        assert await _cards_generated(dispatcher_env) == 999

    async def test_over_quota_without_a_stored_card_reports_the_limit(self, dispatcher_env):
        await _setup(dispatcher_env)
        await _use_up_quota(dispatcher_env)

        await _feed(dispatcher_env, make_message_update(text="/get"))

        assert "daily limit" in _sent_texts(dispatcher_env)[-1]
        assert await _cards_generated(dispatcher_env) == 999

    @pytest.mark.parametrize("failure", ["provider_error", "unclear_card"])
    async def test_without_a_stored_card_nothing_is_sent_or_counted(self, dispatcher_env, failure):
        await _setup(dispatcher_env)
        _fail_generation(dispatcher_env, failure)

        await _feed(dispatcher_env, make_message_update(text="/get"))

        assert not any("Your picked expression" in text for text in _sent_texts(dispatcher_env))
        assert await _cards_generated(dispatcher_env) == 0

    async def test_turned_off_secondary_language_matches_an_unset_one(self, dispatcher_env):
        expression_id = await _setup(dispatcher_env)
        await _feed(dispatcher_env, make_message_update(text="/get"))
        await dispatcher_env["cols"]["users"].update_one({"user_id": USER_ID}, {"$set": {"secondary_language": "none"}})

        dispatcher_env["llm_service"].raise_card_error = True
        await _get_again(dispatcher_env, expression_id)

        last = _sent_texts(dispatcher_env)[-1]
        assert last.startswith(f"<i>{i18n.get('messages.saved_card')}</i>\n")
