"""The maintenance stand-in bot: one note for everything, no database, the real bot's webhook."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from flashcard.maintenance import NOTE_KEY, create_app
from flashcard.services.i18n import I18nService
from flashcard.settings import Settings
from tests.integration.helpers import (
    make_bot,
    make_callback_update,
    make_inline_query_update,
    make_message_update,
)

SECRET = "maintenance-secret"


def _settings(mode: str) -> Settings:
    # MONGO_URI points nowhere: the stand-in must never need the database.
    return Settings(
        BOT_TOKEN="123456:TEST", LOGGER_BOT_TOKEN="123456:TEST", ADMIN_ID=1,
        MONGO_URI="mongodb://127.0.0.1:1/never", MONGO_DB="x",
        COLLECTION_USERS="u", COLLECTION_EXPRESSION="e", COLLECTION_CONJUGATION="c",
        TELEGRAM_DELIVERY_MODE=mode, WEBHOOK_BASE="https://bot.example.org",
        WEBHOOK_PATH="/webhook/telegram/path", WEBHOOK_SECRET=SECRET, UI_LOCALE="en",
    )


def _post(client: TestClient, update, secret: str = SECRET):
    return client.post("/webhook/telegram/path", json=update.model_dump(mode="json", exclude_none=True),
                       headers={"X-Telegram-Bot-Api-Secret-Token": secret})


def test_every_update_gets_the_maintenance_note_and_the_webhook_stays():
    bot, session = make_bot()
    note = I18nService(locale="en", language_name="Italian").get(NOTE_KEY)
    assert note != NOTE_KEY and "maintenance" in note

    with TestClient(create_app(_settings("webhook"), bot=bot)) as client:
        assert client.get("/health/ready").json()["mode"] == "maintenance"
        assert _post(client, make_message_update(text="/get")).status_code == 200
        assert _post(client, make_callback_update(data="grade:abc:3:fwd")).status_code == 200
        assert _post(client, make_inline_query_update(query="cas")).status_code == 200

    calls = [(call.method, call.payload) for call in session.calls]
    methods = [method for method, _ in calls]
    # The same webhook the real bot uses, and it is not removed on stop.
    assert methods[0] == "SetWebhook"
    assert calls[0][1]["url"] == "https://bot.example.org/webhook/telegram/path"
    assert calls[0][1]["secret_token"] == SECRET
    assert "DeleteWebhook" not in methods
    assert ("SendMessage", note) in [(m, p.get("text")) for m, p in calls]
    alert = next(p for m, p in calls if m == "AnswerCallbackQuery")
    assert alert["text"] == note[:200] and alert["show_alert"] is True
    assert next(p for m, p in calls if m == "AnswerInlineQuery")["results"] == []


def test_a_wrong_secret_is_refused():
    bot, session = make_bot()
    with TestClient(create_app(_settings("webhook"), bot=bot)) as client:
        assert _post(client, make_message_update(text="hi"), secret="wrong").status_code == 403
    assert "SendMessage" not in [call.method for call in session.calls]


def test_a_polling_bot_takes_no_webhook_updates():
    bot, session = make_bot()
    app = create_app(_settings("polling"), bot=bot)
    # Polling itself is aiogram's; only the start and the closed webhook route are ours.
    app.router.lifespan_context = _no_lifespan
    with TestClient(app) as client:
        assert _post(client, make_message_update(text="hi")).status_code == 403



@asynccontextmanager
async def _no_lifespan(app):
    yield
