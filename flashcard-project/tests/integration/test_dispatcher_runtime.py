from __future__ import annotations

from bson import ObjectId

from flashcard.telegram.ui.factories.grade_callback import GradeCallback
from flashcard.telegram.ui.factories.inline_remove_callback import InlineRemoveCallback
from flashcard.telegram.ui.factories.settings_callback import SettingsCallback

from .helpers import make_callback_update, make_inline_query_update, make_message_update


async def test_start_command_routes_before_unknown(dispatcher_env, trace_logger):
    update = make_message_update(text="/start")

    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        update,
        **dispatcher_env["dispatcher_data"],
    )

    send_calls = [call for call in dispatcher_env["session"].calls if call.method == "SendMessage"]
    assert len(send_calls) == 1
    assert "Kartino" in send_calls[0].payload["text"]
    assert trace_logger.logged


async def test_unknown_command_hits_unknown_router(dispatcher_env):
    update = make_message_update(text="/notreal")

    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        update,
        **dispatcher_env["dispatcher_data"],
    )

    send_calls = [call for call in dispatcher_env["session"].calls if call.method == "SendMessage"]
    assert len(send_calls) == 1
    assert "didn't understand" in send_calls[0].payload["text"].lower()


async def test_plain_text_creation_generates_card_and_tracks_consumption(dispatcher_env):
    update = make_message_update(text="andare")

    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        update,
        **dispatcher_env["dispatcher_data"],
    )

    send_calls = [call for call in dispatcher_env["session"].calls if call.method == "SendMessage"]
    edit_calls = [call for call in dispatcher_env["session"].calls if call.method == "EditMessageText"]
    assert len(send_calls) == 1
    assert "think" in send_calls[0].payload["text"].lower()
    assert len(edit_calls) == 1
    assert "to go" in edit_calls[0].payload["text"].lower()

    user_doc = await dispatcher_env["user_service"].cols["users"].find_one({"user_id": "42"})
    assert user_doc["consumption"]["system_api"]["cards_generated"] == 1


async def test_save_callback_persists_expression(dispatcher_env):
    update = make_callback_update(data="save:andare", text="Preview card")

    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        update,
        **dispatcher_env["dispatcher_data"],
    )

    saved = await dispatcher_env["expression_service"].cols["expression"].find_one({"user_id": "42", "value": "andare"})
    assert saved is not None
    answer_calls = [call for call in dispatcher_env["session"].calls if call.method == "AnswerCallbackQuery"]
    assert answer_calls


async def test_settings_fsm_state_beats_creation_handler(dispatcher_env):
    nav = SettingsCallback(action="nav", section="set_lang_p").pack()
    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        make_callback_update(data=nav, text="Settings"),
        **dispatcher_env["dispatcher_data"],
    )

    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        make_message_update(text="not-a-language", update_id=11, message_id=11),
        **dispatcher_env["dispatcher_data"],
    )

    edit_calls = [call for call in dispatcher_env["session"].calls if call.method == "EditMessageText"]
    assert not edit_calls
    send_calls = [call for call in dispatcher_env["session"].calls if call.method == "SendMessage"]
    assert any("language" in call.payload["text"].lower() for call in send_calls)


async def test_feedback_fsm_collects_feedback_without_falling_into_creation(dispatcher_env):
    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        make_message_update(text="/feedback"),
        **dispatcher_env["dispatcher_data"],
    )

    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        make_message_update(text="This helped a lot", update_id=12, message_id=12),
        **dispatcher_env["dispatcher_data"],
    )

    user_send_calls = [call for call in dispatcher_env["session"].calls if call.method == "SendMessage"]
    assert any("feedback" in call.payload["text"].lower() for call in user_send_calls)
    logger_calls = dispatcher_env["logger_bot"].session.calls
    assert any("New Feedback" in call.payload["text"] for call in logger_calls if call.method == "SendMessage")


async def test_get_review_command_sends_card_and_updates_pending_state(dispatcher_env):
    expression_id = ObjectId()
    await dispatcher_env["expression_service"].cols["expression"].insert_one(
        {
            "_id": expression_id,
            "user_id": "42",
            "value": "andare",
            "created_at": "2000-01-01T00:00:00Z",
            "status": "active",
        }
    )
    await dispatcher_env["user_service"].cols["users"].update_one(
        {"user_id": "42"},
        {"$set": {"primary_language": "en", "target_level": "A2", "has_pending": False}},
        upsert=True,
    )

    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        make_message_update(text="/get"),
        **dispatcher_env["dispatcher_data"],
    )

    send_calls = [call for call in dispatcher_env["session"].calls if call.method == "SendMessage"]
    assert any("andare" in call.payload["text"].lower() for call in send_calls)
    expression = await dispatcher_env["expression_service"].cols["expression"].find_one({"_id": expression_id})
    assert expression["pending_message_id"] is not None
    user_doc = await dispatcher_env["user_service"].cols["users"].find_one({"user_id": "42"})
    assert user_doc["has_pending"] is True


async def test_grade_callback_updates_expression_and_user(dispatcher_env):
    expression_id = ObjectId()
    await dispatcher_env["expression_service"].cols["expression"].insert_one(
        {
            "_id": expression_id,
            "user_id": "42",
            "value": "andare",
            "created_at": "2000-01-01T00:00:00Z",
            "pending_message_id": 555,
        }
    )
    await dispatcher_env["user_service"].cols["users"].update_one(
        {"user_id": "42"},
        {"$set": {"has_pending": True}},
        upsert=True,
    )

    callback = GradeCallback(expression_id=str(expression_id), grade=4, direction="fwd").pack()
    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        make_callback_update(data=callback, text="Review card"),
        **dispatcher_env["dispatcher_data"],
    )

    expression = await dispatcher_env["expression_service"].cols["expression"].find_one({"_id": expression_id})
    user_doc = await dispatcher_env["user_service"].cols["users"].find_one({"user_id": "42"})
    assert expression["last_grade"] == 4
    assert expression["pending_message_id"] is None
    assert user_doc["has_pending"] is False


async def test_verb_command_uses_scraper_response_and_caches_result(dispatcher_env):
    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        make_message_update(text="/verb andare"),
        **dispatcher_env["dispatcher_data"],
    )

    conjugation = await dispatcher_env["verb_service"].cols["conjugation"].find_one({"verb": "andare"})
    user_doc = await dispatcher_env["user_service"].cols["users"].find_one({"user_id": "42"})
    assert conjugation is not None
    assert user_doc["consumption"]["verb_lookups"] == 1


async def test_inline_remove_confirm_deletes_expression(dispatcher_env):
    expression_id = ObjectId()
    await dispatcher_env["expression_service"].cols["expression"].insert_one(
        {
            "_id": expression_id,
            "user_id": "42",
            "value": "andare",
            "created_at": "2000-01-01T00:00:00Z",
            "status": "active",
        }
    )

    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        make_inline_query_update(query="an"),
        **dispatcher_env["dispatcher_data"],
    )
    callback = InlineRemoveCallback(action="confirm", expression_id=str(expression_id)).pack()
    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        make_callback_update(data=callback, text="andare", message_id=88),
        **dispatcher_env["dispatcher_data"],
    )

    deleted = await dispatcher_env["expression_service"].cols["expression"].find_one({"_id": expression_id})
    assert deleted is None


async def test_llm_failure_is_handled_by_global_error_handler(dispatcher_env):
    dispatcher_env["llm_service"].raise_card_error = True

    await dispatcher_env["dp"].feed_update(
        dispatcher_env["bot"],
        make_message_update(text="andare"),
        **dispatcher_env["dispatcher_data"],
    )

    send_calls = [call for call in dispatcher_env["session"].calls if call.method == "SendMessage"]
    assert any(
        "service" in call.payload["text"].lower()
        or "ai" in call.payload["text"].lower()
        or "sorry" in call.payload["text"].lower()
        for call in send_calls
    )
