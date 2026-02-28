"""
Unit tests for flashcard.services.algorithm.grading.calculate_new_stats

Tests the SRS grading engine that updates expression stats after a user
rates a flashcard. This is a pure function — no I/O, no mocking needed.
"""
from unittest.mock import patch

from flashcard.services.algorithm.grading import (
    calculate_new_stats,
    ALPHA,
    PASS_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------
def _empty_stats() -> dict:
    """Baseline stats representing a brand-new expression (all zeros/None)."""
    return {
        "reps": 0,
        "lapses": 0,
        "success_streak": 0,
        "ewma_grade": 0.0,
        "last_grade": 0,
    }


def _experienced_stats() -> dict:
    """Stats for an expression that has been reviewed several times."""
    return {
        "reps": 5,
        "lapses": 1,
        "success_streak": 3,
        "ewma_grade": 3.5,
        "last_grade": 4,
    }


# ---------------------------------------------------------------------------
# Success / Failure classification
# ---------------------------------------------------------------------------
class TestGradeClassification:
    """Verify that grade >= PASS_THRESHOLD is treated as success."""

    def test_grade_at_threshold_is_success(self):
        result = calculate_new_stats(_empty_stats(), grade=PASS_THRESHOLD)
        assert result["reps"] == 1, "Grade at threshold should count as a successful rep"
        assert result["success_streak"] == 1

    def test_grade_above_threshold_is_success(self):
        result = calculate_new_stats(_empty_stats(), grade=5)
        assert result["reps"] == 1
        assert result["lapses"] == 0

    def test_grade_below_threshold_is_failure(self):
        result = calculate_new_stats(_empty_stats(), grade=PASS_THRESHOLD - 1)
        assert result["reps"] == 0, "Grade below threshold should NOT increment reps"
        assert result["lapses"] == 1
        assert result["success_streak"] == 0

    def test_grade_zero_is_failure(self):
        """Lowest possible grade should be a clean failure."""
        result = calculate_new_stats(_empty_stats(), grade=0)
        assert result["lapses"] == 1
        assert result["success_streak"] == 0

    def test_grade_five_is_success(self):
        """Highest possible grade should be a clean success."""
        result = calculate_new_stats(_empty_stats(), grade=5)
        assert result["reps"] == 1
        assert result["success_streak"] == 1
        assert result["lapses"] == 0


# ---------------------------------------------------------------------------
# Counter updates
# ---------------------------------------------------------------------------
class TestCounterUpdates:
    """Verify reps, lapses, and success_streak update correctly."""

    def test_success_increments_reps_and_streak(self):
        stats = _experienced_stats()  # reps=5, streak=3
        result = calculate_new_stats(stats, grade=4)

        assert result["reps"] == 6
        assert result["success_streak"] == 4
        assert result["lapses"] == stats["lapses"]  # unchanged

    def test_failure_increments_lapses_resets_streak(self):
        stats = _experienced_stats()  # lapses=1, streak=3
        result = calculate_new_stats(stats, grade=1)

        assert result["lapses"] == 2
        assert result["success_streak"] == 0
        assert result["reps"] == stats["reps"]  # unchanged

    def test_consecutive_failures_accumulate_lapses(self):
        stats = {"reps": 0, "lapses": 3, "success_streak": 0, "ewma_grade": 1.0, "last_grade": 1}
        result = calculate_new_stats(stats, grade=0)

        assert result["lapses"] == 4
        assert result["reps"] == 0

    def test_double_grading_accumulates(self):
        """Grading the output of a previous grading should accumulate correctly."""
        first_result = calculate_new_stats(_empty_stats(), grade=4)
        second_result = calculate_new_stats(first_result, grade=4)

        assert second_result["reps"] == 2
        assert second_result["success_streak"] == 2


# ---------------------------------------------------------------------------
# EWMA calculation
# ---------------------------------------------------------------------------
class TestEWMACalculation:
    """Verify the Exponentially Weighted Moving Average formula."""

    def test_ewma_from_zero(self):
        result = calculate_new_stats(_empty_stats(), grade=5)
        expected_ewma = round(ALPHA * 5 + (1 - ALPHA) * 0.0, 4)
        assert result["ewma_grade"] == expected_ewma

    def test_ewma_from_existing(self):
        stats = _experienced_stats()  # ewma=3.5
        grade = 4
        result = calculate_new_stats(stats, grade=grade)
        expected_ewma = round(ALPHA * grade + (1 - ALPHA) * 3.5, 4)
        assert result["ewma_grade"] == expected_ewma

    def test_ewma_zero_grade_pulls_down(self):
        stats = {"reps": 5, "lapses": 0, "success_streak": 5, "ewma_grade": 4.0, "last_grade": 5}
        result = calculate_new_stats(stats, grade=0)
        assert result["ewma_grade"] < 4.0, "Zero grade should pull EWMA down"


# ---------------------------------------------------------------------------
# last_grade tracking
# ---------------------------------------------------------------------------
class TestLastGrade:

    def test_last_grade_is_recorded(self):
        result = calculate_new_stats(_empty_stats(), grade=4)
        assert result["last_grade"] == 4


# ---------------------------------------------------------------------------
# Null / missing stats resilience
# ---------------------------------------------------------------------------
class TestNullSafety:
    """Stats from the DB might have None values — ensure no crashes."""

    def test_all_none_stats(self):
        stats = {
            "reps": None,
            "lapses": None,
            "success_streak": None,
            "ewma_grade": None,
            "last_grade": None,
        }
        result = calculate_new_stats(stats, grade=3)
        assert isinstance(result["reps"], int)
        assert isinstance(result["ewma_grade"], float)

    def test_empty_dict_stats(self):
        result = calculate_new_stats({}, grade=5)
        assert result["reps"] == 1
        assert result["success_streak"] == 1


# ---------------------------------------------------------------------------
# Forward vs Reverse direction
# ---------------------------------------------------------------------------
class TestDirection:
    """is_reverse flag controls which timestamp field is set."""

    @patch("flashcard.services.algorithm.grading.now_utc")
    def test_forward_sets_last_interaction_at(self, mock_now):
        from datetime import datetime, timezone
        mock_now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

        result = calculate_new_stats(_empty_stats(), grade=4, is_reverse=False)
        assert "last_interaction_at" in result
        assert "last_review_at" not in result

    @patch("flashcard.services.algorithm.grading.now_utc")
    def test_reverse_sets_last_review_at(self, mock_now):
        from datetime import datetime, timezone
        mock_now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)

        result = calculate_new_stats(_empty_stats(), grade=4, is_reverse=True)
        assert "last_review_at" in result
        assert "last_interaction_at" not in result
