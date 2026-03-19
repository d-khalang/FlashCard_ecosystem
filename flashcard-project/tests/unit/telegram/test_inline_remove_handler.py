from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId

from flashcard.telegram.handlers.inline_remove import (
    handle_inline_remove_callback,
    handle_inline_remove_query,
)
from flashcard.telegram.ui.factories.inline_remove_callback import InlineRemoveCallback


@pytest.mark.asyncio
class TestHandleInlineRemoveQuery:
    async def test_short_query_returns_empty_results(self):
        inline_query = MagicMock()
        inline_query.query = "a"
        inline_query.from_user.id = 123
        inline_query.answer = AsyncMock()

        expression_service = MagicMock()
        expression_service.search_expressions = AsyncMock()

        await handle_inline_remove_query(inline_query, expression_service)

        expression_service.search_expressions.assert_not_called()
        inline_query.answer.assert_called_once_with(results=[], cache_time=1, is_personal=True)

    async def test_matching_query_returns_articles(self):
        inline_query = MagicMock()
        inline_query.query = "cas"
        inline_query.from_user.id = 123
        inline_query.answer = AsyncMock()

        expression_id = ObjectId()
        expression_service = MagicMock()
        expression_service.search_expressions = AsyncMock(
            return_value=[{"_id": expression_id, "value": "casa"}]
        )

        await handle_inline_remove_query(inline_query, expression_service)

        expression_service.search_expressions.assert_called_once_with(123, "cas", limit=50)
        _, kwargs = inline_query.answer.call_args
        assert kwargs["cache_time"] == 2
        assert kwargs["is_personal"] is True
        assert len(kwargs["results"]) == 1
        assert kwargs["results"][0].title == "casa"

    async def test_overlong_query_returns_empty_results(self):
        inline_query = MagicMock()
        inline_query.query = "a" * 151
        inline_query.from_user.id = 123
        inline_query.answer = AsyncMock()

        expression_service = MagicMock()
        expression_service.search_expressions = AsyncMock()

        await handle_inline_remove_query(inline_query, expression_service)

        expression_service.search_expressions.assert_not_called()
        inline_query.answer.assert_called_once_with(results=[], cache_time=2, is_personal=True)

@pytest.mark.asyncio
class TestHandleInlineRemoveCallback:
    async def test_prompt_action_shows_confirmation_keyboard(self):
        callback = MagicMock()
        callback.inline_message_id = "inline-1"
        callback.bot.edit_message_reply_markup = AsyncMock()
        callback.answer = AsyncMock()

        expression_service = MagicMock()
        callback_data = InlineRemoveCallback(action="prompt", expression_id=str(ObjectId()))

        await handle_inline_remove_callback(callback, callback_data, expression_service)

        callback.bot.edit_message_reply_markup.assert_called_once()
        callback.answer.assert_called_once()

    async def test_cancel_action_restores_initial_keyboard(self):
        callback = MagicMock()
        callback.inline_message_id = "inline-1"
        callback.bot.edit_message_reply_markup = AsyncMock()
        callback.answer = AsyncMock()

        expression_service = MagicMock()
        callback_data = InlineRemoveCallback(action="cancel", expression_id=str(ObjectId()))

        await handle_inline_remove_callback(callback, callback_data, expression_service)

        callback.bot.edit_message_reply_markup.assert_called_once()
        callback.answer.assert_called_once()

    async def test_confirm_action_removes_expression_and_clears_markup(self):
        callback = MagicMock()
        callback.inline_message_id = "inline-1"
        callback.from_user.id = 321
        callback.bot.edit_message_reply_markup = AsyncMock()
        callback.answer = AsyncMock()

        expression_service = MagicMock()
        expression_service.remove_expression = AsyncMock(return_value=True)
        expression_id = str(ObjectId())
        callback_data = InlineRemoveCallback(action="confirm", expression_id=expression_id)

        await handle_inline_remove_callback(callback, callback_data, expression_service)

        expression_service.remove_expression.assert_called_once_with(321, expression_id)
        callback.bot.edit_message_reply_markup.assert_called_once_with(
            inline_message_id="inline-1",
            reply_markup=None,
        )
        callback.answer.assert_called_once()

    async def test_confirm_action_handles_missing_expression(self):
        callback = MagicMock()
        callback.inline_message_id = "inline-1"
        callback.from_user.id = 321
        callback.bot.edit_message_reply_markup = AsyncMock()
        callback.answer = AsyncMock()

        expression_service = MagicMock()
        expression_service.remove_expression = AsyncMock(return_value=False)
        callback_data = InlineRemoveCallback(action="confirm", expression_id="invalid")

        await handle_inline_remove_callback(callback, callback_data, expression_service)

        callback.bot.edit_message_reply_markup.assert_called_once_with(
            inline_message_id="inline-1",
            reply_markup=None,
        )
        callback.answer.assert_called_once()
