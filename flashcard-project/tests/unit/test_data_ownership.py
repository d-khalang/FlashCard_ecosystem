"""
Contract: each collection is written only by its owners (docs/bot-architecture-refactor.md).

`users` field groups: profile/settings/onboarding/last_seen_at (UserService),
consumption (ConsumptionService), review state (ReviewStateStore).
"""
import ast
from pathlib import Path

import flashcard

SRC = Path(flashcard.__file__).parent
WRITE_METHODS = {"insert_one", "insert_many", "update_one", "update_many", "replace_one",
                 "delete_one", "delete_many", "find_one_and_update", "find_one_and_replace",
                 "find_one_and_delete", "bulk_write"}
USERS_WRITERS = {"services/user.py", "services/consumption.py", "services/review_state.py"}
# One-off migrations read users directly; they are removed after the rollout.
USERS_READERS = USERS_WRITERS | {"migrations/backfill_created_at.py", "migrations/backfill_current_review.py"}


def _files_writing(collection: str) -> set[str]:
    found = set()
    for path in SRC.rglob("*.py"):
        for call in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr in WRITE_METHODS
                    and f"'{collection}'" in ast.unparse(call.func.value)):
                found.add(path.relative_to(SRC).as_posix())
    return found


def _files_accessing(collection: str) -> set[str]:
    """Any read or write through `...['<collection>']`."""
    return {path.relative_to(SRC).as_posix() for path in SRC.rglob("*.py")
            if f"['{collection}']" in "".join(ast.unparse(node) for node in ast.walk(
                ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.Subscript))}


def test_only_owners_write_users():
    assert _files_writing("users") == USERS_WRITERS


def test_only_owners_read_users():
    """Other code asks an owner (e.g. pass review_mode in) instead of reading users itself."""
    assert _files_accessing("users") == USERS_READERS
