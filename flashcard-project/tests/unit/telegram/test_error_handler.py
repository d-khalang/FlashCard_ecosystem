from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from google.genai.errors import ServerError
from pymongo.errors import NetworkTimeout

from flashcard.telegram.handlers.errors import error_handler, _user_message_key


class _DummyMessage:
    def __init__(self, user_id: int):
        self.from_user = SimpleNamespace(id=user_id)
        self.answer = AsyncMock()


class TestUserMessageKey:
    """Unit tests for the exception → i18n mapping helper."""

    def test_gemini_error_maps_to_llm_key(self):
        exc = ServerError(503, {"error": {"message": "overloaded"}})
        assert _user_message_key(exc) == "messages.errors.llm_unavailable"

    def test_pymongo_error_maps_to_db_key(self):
        exc = NetworkTimeout("timed out")
        assert _user_message_key(exc) == "messages.errors.db_unavailable"

    def test_unknown_error_maps_to_generic_key(self):
        exc = RuntimeError("boom")
        assert _user_message_key(exc) == "messages.errors.service_unavailable"


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

    async def test_llm_error_sends_llm_specific_message(self):
        message = _DummyMessage(user_id=789)
        exc = ServerError(503, {"error": {"message": "overloaded"}})
        event = SimpleNamespace(
            exception=exc,
            update=SimpleNamespace(
                message=message,
                callback_query=None,
                event_type="message",
            ),
        )
        logger_bot = MagicMock()

        with (
            patch("flashcard.utils.logger.notify_admin_with_trace", new_callable=AsyncMock),
            patch("flashcard.telegram.handlers.errors.i18n.get", return_value="AI overloaded") as mock_i18n,
        ):
            result = await error_handler(event, logger_bot=logger_bot)

        assert result is True
        mock_i18n.assert_called_with("messages.errors.llm_unavailable")
        message.answer.assert_awaited_once_with("AI overloaded")

    async def test_db_error_sends_db_specific_message(self):
        message = _DummyMessage(user_id=321)
        exc = NetworkTimeout("connection timed out")
        event = SimpleNamespace(
            exception=exc,
            update=SimpleNamespace(
                message=message,
                callback_query=None,
                event_type="message",
            ),
        )
        logger_bot = MagicMock()

        with (
            patch("flashcard.utils.logger.notify_admin_with_trace", new_callable=AsyncMock),
            patch("flashcard.telegram.handlers.errors.i18n.get", return_value="DB trouble") as mock_i18n,
        ):
            result = await error_handler(event, logger_bot=logger_bot)

        assert result is True
        mock_i18n.assert_called_with("messages.errors.db_unavailable")
        message.answer.assert_awaited_once_with("DB trouble")
