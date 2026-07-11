from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteWebhook,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    SetWebhook,
)
from aiogram.types import CallbackQuery, Chat, InlineQuery, Message, Update, User
from bson import ObjectId

from flashcard.schemas.expression import ExpressionCard
from flashcard.schemas.import_model import ImportResponse
from flashcard.schemas.story import StoryParagraph, StoryResponse
from flashcard.services.consumption import ConsumptionService
from flashcard.services.expression import ExpressionService
from flashcard.services.user import UserService
from flashcard.services.verb import VerbService


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _deepcopy_doc(doc: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(doc)


def _get_nested(doc: dict[str, Any], key: str) -> Any:
    value: Any = doc
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _set_nested(doc: dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    current = doc
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def _inc_nested(doc: dict[str, Any], key: str, delta: int) -> None:
    current = _get_nested(doc, key)
    if current is None:
        current = 0
    _set_nested(doc, key, current + delta)


def _match_condition(field_value: Any, condition: Any) -> bool:
    if isinstance(condition, dict):
        regex_flags = 0
        if "$options" in condition and "i" in str(condition["$options"]).lower():
            regex_flags |= re.IGNORECASE

        for op, expected in condition.items():
            if op == "$lt":
                if field_value is None or field_value >= expected:
                    return False
            elif op == "$exists":
                exists = field_value is not None
                if bool(expected) != exists:
                    return False
            elif op == "$regex":
                if field_value is None:
                    return False
                pattern = expected.pattern if hasattr(expected, "pattern") else str(expected)
                if re.search(pattern, str(field_value), flags=regex_flags) is None:
                    return False
            elif op == "$in":
                matched = False
                for item in expected:
                    if hasattr(item, "search"):
                        if item.search(str(field_value or "")):
                            matched = True
                            break
                    elif field_value == item:
                        matched = True
                        break
                if not matched:
                    return False
            elif op == "$options":
                continue
            else:
                raise NotImplementedError(f"Unsupported query operator: {op}")
        return True

    return field_value == condition


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, value in query.items():
        if key == "$or":
            if not any(_matches(doc, branch) for branch in value):
                return False
            continue
        if not _match_condition(_get_nested(doc, key), value):
            return False
    return True


class AsyncCursorMock:
    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = docs
        self._index = 0

    def sort(self, field: str, direction: int) -> "AsyncCursorMock":
        reverse = direction == -1
        self._docs.sort(key=lambda doc: _get_nested(doc, field), reverse=reverse)
        return self

    def __aiter__(self) -> "AsyncCursorMock":
        self._index = 0
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._index >= len(self._docs):
            raise StopAsyncIteration
        item = _deepcopy_doc(self._docs[self._index])
        self._index += 1
        return item


class InMemoryCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None):
        self.docs = [_deepcopy_doc(doc) for doc in (docs or [])]

    async def find_one(self, query: dict[str, Any], projection: dict[str, Any] | None = None) -> dict[str, Any] | None:
        for doc in self.docs:
            if _matches(doc, query):
                result = _deepcopy_doc(doc)
                if projection:
                    projected = {}
                    for key, include in projection.items():
                        if include:
                            value = _get_nested(result, key)
                            if value is not None:
                                _set_nested(projected, key, value)
                    return projected
                return result
        return None

    def find(self, query: dict[str, Any]) -> AsyncCursorMock:
        return AsyncCursorMock([_deepcopy_doc(doc) for doc in self.docs if _matches(doc, query)])

    async def distinct(self, field: str, query: dict[str, Any]) -> list[Any]:
        seen = []
        for doc in self.docs:
            if _matches(doc, query):
                value = _get_nested(doc, field)
                if value not in seen:
                    seen.append(value)
        return seen

    async def insert_one(self, doc: dict[str, Any]) -> SimpleNamespace:
        stored = _deepcopy_doc(doc)
        stored.setdefault("_id", ObjectId())
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def insert_many(self, docs: list[dict[str, Any]]) -> SimpleNamespace:
        ids = []
        for doc in docs:
            result = await self.insert_one(doc)
            ids.append(result.inserted_id)
        return SimpleNamespace(inserted_ids=ids)

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> SimpleNamespace:
        for doc in self.docs:
            if _matches(doc, query):
                for key, values in update.items():
                    if key == "$set":
                        for field, value in values.items():
                            _set_nested(doc, field, value)
                    elif key == "$inc":
                        for field, value in values.items():
                            _inc_nested(doc, field, value)
                    elif key == "$setOnInsert":
                        continue
                    else:
                        raise NotImplementedError(f"Unsupported update operator: {key}")
                return SimpleNamespace(modified_count=1, upserted_id=None, deleted_count=0)

        if not upsert:
            return SimpleNamespace(modified_count=0, upserted_id=None, deleted_count=0)

        new_doc = {}
        for key, value in query.items():
            if key.startswith("$"):
                continue
            _set_nested(new_doc, key, value)
        for key, values in update.items():
            if key == "$set":
                for field, value in values.items():
                    _set_nested(new_doc, field, value)
            elif key == "$inc":
                for field, value in values.items():
                    _set_nested(new_doc, field, value)
            elif key == "$setOnInsert":
                for field, value in values.items():
                    if _get_nested(new_doc, field) is None:
                        _set_nested(new_doc, field, value)
        new_doc.setdefault("_id", ObjectId())
        self.docs.append(new_doc)
        return SimpleNamespace(modified_count=0, upserted_id=new_doc["_id"], deleted_count=0)

    async def delete_one(self, query: dict[str, Any]) -> SimpleNamespace:
        for index, doc in enumerate(self.docs):
            if _matches(doc, query):
                self.docs.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    async def replace_one(self, query: dict[str, Any], replacement: dict[str, Any], upsert: bool = False) -> SimpleNamespace:
        for index, doc in enumerate(self.docs):
            if _matches(doc, query):
                new_doc = _deepcopy_doc(replacement)
                new_doc.setdefault("_id", doc.get("_id", ObjectId()))
                self.docs[index] = new_doc
                return SimpleNamespace(modified_count=1, upserted_id=None)
        if upsert:
            new_doc = _deepcopy_doc(replacement)
            new_doc.setdefault("_id", ObjectId())
            self.docs.append(new_doc)
            return SimpleNamespace(modified_count=0, upserted_id=new_doc["_id"])
        return SimpleNamespace(modified_count=0, upserted_id=None)


class InMemoryMongoClient:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.admin = self

    async def command(self, name: str) -> dict[str, Any]:
        if self.should_fail:
            raise RuntimeError("mongo unavailable")
        return {"ok": 1, "command": name}


class DummyTraceLogger:
    def __init__(self):
        self.logged: list[str] = []
        self.shutdown_called = False

    def log_trace_json(self, trace_json: str) -> None:
        self.logged.append(trace_json)

    def shutdown(self) -> None:
        self.shutdown_called = True


class FakeHTTPResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeHTTPClient:
    def __init__(self, response: FakeHTTPResponse):
        self.response = response
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def get(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, Any] | None = None) -> FakeHTTPResponse:
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        return self.response

    async def aclose(self) -> None:
        self.closed = True


class FakeLLMService:
    def __init__(self):
        self.raise_card_error = False
        self.raise_story_error = False
        self.card_calls: list[dict[str, Any]] = []
        self.story_calls: list[dict[str, Any]] = []
        self.import_calls: list[str] = []
        self.card = ExpressionCard(
            success=True,
            norm="andare",
            learning_definition="muoversi verso un luogo",
            translations=[
                {"label": "EN", "text": "to go"},
                {"label": "FA", "text": "رفتن"},
            ],
            learning_example="Vado a scuola ogni mattina.",
            note=None,
            suggestions=[],
        )

    async def generate_expression_card(self, **kwargs: Any) -> ExpressionCard:
        self.card_calls.append(kwargs)
        if self.raise_card_error:
            raise RuntimeError("LLM unavailable")
        return self.card

    async def generate_story(self, **kwargs: Any) -> StoryResponse:
        self.story_calls.append(kwargs)
        if self.raise_story_error:
            raise RuntimeError("story generation failed")
        return StoryResponse(
            paragraphs=[
                StoryParagraph(
                    learning_text="Andare al mercato e parlare con amici.",
                    translation="Go to the market and speak with friends.",
                ),
                StoryParagraph(
                    learning_text="Poi torno a casa felice.",
                    translation="Then I return home happy.",
                ),
            ]
        )

    async def parse_import_list(self, raw_text: str) -> ImportResponse:
        self.import_calls.append(raw_text)
        values = [part.strip() for part in raw_text.split(",") if part.strip()]
        return ImportResponse(success=True, import_list=values)


@dataclass
class TelegramCall:
    method: str
    payload: dict[str, Any]


class FakeTelegramSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[TelegramCall] = []
        self._message_id = 100

    async def close(self) -> None:
        return None

    async def stream_content(self, url: str, headers: dict[str, Any] | None = None, timeout: int = 30, chunk_size: int = 65536, raise_for_status: bool = True):
        if False:
            yield b""

    async def make_request(self, bot: Bot, method: Any, timeout: int | None = None) -> Any:
        payload = method.model_dump(exclude_none=True, warnings=False)
        self.calls.append(TelegramCall(method=method.__class__.__name__, payload=payload))

        if isinstance(method, SendMessage):
            return self._build_message(
                bot=bot,
                chat_id=method.chat_id,
                text=method.text,
                reply_markup=payload.get("reply_markup"),
            )
        if isinstance(method, EditMessageText):
            if method.inline_message_id:
                return True
            return self._build_message(
                bot=bot,
                chat_id=method.chat_id,
                text=method.text,
                reply_markup=payload.get("reply_markup"),
                message_id=method.message_id,
            )
        if isinstance(method, (EditMessageReplyMarkup, AnswerCallbackQuery, SetWebhook, DeleteWebhook)):
            return True
        raise NotImplementedError(f"FakeTelegramSession does not support {method.__class__.__name__}")

    def _build_message(
        self,
        *,
        bot: Bot,
        chat_id: int | str,
        text: str,
        reply_markup: Any = None,
        message_id: int | None = None,
    ) -> Message:
        if message_id is None:
            self._message_id += 1
            message_id = self._message_id

        data = {
            "message_id": message_id,
            "date": _utc_now(),
            "chat": {"id": int(chat_id), "type": "private"},
            "text": text,
        }
        if reply_markup is not None:
            data["reply_markup"] = reply_markup
        return Message.model_validate(data, context={"bot": bot})


def make_bot() -> tuple[Bot, FakeTelegramSession]:
    session = FakeTelegramSession()
    bot = Bot(token="123456:TEST", session=session)
    bot._me = User(id=1, is_bot=True, first_name="Kartino", username="kartino_test_bot")
    return bot, session


def make_message_update(
    *,
    text: str,
    user_id: int = 42,
    username: str = "tester",
    update_id: int = 1,
    message_id: int = 10,
) -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "message": {
                "message_id": message_id,
                "date": _utc_now(),
                "chat": {"id": user_id, "type": "private"},
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": "Test",
                    "username": username,
                },
                "text": text,
            },
        }
    )


def make_callback_update(
    *,
    data: str,
    text: str = "Existing message",
    user_id: int = 42,
    update_id: int = 2,
    message_id: int = 50,
) -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "callback_query": {
                "id": f"cq-{update_id}",
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": "Test",
                    "username": "tester",
                },
                "chat_instance": "ci-1",
                "data": data,
                "message": {
                    "message_id": message_id,
                    "date": _utc_now(),
                    "chat": {"id": user_id, "type": "private"},
                    "text": text,
                },
            },
        }
    )


def make_inline_query_update(
    *,
    query: str,
    user_id: int = 42,
    update_id: int = 3,
) -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "inline_query": {
                "id": f"iq-{update_id}",
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": "Test",
                    "username": "tester",
                },
                "query": query,
                "offset": "",
            },
        }
    )


def make_cols(*, users: list[dict[str, Any]] | None = None, expressions: list[dict[str, Any]] | None = None, conjugations: list[dict[str, Any]] | None = None) -> dict[str, InMemoryCollection]:
    return {
        "users": InMemoryCollection(users),
        "expression": InMemoryCollection(expressions),
        "conjugation": InMemoryCollection(conjugations),
    }


def make_services(cols: dict[str, InMemoryCollection], http_client: FakeHTTPClient | None = None) -> dict[str, Any]:
    expression_service = ExpressionService(cols=cols)
    consumption_service = ConsumptionService(cols=cols)
    user_service = UserService(cols=cols, consumption_service=consumption_service)
    verb_service = VerbService(cols=cols, http_client=http_client)
    return {
        "expression_service": expression_service,
        "user_service": user_service,
        "consumption_service": consumption_service,
        "verb_service": verb_service,
    }
