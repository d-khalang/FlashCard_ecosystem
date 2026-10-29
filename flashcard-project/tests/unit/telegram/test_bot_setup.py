"""
Unit tests for Telegram bot wiring.
"""
from dataclasses import replace

from flashcard.telegram.bot import build_bot_dispatcher, get_allowed_updates
from flashcard.telegram.handlers import verb
from tests.helpers import TEST_LANGUAGE


class TestAllowedUpdates:
    def test_includes_inline_query_after_router_registration(self):
        bot, dp = build_bot_dispatcher("123456:test-token", TEST_LANGUAGE)

        try:
            allowed_updates = get_allowed_updates(dp)
        finally:
            # Avoid leaking an unclosed aiohttp session in tests.
            import asyncio

            asyncio.run(bot.session.close())

        assert "inline_query" in allowed_updates
        assert "callback_query" in allowed_updates
        assert "message" in allowed_updates

    def test_verb_router_not_registered_when_conjugation_disabled(self):
        bot, dp = build_bot_dispatcher("123456:test-token", replace(TEST_LANGUAGE, conjugation=False))

        try:
            routers = list(dp.sub_routers)
        finally:
            import asyncio

            asyncio.run(bot.session.close())

        assert verb.router not in routers

    def test_verb_router_registered_when_conjugation_enabled(self):
        bot, dp = build_bot_dispatcher("123456:test-token", replace(TEST_LANGUAGE, conjugation=True))

        try:
            routers = list(dp.sub_routers)
        finally:
            import asyncio

            asyncio.run(bot.session.close())

        assert verb.router in routers
