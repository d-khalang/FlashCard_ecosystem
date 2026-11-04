"""
Helpers for the Mini App tests against a real MongoDB: a fake LLM, signed init data, seeding.

Nothing here calls a real LLM provider.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlencode

from bson import ObjectId

from flashcard.schemas.expression import CardSection, ExpressionCard, TranslationLine

BOT_TOKEN = os.environ["BOT_TOKEN"]  # set by tests/conftest.py unless the environment sets it, as CI does

LONG_AGO = datetime(2020, 1, 1, tzinfo=timezone.utc)


def make_card(norm: str = "andare", **overrides) -> ExpressionCard:
    fields = dict(
        success=True, norm=norm, learning_definition="muoversi verso un luogo",
        translations=[TranslationLine(label="🇬🇧 EN", text="to go"), TranslationLine(label="🇮🇷 FA", text="رفتن")],
        learning_example="Vado a scuola ogni mattina.", note=None, suggestions=[],
    )
    fields.update(overrides)
    return ExpressionCard(**fields)


class FakeStudyLLM:
    """The LLMService methods the Mini App uses, counting calls and optionally failing or waiting."""

    def __init__(self):
        self.card_calls = 0
        self.section_calls: list[str] = []
        self.fail_cards = False
        self.fail_sections = False
        self.card_delay = 0.0
        # Words the LLM cannot make sense of (it answers success=False for them).
        self.unclear: set[str] = set()
        self.card = make_card()
        # Called with the section name while a section is being generated (to race a grade in).
        self.during_section: Optional[Callable[[str], Awaitable[None]]] = None
        self.section = CardSection(
            definition="spostarsi da un posto a un altro", translations=[], example="Domani andiamo al mare.")
        self.translations = [TranslationLine(label="🇬🇧 EN", text="to head"),
                             TranslationLine(label="🇮🇷 FA", text="رفتن")]

    async def generate_expression_card(self, **kwargs: Any) -> ExpressionCard:
        self.card_calls += 1
        if self.card_delay:
            await asyncio.sleep(self.card_delay)
        if self.fail_cards:
            raise RuntimeError("LLM unavailable")
        if kwargs.get("raw") in self.unclear:
            return ExpressionCard(success=False, norm=kwargs["raw"], learning_definition=None, translations=[],
                                  learning_example=None, note="not clear", suggestions=["x"])
        return self.card.model_copy(update={"norm": kwargs.get("raw", self.card.norm)})

    async def generate_card_section(self, section: str, **kwargs: Any) -> CardSection:
        self.section_calls.append(section)
        if self.during_section is not None:
            await self.during_section(section)
        if self.fail_sections:
            raise RuntimeError("LLM unavailable")
        if section == "translations":
            return CardSection(definition=None, translations=self.translations, example=None)
        return self.section

    async def parse_import_list(self, raw_text: str):
        from flashcard.schemas.import_model import ImportResponse
        values = [part.strip() for part in raw_text.split(",") if part.strip()]
        return ImportResponse(success=True, import_list=values)


def sign_init_data(user_id: int, *, bot_token: str = BOT_TOKEN, auth_age_seconds: int = 0,
                   username: str = "tester", extra: Optional[dict] = None, user: Optional[str] = None,
                   allows_write_to_pm: Optional[bool] = None) -> str:
    """Telegram-format initData signed with `bot_token`."""
    profile = {"id": user_id, "first_name": "T", "username": username}
    if allows_write_to_pm is not None:
        profile["allows_write_to_pm"] = allows_write_to_pm
    fields = {
        "auth_date": str(int(time.time()) - auth_age_seconds),
        "user": user if user is not None else json.dumps(profile, separators=(",", ":")),
        "query_id": "AAH",
        **(extra or {}),
    }
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def auth_header(user_id: int, **kwargs) -> dict:
    return {"Authorization": "tma " + sign_init_data(user_id, **kwargs)}


async def add_user(cols: dict, user_id: int, **fields) -> None:
    """A stored user (as record_seen would have made it)."""
    await cols["users"].insert_one({"user_id": str(user_id), "is_active": True, "created_at": LONG_AGO,
                                    "last_seen_at": datetime.now(timezone.utc), **fields})


async def add_word(cols: dict, user_id: int, value: str, *, age_days: int = 3, **fields) -> str:
    """An active word whose cooldown is over (never interacted, created `age_days` ago)."""
    expression_id = ObjectId()
    await cols["expression"].insert_one({
        "_id": expression_id, "user_id": str(user_id), "value": value, "status": "active",
        "created_at": datetime.now(timezone.utc) - timedelta(days=age_days), **fields,
    })
    return str(expression_id)
