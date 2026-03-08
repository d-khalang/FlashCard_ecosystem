from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from flashcard.api.routes.webhook import webhook_handler
from flashcard.settings import settings


class _DummyRequest:
    def __init__(self, payload=None, json_error=None, state_values=None):
        self._payload = payload
        self._json_error = json_error
        self.app = SimpleNamespace(state=SimpleNamespace(**(state_values or {})))

    async def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class TestWebhookHandler:

    async def test_rejects_invalid_secret_token(self):
        request = _DummyRequest(payload={})

        with pytest.raises(HTTPException) as exc:
            await webhook_handler(request, x_telegram_bot_api_secret_token="wrong-secret")

        assert exc.value.status_code == 403

    async def test_returns_400_on_invalid_json_payload(self):
        request = _DummyRequest(json_error=ValueError("bad json"))

        with pytest.raises(HTTPException) as exc:
            await webhook_handler(request, x_telegram_bot_api_secret_token=settings.WEBHOOK_SECRET)

        assert exc.value.status_code == 400
        assert exc.value.detail == "Invalid JSON payload"

    async def test_returns_500_when_dispatcher_processing_fails(self):
        bot = MagicMock()
        logger_bot = MagicMock()
        dispatcher = SimpleNamespace(feed_update=AsyncMock(side_effect=RuntimeError("boom")))
        state = {
            "bot": bot,
            "dispatcher": dispatcher,
            "dispatcher_data": {"x": 1},
            "logger_bot": logger_bot,
        }
        request = _DummyRequest(payload={"update_id": 1}, state_values=state)

        with (
            patch("flashcard.api.routes.webhook.Update", return_value=MagicMock()) as mock_update,
            patch("flashcard.api.routes.webhook.notify_admin_with_trace", new_callable=AsyncMock) as mock_notify,
        ):
            with pytest.raises(HTTPException) as exc:
                await webhook_handler(request, x_telegram_bot_api_secret_token=settings.WEBHOOK_SECRET)

        assert exc.value.status_code == 500
        assert exc.value.detail == "Failed to process update"
        dispatcher.feed_update.assert_awaited_once_with(bot, mock_update.return_value, x=1)
        mock_notify.assert_awaited_once()

    async def test_returns_400_on_invalid_update_payload(self):
        bot = MagicMock()
        dispatcher = SimpleNamespace(feed_update=AsyncMock(return_value=None))
        state = {
            "bot": bot,
            "dispatcher": dispatcher,
            "dispatcher_data": {},
        }
        request = _DummyRequest(payload={"invalid": "update"}, state_values=state)

        with patch("flashcard.api.routes.webhook.Update", side_effect=ValueError("invalid update")):
            with pytest.raises(HTTPException) as exc:
                await webhook_handler(request, x_telegram_bot_api_secret_token=settings.WEBHOOK_SECRET)

        assert exc.value.status_code == 400
        assert exc.value.detail == "Invalid update payload"
        dispatcher.feed_update.assert_not_awaited()

    async def test_returns_ok_when_update_processed(self):
        bot = MagicMock()
        dispatcher = SimpleNamespace(feed_update=AsyncMock(return_value=None))
        state = {
            "bot": bot,
            "dispatcher": dispatcher,
            "dispatcher_data": {"x": 2},
        }
        request = _DummyRequest(payload={"update_id": 7}, state_values=state)

        with patch("flashcard.api.routes.webhook.Update", return_value=MagicMock()) as mock_update:
            response = await webhook_handler(
                request,
                x_telegram_bot_api_secret_token=settings.WEBHOOK_SECRET,
            )

        assert response == {"ok": True}
        dispatcher.feed_update.assert_awaited_once_with(bot, mock_update.return_value, x=2)
