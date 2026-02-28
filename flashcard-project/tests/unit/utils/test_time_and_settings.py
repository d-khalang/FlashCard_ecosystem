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
