"""Bot texts for card credits: the limit message and the /settings line."""
from typing import Optional

from flashcard.app.quota import CARD_CREDITS, QuotaExceeded, Usage
from flashcard.services.i18n import I18nService


def credits_exceeded_text(i18n: I18nService, result: QuotaExceeded) -> str:
    """The message for a card generation refused because today's credits are used up."""
    return i18n.get("messages.errors.credits_exceeded", limit=result.limit, card_cost=CARD_CREDITS)


def credits_line(i18n: I18nService, usage: Optional[Usage]) -> Optional[str]:
    """Today's credits for the /settings menu; None when nothing limits the user."""
    if usage is None or usage.limit is None:
        return None
    left = max(usage.limit - usage.used, 0)
    return i18n.get("commands.settings.menu.credits", left=left, limit=usage.limit, card_cost=CARD_CREDITS)
