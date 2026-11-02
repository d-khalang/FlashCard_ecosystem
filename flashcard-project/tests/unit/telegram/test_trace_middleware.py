"""
Tests for TraceMiddleware's user recording: record_seen creates the user, so it must
finish before any handler runs, and its failure must not block the update.
"""
import asyncio
from unittest.mock import MagicMock

from flashcard.telegram.middlewares.trace_middleware import TraceMiddleware
from tests.integration.helpers import make_message_update


async def _run(user_service, handler):
    return await TraceMiddleware()(handler, make_message_update(text="/start"), {"user_service": user_service})


async def test_record_seen_finishes_before_the_handler_runs():
    order = []
    user_service = MagicMock()

    async def record_seen(user_id, username):
        await asyncio.sleep(0.01)  # a slow database must not let the handler run first
        order.append(("seen", user_id, username))

    async def handler(event, data):
        order.append("handler")

    user_service.record_seen = record_seen
    await _run(user_service, handler)

    assert order == [("seen", 42, "tester"), "handler"]


async def test_record_seen_failure_still_runs_the_handler(caplog):
    user_service = MagicMock()

    async def record_seen(*_):
        raise RuntimeError("mongo down")

    async def handler(event, data):
        return "handled"

    user_service.record_seen = record_seen

    assert await _run(user_service, handler) == "handled"
    assert "Could not record user 42 as seen" in caplog.text
