"""
Unit tests for expression list formatting.

Tests format_expression_list: alphabetical grouping, plain mode,
no-sort mode, message splitting at 4000 chars, and empty list.
"""
from flashcard.telegram.ui.expression_lists import format_expression_list


# ===================================================================
# format_expression_list
# ===================================================================
class TestExpressionListFormatting:

    def test_empty_list_shows_onboarding_message(self):
        result = format_expression_list([])
        assert len(result) == 1
        assert "📚 Flashcard Collection" in result[0]
        assert "don't have any flashcards yet" in result[0]

    def test_default_mode_sorts_alphabetically(self):
        result = format_expression_list(["banana", "apple"])
        content = result[0]

        assert content.find("apple") < content.find("banana")

    def test_default_mode_adds_letter_headers(self):
        result = format_expression_list(["banana", "apple"])
        content = result[0]

        assert "<b>A</b>" in content
        assert "<b>B</b>" in content

    def test_plain_mode_no_fancy_elements(self):
        result = format_expression_list(["banana", "apple"], plain=True)
        content = result[0]

        # Still sorted
        assert content.find("apple") < content.find("banana")
        # No bold letter headers
        assert "<b>A</b>" not in content
        assert "apple\n" in content

    def test_no_sort_preserves_insertion_order(self):
        result = format_expression_list(
            ["banana", "apple"], sort_alphabetical=False
        )
        content = result[0]

        assert content.find("banana") < content.find("apple")
        # No letter grouping headers when unsorted
        assert "<b>B</b>" not in content

    def test_large_list_splits_at_4000_chars(self):
        expressions = [f"word_{i:04d}" for i in range(500)]
        result = format_expression_list(expressions)

        assert len(result) > 1
        total = "".join(result)
        assert "word_0000" in total
        assert "word_0499" in total

    def test_each_chunk_under_4100_chars(self):
        """No single message should exceed Telegram's ~4096 char limit."""
        expressions = [f"expression_{i:04d}" for i in range(500)]
        result = format_expression_list(expressions)

        for chunk in result:
            assert len(chunk) < 4100

    def test_item_count_in_header(self):
        result = format_expression_list(["a", "b", "c"])
        assert "3 items stored" in result[0]
