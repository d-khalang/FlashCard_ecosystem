import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from flashcard.utils.asyncio_errors import install_asyncio_exception_handler


class TestInstallAsyncioExceptionHandler:

    async def test_logs_unhandled_task_exception_and_notifies_admin(self):
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        mock_logger = MagicMock()
        mock_logger_bot = MagicMock()

        try:
            with (
                patch("flashcard.utils.asyncio_errors.logger", mock_logger),
                patch("flashcard.utils.asyncio_errors.notify_admin_with_trace", new_callable=AsyncMock) as mock_notify,
            ):
                install_asyncio_exception_handler(logger_bot=mock_logger_bot)
                handler = loop.get_exception_handler()

                err = RuntimeError("boom")
                handler(
                    loop,
                    {
                        "message": "Task exception was never retrieved",
                        "exception": err,
                        "future": "dummy-future",
                    },
                )
                await asyncio.sleep(0)

                mock_logger.error.assert_called_once()
                logged_message = mock_logger.error.call_args[0][0]
                assert "Asyncio background task error" in logged_message
                assert "Task exception was never retrieved" in logged_message
                assert "dummy-future" in logged_message
                mock_notify.assert_awaited_once()
                assert "RuntimeError: boom" in mock_notify.await_args.kwargs["text"]
        finally:
            loop.set_exception_handler(previous_handler)

    async def test_ignores_cancelled_error(self):
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        mock_logger = MagicMock()
        mock_logger_bot = MagicMock()

        try:
            with (
                patch("flashcard.utils.asyncio_errors.logger", mock_logger),
                patch("flashcard.utils.asyncio_errors.notify_admin_with_trace", new_callable=AsyncMock) as mock_notify,
            ):
                install_asyncio_exception_handler(logger_bot=mock_logger_bot)
                handler = loop.get_exception_handler()

                handler(
                    loop,
                    {
                        "message": "Task exception was never retrieved",
                        "exception": asyncio.CancelledError(),
                    },
                )
                await asyncio.sleep(0)

                mock_logger.error.assert_not_called()
                mock_notify.assert_not_called()
        finally:
            loop.set_exception_handler(previous_handler)

    async def test_skips_notify_when_loop_is_closed(self):
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        mock_logger = MagicMock()
        mock_logger_bot = MagicMock()

        class _ClosedLoop:
            def is_closed(self):
                return True

            def create_task(self, _coro):
                raise AssertionError("create_task must not be called on closed loop")

        try:
            with (
                patch("flashcard.utils.asyncio_errors.logger", mock_logger),
                patch("flashcard.utils.asyncio_errors.notify_admin_with_trace", new_callable=AsyncMock) as mock_notify,
            ):
                install_asyncio_exception_handler(logger_bot=mock_logger_bot)
                handler = loop.get_exception_handler()

                handler(
                    _ClosedLoop(),
                    {
                        "message": "Task exception was never retrieved",
                        "exception": RuntimeError("boom"),
                    },
                )

                mock_notify.assert_not_called()
                mock_logger.warning.assert_called_once()
                assert "event loop is closed" in mock_logger.warning.call_args[0][0]
        finally:
            loop.set_exception_handler(previous_handler)

    async def test_logs_warning_when_create_task_fails(self):
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        mock_logger = MagicMock()
        mock_logger_bot = MagicMock()

        class _FailingLoop:
            def is_closed(self):
                return False

            def create_task(self, _coro):
                raise RuntimeError("Event loop is closed")

        try:
            with (
                patch("flashcard.utils.asyncio_errors.logger", mock_logger),
                patch("flashcard.utils.asyncio_errors.notify_admin_with_trace", new_callable=AsyncMock),
            ):
                install_asyncio_exception_handler(logger_bot=mock_logger_bot)
                handler = loop.get_exception_handler()

                handler(
                    _FailingLoop(),
                    {
                        "message": "Task exception was never retrieved",
                        "exception": RuntimeError("boom"),
                    },
                )

                mock_logger.warning.assert_called_once()
                assert "failed to schedule task" in mock_logger.warning.call_args[0][0]
        finally:
            loop.set_exception_handler(previous_handler)
