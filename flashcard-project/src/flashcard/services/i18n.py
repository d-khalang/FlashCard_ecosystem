"""
Interface text for one instance (docs/bot-architecture-refactor.md, #7).

The composition root builds one `I18nService` from the instance's `LanguageConfig`
and passes it down (Telegram handlers receive it as `i18n`); nothing imports a
shared instance, so importing a module never reads settings.
"""
import json
import os
from importlib.resources import files
from typing import Dict, Any, Optional

from flashcard.language import LanguageConfig
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)

# Used for any key the instance's UI locale lacks.
FALLBACK_LOCALE = "en"


class I18nService:
    def __init__(self, *, locale: str, language_name: str, locales_dir: Optional[str] = None):
        """
        `locale`: the UI locale (`UI_LOCALE`); `language_name`: the language this
        instance teaches, filled into `{language}` / `{language_lower}`.
        """
        self.locale = locale
        self.language_name = language_name
        self.locales_dir = locales_dir
        self.translations: Dict[str, Dict[str, Any]] = {}
        self._load_locales()

    @classmethod
    def for_language(cls, language: LanguageConfig) -> "I18nService":
        return cls(locale=language.ui_locale, language_name=language.name)

    def _load_locales(self):
        """Load locale JSON either from a custom directory or package resources."""
        if self.locales_dir:
            self._load_locales_from_dir(self.locales_dir)
            return

        try:
            locales_root = files("flashcard").joinpath("resources/locales")
            for resource in locales_root.iterdir():
                if resource.name.endswith(".json"):
                    lang_code = resource.name[:-5]
                    try:
                        self.translations[lang_code] = json.loads(
                            resource.read_text(encoding="utf-8")
                        )
                    except Exception as e:
                        logger.error(f"Error loading locale {lang_code}: {e}")
        except Exception:
            return

    def _load_locales_from_dir(self, locales_dir: str):
        if not os.path.exists(locales_dir):
            return

        for filename in os.listdir(locales_dir):
            if filename.endswith(".json"):
                lang_code = filename[:-5]
                file_path = os.path.join(locales_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        self.translations[lang_code] = json.load(f)
                except Exception as e:
                    logger.error(f"Error loading locale {lang_code}: {e}")

    def _lookup(self, locale: str, key: str) -> Any:
        value: Any = self.translations.get(locale, {})
        for k in key.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(k)
        return value

    def get(self, key: str, **kwargs) -> Any:
        """
        Retrieves a translation string.
        Supports nested keys using dot notation (e.g., 'start.welcome').
        A key missing from the UI locale falls back to English, then to the key itself.
        """
        value = self._lookup(self.locale, key)
        if value is None and self.locale != FALLBACK_LOCALE:
            value = self._lookup(FALLBACK_LOCALE, key)
        if value is None:
            return key

        if isinstance(value, str):
            kwargs.setdefault("language", self.language_name)
            kwargs.setdefault("language_lower", self.language_name.lower())
            try:
                return value.format(**kwargs)
            except KeyError:
                return value

        return value
