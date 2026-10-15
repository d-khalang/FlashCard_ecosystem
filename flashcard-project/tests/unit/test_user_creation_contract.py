"""
Contract: users are created in one place, and every entry point triggers it.

`UserService.record_seen` is the only writer that creates user documents (it sets
`created_at`, the trial start). Every other writer updates existing users only, so
each entry point must call `record_seen` before any handler runs:

- Telegram: TraceMiddleware on `dp.update` (tested here and in test_trace_middleware.py).
- Mini App (not built yet): its auth/launch step must call `record_seen`; add its test here.
"""
import ast
from pathlib import Path

import flashcard
from flashcard.telegram.bot import build_bot_dispatcher
from flashcard.telegram.middlewares.trace_middleware import TraceMiddleware

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
    _, dp = build_bot_dispatcher()

    assert any(isinstance(middleware, TraceMiddleware) for middleware in dp.update.middleware)
