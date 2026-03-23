"""
Unit tests for Telegram bot wiring.
"""
from unittest.mock import patch

from flashcard.telegram.bot import build_bot_dispatcher, get_allowed_updates


class TestAllowedUpdates:
    def test_includes_inline_query_after_router_registration(self):
        with patch("flashcard.telegram.bot.settings.BOT_TOKEN", "123456:test-token"):
            bot, dp = build_bot_dispatcher()

        try:
            allowed_updates = get_allowed_updates(dp)
        finally:
            # Avoid leaking an unclosed aiohttp session in tests.
            import asyncio

            asyncio.run(bot.session.close())

        assert "inline_query" in allowed_updates
        assert "callback_query" in allowed_updates
        assert "message" in allowed_updates
