"""
Unit tests for flashcard.telegram.handlers.creation
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import Message

from flashcard.app.creation import CreationUseCases
from flashcard.telegram.handlers.creation import handle_text_message
from flashcard.services.language_validation import LanguageValidationResult
from tests.helpers import TEST_LANGUAGE, make_user

@pytest.mark.asyncio
async def test_handle_text_message_too_long():
    # Setup mocks
    message = AsyncMock(spec=Message)
    message.text = "A" * 151  # One character over the limit
    message.answer = AsyncMock()
    
    llm_service = MagicMock()
    user_service = MagicMock()
    quota = MagicMock()
    
    with patch("flashcard.telegram.handlers.creation.i18n.get") as mock_i18n_get:
        mock_i18n_get.return_value = "Input too long error message"

        # Call handler
        use_cases = CreationUseCases(MagicMock(), user_service, quota, llm_service, review_state=AsyncMock())
        await handle_text_message(message, creation_use_cases=use_cases, language=TEST_LANGUAGE)

        # Assertions
        # 1. It should answer with an error message
        message.answer.assert_called_once_with("Input too long error message")
        mock_i18n_get.assert_called_with("messages.errors.input_too_long")
        
        # 2. It should NOT call the LLM service or any other service
        llm_service.generate_expression_card.assert_not_called()
        user_service.get_user.assert_not_called()
        quota.record.assert_not_called()


@pytest.mark.asyncio
async def test_handle_text_message_invalid_language_skips_generation():
    message = AsyncMock(spec=Message)
    message.text = "こんにちは"
    message.from_user = MagicMock(id=123)
    status_msg = AsyncMock()
    message.answer = AsyncMock(return_value=status_msg)

    llm_service = MagicMock()
    user_service = MagicMock()
    user_service.get_user = AsyncMock(return_value=make_user(user_id="123"))
    quota = MagicMock()
    language_validator = MagicMock()
    language_validator.validate_expression = AsyncMock(
        return_value=LanguageValidationResult(
            is_valid=False,
            normalized_text="こんにちは",
            reason="unsupported_characters",
        )
    )

    use_cases = CreationUseCases(MagicMock(), user_service, quota, llm_service, review_state=AsyncMock(),
                                 language_validator=language_validator)
    await handle_text_message(message, creation_use_cases=use_cases, language=TEST_LANGUAGE)

    llm_service.generate_expression_card.assert_not_called()
    quota.record.assert_not_called()
    status_msg.edit_text.assert_called_once()
