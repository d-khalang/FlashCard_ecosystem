from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from flashcard.telegram.handlers.errors import error_handler


class _DummyMessage:
    def __init__(self, user_id: int):
        self.from_user = SimpleNamespace(id=user_id)
        self.answer = AsyncMock()


class TestErrorHandler:

    async def test_returns_true_and_notifies_user_on_message_update(self):
        message = _DummyMessage(user_id=123)
        event = SimpleNamespace(
            exception=RuntimeError("boom"),
            update=SimpleNamespace(
                message=message,
                callback_query=None,
                event_type="message",
            ),
        )
        logger_bot = MagicMock()

        with (
            patch("flashcard.utils.logger.notify_admin_with_trace", new_callable=AsyncMock) as mock_notify,
            patch("flashcard.telegram.handlers.errors.i18n.get", return_value="Service unavailable"),
        ):
            result = await error_handler(event, logger_bot=logger_bot, trace_id="trace-1")

        assert result is True
        message.answer.assert_awaited_once_with("Service unavailable")
        mock_notify.assert_awaited_once()

    async def test_admin_notify_failure_does_not_break_handler(self):
        message = _DummyMessage(user_id=456)
        event = SimpleNamespace(
            exception=RuntimeError("boom"),
            update=SimpleNamespace(
                message=message,
                callback_query=None,
                event_type="message",
            ),
        )
        logger_bot = MagicMock()

        with (
            patch("flashcard.utils.logger.notify_admin_with_trace", new_callable=AsyncMock, side_effect=RuntimeError("net down")),
            patch("flashcard.telegram.handlers.errors.i18n.get", return_value="Service unavailable"),
        ):
            result = await error_handler(event, logger_bot=logger_bot, trace_id="trace-2")

        assert result is True
        message.answer.assert_awaited_once_with("Service unavailable")
