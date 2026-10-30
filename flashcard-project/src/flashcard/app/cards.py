"""
Card generation shared by creation and review: the settings a card is made with,
and the one LLM call that makes it. Both flows use these, so a card for the same
user and expression is requested the same way.
"""
from typing import Awaitable, Callable, Optional

from flashcard.schemas.expression import CardSettings, ExpressionCard
from flashcard.schemas.languages import get_language_flag
from flashcard.schemas.user import UserDB
from flashcard.services.llm.llm import LLMService

FallbackNotifier = Callable[[], Awaitable[None]]


def card_settings(user: UserDB) -> CardSettings:
    """The user's settings for a card. UserService has already filled missing ones from the instance defaults."""
    return CardSettings(
        level=user.target_level,
        primary_language=user.primary_language,
        secondary_language=user.secondary_translation,
    )


async def generate_card(
    llm: LLMService,
    raw: str,
    settings: CardSettings,
    on_fallback: Optional[FallbackNotifier] = None,
) -> ExpressionCard:
    """Generate a card. `on_fallback` is awaited if the primary LLM provider fails over."""
    primary = settings.primary_language
    secondary = settings.secondary_language
    return await llm.generate_expression_card(
        raw=raw,
        level=settings.level,
        lang1_code=primary,
        lang2_code=secondary,
        lang1_label=get_language_flag(primary),
        lang2_label=get_language_flag(secondary) if secondary else None,
        on_fallback=on_fallback,
    )
