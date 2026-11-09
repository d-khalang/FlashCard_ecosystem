"""
Unit tests for the bot's credit texts: the /settings line and the limit message.
"""
from flashcard.app.quota import QuotaExceeded, Usage
from flashcard.telegram.helpers.credits import credits_exceeded_text, credits_line
from tests.helpers import TEST_I18N as i18n


class TestCreditsLine:

    def test_shows_credits_left_of_the_limit(self):
        assert credits_line(i18n, Usage(used=6, limit=20)) == i18n.get(
            "commands.settings.menu.credits", left=14, limit=20, card_cost=2)

    def test_never_shows_a_negative_count(self):
        assert "<b>0 of 20</b>" in credits_line(i18n, Usage(used=21, limit=20))

    def test_says_unlimited_when_nothing_limits_the_user(self):
        assert credits_line(i18n, Usage(used=5, limit=None)) == i18n.get(
            "commands.settings.menu.credits_unlimited", card_cost=2)

    def test_is_hidden_without_usage(self):
        assert credits_line(i18n, None) is None


class TestCreditsExceeded:

    def test_names_the_daily_credits_and_the_card_cost(self):
        assert credits_exceeded_text(i18n, QuotaExceeded(tier="normal", limit=20)) == i18n.get(
            "messages.errors.credits_exceeded", limit=20, card_cost=2)
