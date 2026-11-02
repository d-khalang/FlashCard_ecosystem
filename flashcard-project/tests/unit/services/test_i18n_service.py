"""
Unit tests for flashcard.services.i18n.I18nService

Tests locale loading, dot-notation key lookups, fallback behavior,
and string formatting with kwargs. Uses temp directory with fixture
JSON files instead of mocking.
"""
import json
import os
import tempfile

from flashcard.services.i18n import I18nService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _create_i18n_service(translations: dict, locale: str = "en", language_name: str = "Italian") -> I18nService:
    """
    Create an I18nService with temp JSON locale files.

    Args:
        translations: dict of {lang_code: {key_tree}} 
                      e.g. {"en": {"start": {"welcome": "Hello"}}}
    """
    tmpdir = tempfile.mkdtemp()
    for lang_code, data in translations.items():
        filepath = os.path.join(tmpdir, f"{lang_code}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f)
    return I18nService(locale=locale, language_name=language_name, locales_dir=tmpdir)


# ===================================================================
# Basic key retrieval
# ===================================================================
class TestBasicGet:

    def test_simple_key(self):
        svc = _create_i18n_service({"en": {"greeting": "Hello"}})
        assert svc.get("greeting") == "Hello"

    def test_nested_key_with_dot_notation(self):
        svc = _create_i18n_service({
            "en": {"start": {"welcome": "Welcome to the bot!"}}
        })
        assert svc.get("start.welcome") == "Welcome to the bot!"

    def test_deeply_nested_key(self):
        svc = _create_i18n_service({
            "en": {"commands": {"verb": {"usage": "Use /verb <word>"}}}
        })
        assert svc.get("commands.verb.usage") == "Use /verb <word>"

    def test_missing_key_returns_key_string(self):
        svc = _create_i18n_service({"en": {"greeting": "Hello"}})
        assert svc.get("nonexistent.key") == "nonexistent.key"


# ===================================================================
# Locale fallback
# ===================================================================
class TestLocaleFallback:

    def test_unsupported_locale_falls_back_to_english(self):
        svc = _create_i18n_service({"en": {"greeting": "Hello"}}, locale="xx")
        assert svc.get("greeting") == "Hello"

    def test_missing_key_in_locale_falls_back_to_en(self):
        svc = _create_i18n_service({
            "en": {"greeting": "Hello", "farewell": "Goodbye"},
            "it": {"greeting": "Ciao"},  # no "farewell" in Italian
        }, locale="it")
        # Italian has no "farewell" → falls back to English, not the raw key
        assert svc.get("farewell") == "Goodbye"

    def test_key_found_in_locale_does_not_fallback(self):
        svc = _create_i18n_service({
            "en": {"greeting": "Hello"},
            "it": {"greeting": "Ciao"},
        }, locale="it")
        assert svc.get("greeting") == "Ciao"

    def test_key_missing_everywhere_returns_key(self):
        svc = _create_i18n_service({"en": {}, "it": {}}, locale="it")
        assert svc.get("nowhere") == "nowhere"

    def test_for_language_uses_the_instance_ui_locale_and_language(self):
        from dataclasses import replace
        from tests.helpers import TEST_LANGUAGE

        svc = I18nService.for_language(replace(TEST_LANGUAGE, ui_locale="it", name="Latin"))

        assert svc.locale == "it"
        assert svc.language_name == "Latin"


# ===================================================================
# String formatting with kwargs
# ===================================================================
class TestStringFormatting:

    def test_format_with_kwargs(self):
        svc = _create_i18n_service({
            "en": {"welcome": "Hello {name}!"}
        })
        assert svc.get("welcome", name="Noor") == "Hello Noor!"

    def test_format_with_multiple_kwargs(self):
        svc = _create_i18n_service({
            "en": {"stats": "{count} cards in {days} days"}
        })
        result = svc.get("stats", count=50, days=7)
        assert result == "50 cards in 7 days"

    def test_language_placeholders_come_from_the_instance(self):
        svc = _create_i18n_service({"en": {"x": "Learn {language} ({language_lower})"}}, language_name="Latin")
        assert svc.get("x") == "Learn Latin (latin)"

    def test_missing_kwarg_returns_unformatted(self):
        """If a kwarg is missing, return the raw template (don't crash)."""
        svc = _create_i18n_service({
            "en": {"welcome": "Hello {name}!"}
        })
        result = svc.get("welcome")  # no name kwarg
        assert result == "Hello {name}!"


# ===================================================================
# Edge cases
# ===================================================================
class TestEdgeCases:

    def test_empty_locales_dir(self):
        tmpdir = tempfile.mkdtemp()  # empty dir
        svc = I18nService(locale="en", language_name="Italian", locales_dir=tmpdir)
        assert svc.get("anything") == "anything"

    def test_nonexistent_locales_dir(self):
        svc = I18nService(locale="en", language_name="Italian", locales_dir="/nonexistent/path")
        assert svc.get("anything") == "anything"

    def test_non_string_value_returned_as_is(self):
        """If a key maps to a list or dict, return it without formatting."""
        svc = _create_i18n_service({
            "en": {"levels": ["A1", "A2", "B1"]}
        })
        result = svc.get("levels")
        assert result == ["A1", "A2", "B1"]
