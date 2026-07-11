from typing import Awaitable, Callable, Optional, Union
from flashcard.services.llm.llm import LLMService
from flashcard.telegram.ui.expression import render_expression_card
from flashcard.schemas.languages import get_language_flag
from flashcard.schemas.expression import ExpressionCard
from flashcard.schemas.user import UserDB
from flashcard.services.user import UserService
from flashcard.services.i18n import i18n
from flashcard.services.language_validation import LanguageValidityChecker
from flashcard.settings import settings

async def generate_and_render_card(
    llm_service: LLMService,
    user_service: UserService,
    user_id: Union[str, int],
    text: str,
    language_validator: Optional[LanguageValidityChecker] = None,
    on_llm_fallback: Optional[Callable[[], Awaitable[None]]] = None,
) -> tuple[str, bool, Optional[ExpressionCard], UserDB]:
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

    if language_validator is not None:
        validation = await language_validator.validate_expression(text)
        if not validation.is_valid:
            message = i18n.get(
                "messages.errors.invalid_learning_language_input",
                language=settings.LEARNING_LANGUAGE_NAME,
            )
            if validation.suggestions:
                message = f"{message}\n" + "\n".join(validation.suggestions[:3])
            return message, False, None, user
        if validation.normalized_text:
            text = validation.normalized_text

    # Quota check
    uses_own_key = user.api_config is not None
    if not user_service.can_generate_card(user, uses_own_key=uses_own_key):
        limits = user_service._get_effective_limits(user)
        quota_msg = i18n.get(
            "messages.errors.quota_exceeded",
            type="card",
            tier=user.tier.value,
            limit=limits["cards"]
        )
        return quota_msg, False, None, user
    
    lang1_code = user.primary_language
    lang2_code = user.secondary_language
    lang1_label = get_language_flag(lang1_code)
    lang2_label = get_language_flag(lang2_code) if lang2_code else None

    card = await llm_service.generate_expression_card(
        raw=text,
        level=user.target_level,
        lang1_code=lang1_code,
        lang2_code=lang2_code,
        lang1_label=lang1_label,
        lang2_label=lang2_label,
        on_fallback=on_llm_fallback,
    )

    rendered = render_expression_card(card)
    success = rendered.get("success", False)
    content = rendered.get("content", "")
    
    return content, success, card, user

