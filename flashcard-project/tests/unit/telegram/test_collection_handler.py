"""
Unit tests for flashcard.telegram.handlers.collection
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message

from flashcard.telegram.handlers.collection import cmd_remove


@pytest.mark.asyncio
async def test_cmd_remove_uses_current_bot_username():
    message = AsyncMock(spec=Message)
    message.answer = AsyncMock()
    message.bot.username = "shadow_it_bot"

    with patch("flashcard.telegram.handlers.collection.i18n.get") as mock_i18n_get:
        mock_i18n_get.return_value = "remove-guide"

        await cmd_remove(message)

    mock_i18n_get.assert_called_once_with(
        "commands.remove.guide",
        inline_name="@shadow_it_bot",
    )
    message.answer.assert_called_once_with("remove-guide")
