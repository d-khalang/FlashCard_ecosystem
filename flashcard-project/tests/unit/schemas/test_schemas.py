"""
Unit tests for Pydantic schemas and language normalization.

Tests:
  - ExpressionCard, ExpressionDB defaults
  - UserDB defaults and consumption model
  - Language normalization (aliases, codes, unknown)
  - Helper functions (get_language_flag, get_language_name)
"""
import pytest
from pydantic import ValidationError

from flashcard.schemas.expression import ExpressionCard, ExpressionDB, ExpressionStats
from flashcard.schemas.user import UserDB, UserConsumption, LLMUsage
from flashcard.schemas.languages import (
    normalize_language_input,
    get_language_flag,
    get_language_name,
    LANGUAGE_DATA,
)


# ===================================================================
# ExpressionCard
# ===================================================================
class TestExpressionCard:

    def test_valid_success_card(self):
        card = ExpressionCard(
            success=True,
            norm="parlare",
            def_it="Comunicare a voce",
            translations=[{"label": "🇬🇧 EN", "text": "to speak"}],
            example_it="Parliamo italiano.",
            note_it=None,
            suggestions=[],
        )
        assert card.success is True
        assert card.norm == "parlare"

    def test_valid_failure_card(self):
        card = ExpressionCard(
            success=False,
            norm="",
            def_it=None,
            translations=[],
            example_it=None,
            note_it="Parola non chiara",
            suggestions=["parlare", "parlato"],
        )
        assert card.success is False
        assert len(card.suggestions) == 2


# ===================================================================
# ExpressionDB
# ===================================================================
class TestExpressionDB:

    def test_defaults(self):
        doc = ExpressionDB(
            user_id="123",
            value="casa",
            created_at="2026-01-01T00:00:00Z",
        )
        assert doc.reps == 0
        assert doc.lapses == 0
        assert doc.success_streak == 0
        assert doc.ewma_grade == 0.0
        assert doc.last_grade == 0
        assert doc.reverse_stats is None
        assert doc.status == "active"
        assert doc.pending_message_id is None

    def test_with_reverse_stats(self):
        doc = ExpressionDB(
            user_id="123",
            value="casa",
            created_at="2026-01-01T00:00:00Z",
            reverse_stats=ExpressionStats(reps=3, ewma_grade=3.5),
        )
        assert doc.reverse_stats is not None
        assert doc.reverse_stats.reps == 3
        assert doc.reverse_stats.ewma_grade == 3.5

    def test_model_dump_contains_all_srs_fields(self):
        """model_dump() should include all SRS-relevant keys."""
        doc = ExpressionDB(
            user_id="123", value="test", created_at="2026-01-01T00:00:00Z"
        )
        dump = doc.model_dump()
        for field in ["reps", "lapses", "success_streak", "ewma_grade", "status"]:
            assert field in dump, f"Missing field: {field}" 

    def test_expression_stats_defaults(self):
        """ExpressionStats (used for reverse_stats) should have safe defaults."""
        stats = ExpressionStats()
        assert stats.reps == 0
        assert stats.lapses == 0
        assert stats.success_streak == 0
        assert stats.ewma_grade == 0.0


# ===================================================================
# UserDB
# ===================================================================
class TestUserDB:

    def test_defaults(self):
        user = UserDB(user_id="123")
        assert user.is_active is True
        assert user.primary_language == "en"
        assert user.target_level == "A2"
        assert user.review_mode == "standard"
        assert user.review_interval_minutes == 30
        assert user.api_config is None

    def test_consumption_defaults(self):
        user = UserDB(user_id="123")
        assert isinstance(user.consumption, UserConsumption)
        assert user.consumption.system_api.cards_generated == 0
        assert user.consumption.verb_lookups == 0

    def test_model_dump_shape(self):
        user = UserDB(user_id="123")
        dump = user.model_dump()
        assert "user_id" in dump
        assert "consumption" in dump
        assert "system_api" in dump["consumption"]


# ===================================================================
# Language normalization
# ===================================================================
class TestLanguageNormalization:

    @pytest.mark.parametrize("raw, expected", [
        ("en", "en"),       # lowercase code
        ("EN", "en"),       # uppercase code
        ("Farsi", "fa"),    # alias
        ("persian", "fa"),  # alias variant
        ("english", "en"),  # full name
        ("eng", "en"),      # abbreviation
    ])
    def test_normalizes_valid_input(self, raw, expected):
        assert normalize_language_input(raw) == expected

    def test_unknown_language_raises(self):
        with pytest.raises(ValueError, match="Unsupported language"):
            normalize_language_input("klingon")

    def test_none_allowed_accepts_none_string(self):
        result = normalize_language_input("none", none_allowed=True)
        assert result == "none"

    def test_none_not_allowed_rejects_none_string(self):
        with pytest.raises(ValueError):
            normalize_language_input("none", none_allowed=False)


# ===================================================================
# Language helper functions
# ===================================================================
class TestLanguageHelpers:

    def test_get_flag_known_language(self):
        assert get_language_flag("it") == "🇮🇹"
        assert get_language_flag("fa") == "🇮🇷"

    def test_get_flag_unknown_language(self):
        assert get_language_flag("xx") == "🌍"

    def test_get_flag_none(self):
        assert get_language_flag(None) == "🌍"

    def test_get_name_known(self):
        assert get_language_name("it") == "Italian"
        assert get_language_name("en") == "English"

    def test_get_name_unknown(self):
        assert get_language_name("xx") == "XX"
