"""
Unit tests for flashcard.telegram.handlers.creation
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import Message

from flashcard.telegram.handlers.creation import handle_text_message
from flashcard.schemas.user import UserDB

@pytest.mark.asyncio
async def test_handle_text_message_too_long():
    # Setup mocks
    message = AsyncMock(spec=Message)
    message.text = "A" * 151  # One character over the limit
    message.answer = AsyncMock()
    
    llm_service = MagicMock()
    user_service = MagicMock()
    consumption_service = MagicMock()
    
    with patch("flashcard.telegram.handlers.creation.i18n.get") as mock_i18n_get:
        mock_i18n_get.return_value = "Input too long error message"

        # Call handler
        await handle_text_message(message, llm_service, user_service, consumption_service)

        # Assertions
        # 1. It should answer with an error message
        message.answer.assert_called_once_with("Input too long error message")
        mock_i18n_get.assert_called_with("messages.errors.input_too_long")
        
        # 2. It should NOT call the LLM service or any other service
        llm_service.generate_expression_card.assert_not_called()
        user_service.get_user.assert_not_called()
        consumption_service.increment.assert_not_called()
