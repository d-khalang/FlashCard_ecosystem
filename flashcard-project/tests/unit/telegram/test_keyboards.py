"""
Unit tests for keyboard builders.

Tests the structure and callback data of all keyboard functions.
We verify button count, layout rows, and callback data format
without needing a running Telegram bot.
"""
from bson import ObjectId

from flashcard.telegram.keyboards import (
    expression_action_kb,
    get_review_keyboard,
    get_level_selection_keyboard,
    get_interval_settings_keyboard,
)
from flashcard.telegram.ui.factories.grade_callback import GradeCallback


# ===================================================================
# expression_action_kb
# ===================================================================
class TestExpressionActionKeyboard:

    def test_has_save_and_regenerate_buttons(self):
        kb = expression_action_kb("parlare")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        texts = [b.text for b in buttons]

        assert len(buttons) == 2
        assert any("save" in t.lower() or "💾" in t for t in texts)

    def test_callback_data_contains_expression(self):
        kb = expression_action_kb("parlare")
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]

        assert "save:parlare" in callbacks
        assert "regen:parlare" in callbacks


# ===================================================================
# get_review_keyboard
# ===================================================================
class TestReviewKeyboard:

    def test_has_grades_0_through_5(self):
        kb = get_review_keyboard("abc123")
        buttons = [btn for row in kb.inline_keyboard for btn in row]

        # Should have 6 buttons: 0, 1, 2, 3, 4, 5
        assert len(buttons) == 6

    def test_layout_is_1_4_1(self):
        """Row 1: grade 0, Row 2: grades 1-4, Row 3: grade 5."""
        kb = get_review_keyboard("abc123")

        assert len(kb.inline_keyboard) == 3
        assert len(kb.inline_keyboard[0]) == 1  # "0 - I had no idea"
        assert len(kb.inline_keyboard[1]) == 4  # 1, 2, 3, 4
        assert len(kb.inline_keyboard[2]) == 1  # "5 - Known like family"

    def test_forward_direction_encoded(self):
        kb = get_review_keyboard("abc123", direction="forward")
        first_btn = kb.inline_keyboard[0][0]

        # Callback should contain direction code "fwd"
        assert "fwd" in first_btn.callback_data

    def test_reverse_direction_encoded(self):
        kb = get_review_keyboard("abc123", direction="reverse")
        first_btn = kb.inline_keyboard[0][0]

        assert "rev" in first_btn.callback_data

    def test_callback_data_is_parseable(self):
        """Callback data should be parseable back into a GradeCallback."""
        kb = get_review_keyboard("expr_id_123", direction="forward")
        raw = kb.inline_keyboard[0][0].callback_data

        parsed = GradeCallback.unpack(raw)
        assert parsed.expression_id == "expr_id_123"
        assert parsed.grade == 0
        assert parsed.direction == "fwd"


# ===================================================================
# get_level_selection_keyboard
# ===================================================================
class TestLevelSelectionKeyboard:

    def test_has_six_levels_plus_back(self):
        kb = get_level_selection_keyboard()
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        assert len(buttons) == 7  # A1, A2, B1, B2, C1, C2, Back

    def test_current_level_has_checkmark(self):
        kb = get_level_selection_keyboard(current_level="B1")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        texts = [b.text for b in buttons]

        assert any("B1" in t and "✅" in t for t in texts)
        # Other levels should NOT have checkmark
        assert not any("A1" in t and "✅" in t for t in texts)

    def test_layout_is_3_3_1(self):
        kb = get_level_selection_keyboard()
        assert len(kb.inline_keyboard) == 3
        assert len(kb.inline_keyboard[0]) == 3  # A1, A2, B1
        assert len(kb.inline_keyboard[1]) == 3  # B2, C1, C2
        assert len(kb.inline_keyboard[2]) == 1  # Back


# ===================================================================
# get_interval_settings_keyboard
# ===================================================================
class TestIntervalSettingsKeyboard:

    def test_has_four_intervals_plus_back(self):
        kb = get_interval_settings_keyboard()
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        assert len(buttons) == 5  # 30, 60, 90, 120, Back

    def test_current_interval_has_checkmark(self):
        kb = get_interval_settings_keyboard(current_minutes=60)
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        texts = [b.text for b in buttons]

        assert any("60" in t and "✅" in t for t in texts)
        assert not any("30" in t and "✅" in t for t in texts)

    def test_layout_is_2_2_1(self):
        kb = get_interval_settings_keyboard()
        assert len(kb.inline_keyboard) == 3
        assert len(kb.inline_keyboard[0]) == 2
        assert len(kb.inline_keyboard[1]) == 2
        assert len(kb.inline_keyboard[2]) == 1  # Back
