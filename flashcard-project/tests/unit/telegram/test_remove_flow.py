"""
Tests for inline remove at the Telegram entry point: search saved cards inline, then
Remove -> confirm/cancel -> delete.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from bson import ObjectId

from flashcard.app.collection import CollectionUseCases
from flashcard.services.i18n import i18n
from flashcard.telegram.handlers import inline_remove
from flashcard.telegram.ui.factories.inline_remove_callback import InlineRemoveCallback


USER_ID = 666
EXPRESSION_ID = str(ObjectId())


def _deps(*, found=None, removed=True):
    expression_service = MagicMock()
    expression_service.search_expressions = AsyncMock(return_value=found or [])
    expression_service.remove_expression = (
        AsyncMock(side_effect=removed) if isinstance(removed, Exception) else AsyncMock(return_value=removed))
    return SimpleNamespace(expression_service=expression_service)


def _use_cases(d) -> CollectionUseCases:
    return CollectionUseCases(review_state=AsyncMock(), expression_service=d.expression_service, user_service=AsyncMock(),
                              quota=MagicMock(), llm_service=MagicMock())


async def _query(d, text):
    inline_query = MagicMock()
    inline_query.query = text
    inline_query.from_user.id = USER_ID
    inline_query.answer = AsyncMock()
    await inline_remove.handle_inline_remove_query(inline_query, collection_use_cases=_use_cases(d))
    return inline_query


def _callback(*, inline=True):
    callback = MagicMock()
    callback.from_user.id = USER_ID
    callback.inline_message_id = "inline-1" if inline else None
    callback.bot.edit_message_reply_markup = AsyncMock()
    callback.message.edit_reply_markup = AsyncMock()
    callback.answer = AsyncMock()
    return callback


def _stale_callback():
    callback = _callback()
    callback.bot.edit_message_reply_markup = AsyncMock(
        side_effect=TelegramBadRequest(method=MagicMock(), message="message to edit not found"))
    return callback


async def _press(d, action, callback=None, expression_id=EXPRESSION_ID):
    callback = callback or _callback()
    data = InlineRemoveCallback(action=action, expression_id=expression_id)
    await inline_remove.handle_inline_remove_callback(callback, data, collection_use_cases=_use_cases(d))
    return callback


def _buttons(markup) -> list[tuple[str, str]]:
    return [(b.text, InlineRemoveCallback.unpack(b.callback_data).action)
            for row in markup.inline_keyboard for b in row]


def _new_markup(callback):
    return callback.bot.edit_message_reply_markup.await_args.kwargs["reply_markup"]


class TestRemoveSearch:

    @pytest.mark.parametrize("text", ["", "a", " a ", "   "])
    async def test_short_query_answers_nothing_without_searching(self, text):
        d = _deps()
        inline_query = await _query(d, text)

        d.expression_service.search_expressions.assert_not_awaited()
        inline_query.answer.assert_awaited_once_with(results=[], cache_time=1, is_personal=True)

    async def test_query_over_150_chars_answers_nothing_without_searching(self):
        d = _deps()
        inline_query = await _query(d, "a" * 151)

        d.expression_service.search_expressions.assert_not_awaited()
        inline_query.answer.assert_awaited_once_with(results=[], cache_time=2, is_personal=True)

    async def test_query_is_stripped_and_limited_to_50_results(self):
        d = _deps()
        await _query(d, "  cas  ")

        d.expression_service.search_expressions.assert_awaited_once_with(USER_ID, "cas", limit=50)

    async def test_each_match_is_an_article_with_a_remove_button(self):
        first, second = ObjectId(), ObjectId()
        d = _deps(found=[{"_id": first, "value": "casa"}, {"_id": second, "value": "casetta"}])
        inline_query = await _query(d, "cas")

        kwargs = inline_query.answer.await_args.kwargs
        assert (kwargs["cache_time"], kwargs["is_personal"]) == (2, True)
        results = kwargs["results"]
        assert [(r.id, r.title) for r in results] == [(str(first), "casa"), (str(second), "casetta")]
        assert results[0].description == i18n.get("callbacks.inline_remove.result_description")
        assert results[0].input_message_content.message_text == "casa"
        assert _buttons(results[0].reply_markup) == [(i18n.get("messages.buttons.inline_remove"), "prompt")]
        assert InlineRemoveCallback.unpack(
            results[1].reply_markup.inline_keyboard[0][0].callback_data).expression_id == str(second)

    async def test_matches_without_id_or_value_are_skipped(self):
        good = ObjectId()
        d = _deps(found=[{"value": "senza id"}, {"_id": ObjectId(), "value": ""}, {"_id": good, "value": "casa"}])
        inline_query = await _query(d, "cas")

        assert [r.id for r in inline_query.answer.await_args.kwargs["results"]] == [str(good)]


class TestRemoveConfirmation:

    async def test_remove_asks_for_confirmation(self):
        d = _deps()
        callback = await _press(d, "prompt")

        assert _buttons(_new_markup(callback)) == [
            (i18n.get("messages.buttons.inline_remove_cancel"), "cancel"),
            (i18n.get("messages.buttons.inline_remove_confirm"), "confirm"),
        ]
        callback.answer.assert_awaited_once_with(i18n.get("callbacks.inline_remove.prompt"), show_alert=True)
        d.expression_service.remove_expression.assert_not_awaited()

    async def test_cancel_restores_remove_button(self):
        d = _deps()
        callback = await _press(d, "cancel")

        assert _buttons(_new_markup(callback)) == [(i18n.get("messages.buttons.inline_remove"), "prompt")]
        callback.answer.assert_awaited_once_with(i18n.get("callbacks.inline_remove.cancelled"), show_alert=False)
        d.expression_service.remove_expression.assert_not_awaited()

    async def test_confirm_removes_and_clears_buttons(self):
        d = _deps(removed=True)
        callback = await _press(d, "confirm")

        d.expression_service.remove_expression.assert_awaited_once_with(USER_ID, EXPRESSION_ID)
        callback.bot.edit_message_reply_markup.assert_awaited_once_with(
            inline_message_id="inline-1", reply_markup=None)
        callback.answer.assert_awaited_once_with(i18n.get("callbacks.inline_remove.removed"), show_alert=False)

    async def test_confirm_on_missing_card_clears_buttons_and_alerts(self):
        d = _deps(removed=False)
        callback = await _press(d, "confirm", expression_id="not-an-id")

        d.expression_service.remove_expression.assert_awaited_once_with(USER_ID, "not-an-id")
        callback.bot.edit_message_reply_markup.assert_awaited_once_with(
            inline_message_id="inline-1", reply_markup=None)
        callback.answer.assert_awaited_once_with(i18n.get("callbacks.inline_remove.missing"), show_alert=True)

    async def test_chat_message_is_edited_when_not_inline(self):
        d = _deps()
        callback = await _press(d, "confirm", callback=_callback(inline=False))

        callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
        callback.bot.edit_message_reply_markup.assert_not_awaited()


class TestRemoveErrors:

    async def test_unexpected_error_alerts_error(self):
        d = _deps(removed=RuntimeError("db down"))
        callback = await _press(d, "confirm")

        callback.answer.assert_awaited_once_with(i18n.get("callbacks.inline_remove.error"), show_alert=True)

    @pytest.mark.parametrize("removed, text_key, show_alert", [
        (True, "callbacks.inline_remove.removed", False),
        (False, "callbacks.inline_remove.missing", True),
    ])
    async def test_stale_message_after_confirm_still_reports_the_removal(self, removed, text_key, show_alert):
        # Clearing the buttons is cosmetic; the answer reflects what happened to the card.
        d = _deps(removed=removed)
        callback = _stale_callback()
        await _press(d, "confirm", callback=callback)

        d.expression_service.remove_expression.assert_awaited_once()
        callback.answer.assert_awaited_once_with(i18n.get(text_key), show_alert=show_alert)

    async def test_stale_message_on_prompt_reports_invalid(self):
        d = _deps()
        callback = _stale_callback()
        await _press(d, "prompt", callback=callback)

        callback.answer.assert_awaited_once_with(i18n.get("callbacks.inline_remove.invalid"), show_alert=True)
        d.expression_service.remove_expression.assert_not_awaited()
