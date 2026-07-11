from typing import Final

from flashcard.schemas.languages import LanguageCode, LanguageLevel, get_language_flag
from flashcard.settings import settings

# Default user settings. These are process-level defaults loaded from env.
DEFAULT_LANG_1_CODE: Final[LanguageCode] = settings.DEFAULT_PRIMARY_LANGUAGE
DEFAULT_LANG_1_LABEL: Final[str] = (
    f"{get_language_flag(settings.DEFAULT_PRIMARY_LANGUAGE)} "
    f"{settings.DEFAULT_PRIMARY_LANGUAGE.upper()}"
)
DEFAULT_LANG_LEVEL: Final[LanguageLevel] = settings.DEFAULT_TARGET_LEVEL

# Scheduler Settings
DEFAULT_SCHEDULER_INTERVAL_MINUTES: Final[int] = 30
