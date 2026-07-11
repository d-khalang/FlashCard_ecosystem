"""
Unit tests for time utilities and settings.

Tests:
  - now_utc: returns aware UTC datetime
  - iso_z: formats to ISO 8601 with Z suffix
  - Settings.webhook_url: property combining base + path
"""
from datetime import datetime, timezone

from flashcard.utils.time import now_utc, iso_z


# ===================================================================
# now_utc
# ===================================================================
class TestNowUtc:

    def test_returns_aware_datetime(self):
        result = now_utc()
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_is_utc(self):
        result = now_utc()
        assert result.tzinfo == timezone.utc

    def test_is_recent(self):
        """now_utc() should be within 1 second of datetime.now(UTC)."""
        before = datetime.now(timezone.utc)
        result = now_utc()
        after = datetime.now(timezone.utc)

        assert before <= result <= after


# ===================================================================
# iso_z
# ===================================================================
class TestIsoZ:

    def test_format_with_z_suffix(self):
        dt = datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = iso_z(dt)

        assert result == "2026-01-15T10:30:00Z"

    def test_naive_datetime_treated_as_utc(self):
        dt = datetime(2026, 6, 1, 12, 0, 0)  # no tzinfo
        result = iso_z(dt)

        assert result.endswith("Z")
        assert "2026-06-01T12:00:00Z" == result

    def test_seconds_precision(self):
        """Output should have seconds but no microseconds."""
        dt = datetime(2026, 1, 1, 0, 0, 0, 123456, tzinfo=timezone.utc)
        result = iso_z(dt)

        assert result == "2026-01-01T00:00:00Z"
        assert "." not in result  # no microseconds

    def test_round_trip(self):
        """iso_z output should be parseable back to a datetime."""
        original = now_utc()
        iso_str = iso_z(original)

        parsed = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        assert parsed.year == original.year
        assert parsed.minute == original.minute


# ===================================================================
# Settings.webhook_url property
# ===================================================================
class TestSettingsWebhookUrl:

    def test_combines_base_and_path(self):
        from flashcard.settings import settings

        url = settings.webhook_url

        # Should be a valid URL combining base + path
        assert url.startswith("http")
        assert "/" in url

    def test_no_double_slashes(self):
        """Base trailing slash + path leading slash should not produce '//'."""
        from flashcard.settings import settings

        url = settings.webhook_url
        # Remove protocol ://
        after_protocol = url.split("://", 1)[1]
        assert "//" not in after_protocol


class TestSettingsLanguageAndConjugation:
    def _base_settings_kwargs(self):
        return {
            "BOT_TOKEN": "123456:test-token",
            "LOGGER_BOT_TOKEN": "123456:test-logger",
            "ADMIN_ID": 0,
            "MONGO_URI": "mongodb://localhost:27017",
            "MONGO_DB": "test_db",
            "COLLECTION_USERS": "users",
            "COLLECTION_EXPRESSION": "expressions",
            "COLLECTION_CONJUGATION": "conjugations",
        }

    def test_language_defaults_are_italian(self):
        from flashcard.settings import Settings

        settings = Settings(
            **self._base_settings_kwargs(),
            SCRAPER_API_KEY="key",
            SCRAPER_URL="http://conjugator",
            SCRAPER_PORT=8000,
        )

        assert settings.LEARNING_LANGUAGE_CODE == "it"
        assert settings.LEARNING_LANGUAGE_NAME == "Italian"
        assert settings.DEFAULT_PRIMARY_LANGUAGE == "en"
        assert settings.ENABLE_CONJUGATION is True

    def test_conjugation_disabled_does_not_require_scraper_settings(self):
        from flashcard.settings import Settings

        settings = Settings(
            **self._base_settings_kwargs(),
            ENABLE_CONJUGATION=False,
            SCRAPER_API_KEY=None,
            SCRAPER_URL=None,
            SCRAPER_PORT=None,
        )

        assert settings.ENABLE_CONJUGATION is False
        assert settings.SCRAPER_URL is None

    def test_empty_optional_language_settings_are_normalized_to_none(self):
        from flashcard.settings import Settings

        settings = Settings(
            **self._base_settings_kwargs(),
            ENABLE_CONJUGATION=False,
            DEFAULT_SECONDARY_LANGUAGE="",
            SCRAPER_API_KEY="",
            SCRAPER_URL="   ",
            SCRAPER_PORT=None,
        )

        assert settings.DEFAULT_SECONDARY_LANGUAGE is None
        assert settings.SCRAPER_API_KEY is None
        assert settings.SCRAPER_URL is None

    def test_conjugation_enabled_requires_scraper_settings(self):
        from flashcard.settings import Settings

        import pytest

        with pytest.raises(ValueError, match="Conjugation is enabled"):
            Settings(
                **self._base_settings_kwargs(),
                SCRAPER_API_KEY=None,
                SCRAPER_URL=None,
                SCRAPER_PORT=None,
            )
