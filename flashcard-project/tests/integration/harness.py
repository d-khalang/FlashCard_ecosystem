"""
The bot and the Mini App API in one process, over one test database and one fake Telegram.

Everything the bot or the API sends to Telegram is recorded on `session.calls`; nothing leaves the
machine. The LLM, the speech provider and the conjugation scraper are fakes. Use it for flows that
cross both surfaces, e.g. a card the bot sent, graded in the app.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
from aiogram import Bot, Dispatcher
from fastapi import FastAPI

from .helpers import FakeTelegramSession, make_callback_update, make_message_update
from .study_helpers import FakeStudyLLM, auth_header

USER = 42


class FakeSpeech:
    """Stands in for the text-to-speech provider; returns recognisable bytes and records each call."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, text: str, voice: str) -> bytes:
        self.calls.append((text, voice))
        return b"mp3:" + text.encode()


@dataclass
class Harness:
    bot: Bot
    session: FakeTelegramSession
    dp: Dispatcher
    handler_data: dict
    app: FastAPI
    api: httpx.AsyncClient
    cols: dict
    llm: FakeStudyLLM
    speech: FakeSpeech
    _update_id: int = field(default=1000)

    # --- the bot side -------------------------------------------------------------------------
    async def send(self, text: str, user_id: int = USER) -> None:
        """The user types `text` in the bot chat."""
        self._update_id += 1
        update = make_message_update(text=text, user_id=user_id, update_id=self._update_id,
                                     message_id=self._update_id)
        await self.dp.feed_update(self.bot, update, **self.handler_data)

    async def tap(self, data: str, message_id: int, user_id: int = USER) -> None:
        """The user taps an inline button carrying `data` on the bot message `message_id`."""
        self._update_id += 1
        update = make_callback_update(data=data, user_id=user_id, update_id=self._update_id,
                                      message_id=message_id)
        await self.dp.feed_update(self.bot, update, **self.handler_data)

    def calls(self, method: str) -> list[dict[str, Any]]:
        """Payloads of the Telegram calls named `method` (e.g. "SendMessage"), oldest first."""
        return [call.payload for call in self.session.calls if call.method == method]

    # --- the Mini App side --------------------------------------------------------------------
    async def get(self, path: str, user_id: int = USER) -> httpx.Response:
        return await self.api.get(f"/api/v1{path}", headers=auth_header(user_id))

    async def post(self, path: str, body: dict | None = None, user_id: int = USER) -> httpx.Response:
        return await self.api.post(f"/api/v1{path}", json=body or {}, headers=auth_header(user_id))

    async def idle(self) -> None:
        """Wait for the Mini App's background updates of bot messages (instead of sleeping)."""
        await self.app.state.bot_buttons.wait_idle()
