"""
Unit tests for expression card and review message formatting.

Tests render_expression_card (success/failure paths)
and format_review_message (forward/reverse modes).
"""
from flashcard.schemas.expression import ExpressionCard
from flashcard.telegram.ui.expression import (
    render_expression_card,
    format_review_message,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_card(**overrides) -> ExpressionCard:
    """Create a standard success card."""
    base = {
        "success": True,
        "norm": "parlare",
        "learning_definition": "Comunicare a voce",
        "translations": [
            {"label": "🇬🇧 EN", "text": "to speak"},
            {"label": "🇮🇷 FA", "text": "صحبت کردن"},
        ],
        "learning_example": "Parliamo italiano ogni giorno.",
        "note": None,
        "suggestions": [],
    }
    base.update(overrides)
    return ExpressionCard(**base)


def _make_failure_card(**overrides) -> ExpressionCard:
    base = {
        "success": False,
        "norm": "",
        "learning_definition": None,
        "translations": [],
        "learning_example": None,
        "note": "Parola non chiara",
        "suggestions": ["parlare", "parlato"],
    }
    base.update(overrides)
    return ExpressionCard(**base)


# ===================================================================
# render_expression_card
# ===================================================================
class TestRenderExpressionCard:

    def test_success_card_contains_definition(self):
        result = render_expression_card(_make_card())

        assert result["success"] is True
        assert "Comunicare a voce" in result["content"]

    def test_success_card_contains_translations(self):
        result = render_expression_card(_make_card())

        assert "to speak" in result["content"]
        assert "🇬🇧 EN" in result["content"]

    def test_success_card_contains_example(self):
        result = render_expression_card(_make_card())
        assert "Parliamo italiano" in result["content"]

    def test_failure_card_returns_note(self):
        result = render_expression_card(_make_failure_card())

        assert result["success"] is False
        assert "Parola non chiara" in result["content"]

    def test_failure_card_without_note_uses_default(self):
        result = render_expression_card(_make_failure_card(note=None))
        assert "Expression not clear" in result["content"]

    def test_one_translation_doesnt_crash(self):
        card = _make_card(translations=[{"label": "🇬🇧 EN", "text": "to speak"}])
        result = render_expression_card(card)
        assert result["success"] is True
        assert "to speak" in result["content"]

    def test_no_translations_doesnt_crash(self):
        card = _make_card(translations=[])
        result = render_expression_card(card)
        assert result["success"] is True


# ===================================================================
# format_review_message
# ===================================================================
class TestFormatReviewMessage:

    def test_forward_shows_word_prominently(self):
        card = _make_card()
        msg = format_review_message(card, "parlare", direction="forward")

        assert "<b>parlare</b>" in msg
        assert "tg-spoiler" in msg

    def test_forward_hides_definition_in_spoiler(self):
        card = _make_card()
        msg = format_review_message(card, "parlare", direction="forward")

        # Definition should be inside spoiler
        spoiler_start = msg.index("<tg-spoiler>")
        spoiler_end = msg.index("</tg-spoiler>")
        spoiler_content = msg[spoiler_start:spoiler_end]

        assert "Comunicare a voce" in spoiler_content

    def test_reverse_shows_definition_prominently(self):
        card = _make_card()
        msg = format_review_message(card, "parlare", direction="reverse")

        assert "Reverse Review" in msg
        assert "Comunicare a voce" in msg

    def test_reverse_hides_word_in_spoiler(self):
        card = _make_card()
        msg = format_review_message(card, "parlare", direction="reverse")

        spoiler_start = msg.index("<tg-spoiler>")
        spoiler_end = msg.index("</tg-spoiler>")
        spoiler_content = msg[spoiler_start:spoiler_end]

        assert "parlare" in spoiler_content

    def test_missing_definition_uses_translation(self):
        """If learning_definition is None, reverse mode should fall back to translations."""
        card = _make_card(learning_definition=None)
        msg = format_review_message(card, "parlare", direction="reverse")

        assert "to speak" in msg  # falls back to translation
