"""
Contract: settings and i18n are injected, not imported (docs/bot-architecture-refactor.md, #7).

Only entry points load settings from the environment; everything else receives
what it needs from the composition root. A module-level settings global made
every import read the environment and froze values at import time.
"""
import ast
from pathlib import Path

import flashcard

SRC = Path(flashcard.__file__).parent
ENTRY_POINTS = {
    "__main__.py",
    "api/main.py",
    "migrations/backfill_created_at.py",
    "migrations/backfill_current_review.py",
    "migrations/dedupe_expressions.py",
    "migrations/convert_dates.py",
}


def _modules_importing_settings():
    for path in SRC.rglob("*.py"):
        module = path.relative_to(SRC).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module == "flashcard.settings":
                yield module
            elif (isinstance(node, ast.ImportFrom) and node.module == "flashcard"
                  and any(a.name == "settings" for a in node.names)):
                yield module
            elif isinstance(node, ast.Import) and any(a.name == "flashcard.settings" for a in node.names):
                yield module


def test_only_entry_points_load_settings():
    assert set(_modules_importing_settings()) - ENTRY_POINTS == set()


def test_settings_module_has_no_global_instance():
    import flashcard.settings as settings_module

    assert not hasattr(settings_module, "settings")


def test_i18n_is_built_only_by_the_composition_root():
    """Handlers, keyboards and the scheduler receive `i18n`; none builds or imports a shared one."""
    import flashcard.services.i18n as i18n_module

    assert not hasattr(i18n_module, "i18n")
    builders = set()
    for path in SRC.rglob("*.py"):
        module = path.relative_to(SRC).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and ast.unparse(node.func).startswith("I18nService"):
                builders.add(module)
    assert builders == {"composition.py"}
