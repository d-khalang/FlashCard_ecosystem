"""
Contract: users are created in one place, and every entry point triggers it.

`UserService.record_seen` is the only writer that creates user documents (it sets
`created_at`, the trial start). Every other writer updates existing users only, so
each entry point must call `record_seen` before any handler runs:

- Telegram: TraceMiddleware on `dp.update` (tested here and in test_trace_middleware.py).
- Mini App: its sign-in dependency (`miniapp/routes/deps.py: authenticated_user`) calls `record_seen`.
"""
import ast
from pathlib import Path

import flashcard
from flashcard.telegram.bot import build_bot_dispatcher
from flashcard.telegram.middlewares.trace_middleware import TraceMiddleware
from tests.helpers import TEST_LANGUAGE

SRC = Path(flashcard.__file__).parent
ALLOWED_USER_CREATORS = {("services/user.py", "record_seen")}


def _user_upserts():
    """(file, function) of every `...users...(..., upsert=True)` call in the package."""
    found = set()
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(func):
                if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                    continue
                upsert = any(kw.arg == "upsert" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False)
                             for kw in call.keywords)
                if upsert and "users" in ast.unparse(call.func.value):
                    found.add((path.relative_to(SRC).as_posix(), func.name))
    return found


def test_only_record_seen_creates_users():
    assert _user_upserts() == ALLOWED_USER_CREATORS


def test_telegram_entry_point_records_the_user_first():
    _, dp = build_bot_dispatcher("123456:test-token", TEST_LANGUAGE)

    assert any(isinstance(middleware, TraceMiddleware) for middleware in dp.update.middleware)


async def test_miniapp_sign_in_records_the_user_before_any_route_runs():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import httpx
    from httpx import ASGITransport

    from flashcard.app.study import CurrentState
    from flashcard.miniapp.api import create_app
    from flashcard.settings import get_setting
    from tests.integration.study_helpers import auth_header

    order = []
    app = create_app(get_setting())
    app.state.core = SimpleNamespace(
        user_service=SimpleNamespace(record_seen=AsyncMock(side_effect=lambda *a: order.append("seen"))),
        study_use_cases=SimpleNamespace(current=AsyncMock(
            side_effect=lambda *a: order.append("route") or CurrentState(card=None, undo_available=False))),
    )

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/api/v1/study/current", headers=auth_header(42, username="noor"))

    assert order == ["seen", "route"]
    app.state.core.user_service.record_seen.assert_awaited_once_with(42, "noor", False)


def test_the_miniapp_creates_no_users_itself():
    miniapp = {file for file, _ in _user_upserts() if file.startswith("miniapp/")}

    assert miniapp == set()
