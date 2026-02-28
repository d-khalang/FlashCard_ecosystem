"""
Unit tests for flashcard.services.algorithm.priority

Tests the review-candidate scoring algorithm:
  - parse_iso() — ISO timestamp parsing
  - hours_since() — time delta helper
  - calculate_priority() — the full priority formula

These are pure functions. We mock `random.random` and
`datetime.now` for deterministic results.
"""
import random
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from flashcard.services.algorithm.priority import (
    parse_iso,
    hours_since,
    calculate_priority,
)

UTC = timezone.utc

# A fixed "now" for deterministic tests
FIXED_NOW = datetime(2026, 2, 27, 12, 0, 0, tzinfo=UTC)


# ===================================================================
# parse_iso
# ===================================================================
class TestParseISO:
    """parse_iso converts ISO-8601 strings to aware datetimes."""

    def test_z_suffix(self):
        result = parse_iso("2026-01-15T10:30:00Z")
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.tzinfo is not None

    def test_offset_suffix(self):
        result = parse_iso("2026-01-15T10:30:00+00:00")
        assert result is not None
        assert result.tzinfo is not None

    def test_naive_timestamp_gets_utc(self):
        result = parse_iso("2026-01-15T10:30:00")
        assert result is not None
        assert result.tzinfo is not None, "Naive datetimes should be coerced to UTC"

    def test_none_returns_none(self):
        assert parse_iso(None) is None

    def test_empty_string_returns_none(self):
        assert parse_iso("") is None

    def test_invalid_string_returns_none(self):
        assert parse_iso("not-a-date") is None


# ===================================================================
# hours_since
# ===================================================================
class TestHoursSince:
    """hours_since calculates hours between a datetime and now."""

    def test_none_returns_zero(self):
        assert hours_since(None) == 0.0

    @patch("flashcard.services.algorithm.priority.datetime")
    def test_one_hour_ago(self, mock_dt):
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        one_hour_ago = FIXED_NOW - timedelta(hours=1)
        result = hours_since(one_hour_ago)
        assert abs(result - 1.0) < 0.01

    @patch("flashcard.services.algorithm.priority.datetime")
    def test_negative_diff_clamped_to_zero(self, mock_dt):
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        future = FIXED_NOW + timedelta(hours=1)
        result = hours_since(future)
        assert result == 0.0, "Future timestamps should clamp to 0"


# ===================================================================
# calculate_priority
# ===================================================================
class TestCalculatePriority:
    """
    Priority formula:
      0.40 * recency +
      0.35 * difficulty +
      0.10 * stability +
      0.05 * novelty +
      0.05 * lapses +
      random(0, 0.08)
    """

    def _make_stats(self, **overrides) -> dict:
        """Create a stats dict with sensible defaults, overriding as needed."""
        base = {
            "last_interaction_at": None,
            "created_at": None,
            "ewma_grade": 0.0,
            "success_streak": 0,
            "lapses": 0,
            "reps": 0,
        }
        base.update(overrides)
        return base

    @patch("flashcard.services.algorithm.priority.random")
    def test_new_card_has_novelty_bonus(self, mock_random_mod):
        """A card with reps=0 should get the Novelty bonus (0.05)."""
        mock_random_mod.random.return_value = 0.0  # eliminate randomness

        new_card = self._make_stats(reps=0)
        reviewed_card = self._make_stats(reps=1)

        priority_new = calculate_priority(new_card)
        priority_reviewed = calculate_priority(reviewed_card)

        assert priority_new > priority_reviewed, "New card should have higher priority"

    @patch("flashcard.services.algorithm.priority.random")
    def test_low_ewma_means_high_priority(self, mock_random_mod):
        """Low EWMA (grade 0) → Difficulty is high → higher priority."""
        mock_random_mod.random.return_value = 0.0

        hard_card = self._make_stats(ewma_grade=0, reps=5)
        easy_card = self._make_stats(ewma_grade=5, reps=5)

        priority_hard = calculate_priority(hard_card)
        priority_easy = calculate_priority(easy_card)

        assert priority_hard > priority_easy

    @patch("flashcard.services.algorithm.priority.random")
    def test_high_streak_lowers_priority(self, mock_random_mod):
        """Long success streak → stable card → lower priority."""
        mock_random_mod.random.return_value = 0.0

        low_streak = self._make_stats(success_streak=0, reps=10, lapses=10)
        high_streak = self._make_stats(success_streak=8, reps=10, lapses=2)

        assert calculate_priority(low_streak) > calculate_priority(high_streak)

    @patch("flashcard.services.algorithm.priority.random")
    def test_lapses_increase_priority(self, mock_random_mod):
        """More lapses → card keeps being forgotten → higher priority."""
        mock_random_mod.random.return_value = 0.0

        no_lapses = self._make_stats(lapses=0, reps=5)
        many_lapses = self._make_stats(lapses=5, reps=5)

        assert calculate_priority(many_lapses) > calculate_priority(no_lapses)

    @patch("flashcard.services.algorithm.priority.random")
    def test_lapses_capped_at_five(self, mock_random_mod):
        """Lapses beyond 5 should NOT increase priority further."""
        mock_random_mod.random.return_value = 0.0

        five_lapses = self._make_stats(lapses=5, reps=5)
        hundred_lapses = self._make_stats(lapses=100, reps=5)

        assert calculate_priority(five_lapses) == calculate_priority(hundred_lapses)

    @patch("flashcard.services.algorithm.priority.random")
    def test_missing_timestamps_dont_crash(self, mock_random_mod):
        """All timestamps None — should still return a valid float."""
        mock_random_mod.random.return_value = 0.0

        stats = self._make_stats()  # all None
        result = calculate_priority(stats)

        assert isinstance(result, float)
        assert result >= 0

    @patch("flashcard.services.algorithm.priority.random")
    def test_returns_float_in_valid_range(self, mock_random_mod):
        """Priority should be a float between 0 and ~1.08."""
        mock_random_mod.random.return_value = 0.04  # mid-range randomness

        stats = self._make_stats(
            ewma_grade=2.5,
            success_streak=2,
            lapses=1,
            reps=3,
        )
        result = calculate_priority(stats)

        assert isinstance(result, float)
        assert 0 <= result <= 1.5  # generous upper bound

    @patch("flashcard.services.algorithm.priority.random")
    def test_randomness_adds_jitter(self, mock_random_mod):
        """Two identical calls with different random values → different scores."""
        stats = self._make_stats(reps=3, ewma_grade=2.0)

        mock_random_mod.random.return_value = 0.0
        p1 = calculate_priority(stats)

        mock_random_mod.random.return_value = 1.0  # max → 0.08 jitter
        p2 = calculate_priority(stats)

        assert abs(p2 - p1 - 0.08) < 0.001, "Max jitter should be 0.08"
