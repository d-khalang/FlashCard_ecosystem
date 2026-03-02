from typing import Union
from aiogram import Bot
from flashcard.services.llm.llm import LLMService
from flashcard.telegram.ui.expression import render_expression_card
from flashcard.schemas.languages import get_language_flag
from flashcard.schemas.expression import ExpressionCard
from flashcard.schemas.user import UserDB
from flashcard.services.user import UserService

async def generate_and_render_card(
    llm_service: LLMService,
    user_service: UserService,
    user_id: Union[str, int],
    text: str,
    logger_bot: Bot = None,
) -> tuple[str, bool, ExpressionCard, UserDB]:
    """
    Generates an expression card using LLMService and returns the rendered text, success status, the card object, and user.
    
    Args:
        llm_service: Instance of LLMService.
        user_service: Instance of UserService.
        user_id: User ID.
        text: Input text (raw or normalized).

    Returns:
        tuple[str, bool, ExpressionCard, UserDB]: (rendered_text, success, card_object, user)
    """

    user = await user_service.get_user(user_id)
    
    lang1_code = user.primary_language
    lang2_code = user.secondary_language
    lang1_label = get_language_flag(lang1_code)
    lang2_label = get_language_flag(lang2_code) if lang2_code else None

    try:
        card = await llm_service.generate_expression_card(
            raw=text,
            level=user.target_level,
            lang1_code=lang1_code,
            lang2_code=lang2_code,
            lang1_label=lang1_label,
            lang2_label=lang2_label,
        )

        rendered = render_expression_card(card)
        success = rendered.get("success", False)
        content = rendered.get("content", "")
        
        return content, success, card, user
    
    except Exception as e:
        from flashcard.utils.logger import get_logger, notify_admin_with_trace
        get_logger(__name__).error(f"Error generating card for '{text}': {e}", exc_info=True)
        if logger_bot:
            await notify_admin_with_trace(logger_bot, f"LLM Generation Error for '{text}': {e}")
        return "", False, None, user

