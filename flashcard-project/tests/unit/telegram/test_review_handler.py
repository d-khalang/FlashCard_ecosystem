"""
Unit tests for review handler helpers.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from flashcard.telegram.handlers.review import safe_answer_callback


class TestSafeAnswerCallback:

    async def test_swallows_expired_query_error(self):
        callback = MagicMock()
        callback.answer = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(), message="query is too old and response timeout expired")
        )

        await safe_answer_callback(callback, "ok", show_alert=True)

    async def test_reraises_other_bad_request(self):
        callback = MagicMock()
        callback.answer = AsyncMock(
            side_effect=TelegramBadRequest(method=MagicMock(), message="chat not found")
        )

        with pytest.raises(TelegramBadRequest):
            await safe_answer_callback(callback, "ok")
