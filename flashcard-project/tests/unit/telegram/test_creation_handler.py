"""
Unit tests for flashcard.telegram.handlers.creation
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import Message

from flashcard.telegram.handlers.creation import handle_text_message
from flashcard.schemas.user import UserDB
from flashcard.services.language_validation import LanguageValidationResult

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


@pytest.mark.asyncio
async def test_handle_text_message_invalid_language_skips_generation():
    message = AsyncMock(spec=Message)
    message.text = "こんにちは"
    message.from_user = MagicMock(id=123)
    status_msg = AsyncMock()
    message.answer = AsyncMock(return_value=status_msg)

    llm_service = MagicMock()
    user_service = MagicMock()
    user_service.get_user = AsyncMock(return_value=UserDB(user_id="123"))
    user_service.can_generate_card.return_value = True
    consumption_service = MagicMock()
    language_validator = MagicMock()
    language_validator.validate_expression = AsyncMock(
        return_value=LanguageValidationResult(
            is_valid=False,
            normalized_text="こんにちは",
            reason="unsupported_characters",
        )
    )

    await handle_text_message(
        message,
        llm_service,
        user_service,
        consumption_service,
        language_validator=language_validator,
    )

    llm_service.generate_expression_card.assert_not_called()
    consumption_service.increment.assert_not_called()
    status_msg.edit_text.assert_called_once()
