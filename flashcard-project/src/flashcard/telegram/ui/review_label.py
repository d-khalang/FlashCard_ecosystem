from typing import Optional

from flashcard.app.review import ReviewReady
from flashcard.services.i18n import I18nService


def review_label(i18n: I18nService, ready: ReviewReady) -> Optional[str]:
    """Marks a stored card sent in place of a failed generation."""
    if not ready.from_storage:
        return None
    key = "messages.saved_card_older_settings" if ready.older_settings else "messages.saved_card"
    return i18n.get(key)
