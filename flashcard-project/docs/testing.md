# Testing

The FlashCard project uses **pytest** with **pytest-asyncio** for testing. The suite covers all major components: algorithms, services, schemas, Telegram UI, and infrastructure.

## Quick Start

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v --tb=short

# Run a specific file
pytest tests/unit/services/test_expression_service.py -v

# Run a specific test class
pytest tests/unit/algorithm/test_grading.py::TestEWMACalculation -v
```

## Test Structure

```
tests/
├── conftest.py                     # Env var setup (prevents settings.py crash)
├── helpers.py                      # Shared utilities (AsyncCursorMock)
├── __init__.py                     # Makes tests/ importable
│
├── unit/
│   ├── algorithm/                  # Pure function tests (no mocking)
│   │   ├── test_grading.py         # calculate_new_stats (17 tests)
│   │   └── test_priority.py        # calculate_priority, parse_iso (17 tests)
│   │
│   ├── services/                   # Business logic (mocked MongoDB)
│   │   ├── test_expression_service.py  # CRUD + review candidate (22 tests)
│   │   ├── test_verb_service.py        # Verb lookup + scraper (24 tests)
│   │   ├── test_user_service.py        # User CRUD + settings (18 tests)
│   │   ├── test_i18n_service.py        # Locale loading (13 tests)
│   │   ├── test_consumption_service.py # Daily quota tracking (10 tests)
│   │   └── test_llm_service.py         # Mocked genai (10 tests)
│   │
│   ├── schemas/                    # Pydantic models + language utils
│   │   └── test_schemas.py         # ExpressionDB, UserDB, language normalization (24 tests)
│   │
│   ├── telegram/                   # UI + keyboards (no real Telegram)
│   │   ├── test_creation_handler.py    # Creation input guards (1 test)
│   │   ├── test_keyboards.py           # Button counts, layouts, callbacks (14 tests)
│   │   ├── test_expression_card_ui.py  # Card rendering + review modes (12 tests)
│   │   ├── test_expression_ui.py       # Expression list formatting (8 tests)
│   │   ├── test_verb_ui.py             # Conjugation formatting (16 tests)
│   │   ├── test_story_and_callbacks.py # Story UI + callback factories (14 tests)
│   │   └── test_review_handler.py      # Callback timeout helper behavior (2 tests)
│   │
│   ├── scheduler/                  # Background job logic (mocked)
│   │   └── test_scheduler.py       # User filtering, metrics, scheduler tracing (9 tests)
│   │
│   └── utils/                      # Utilities
│       ├── test_tracing.py         # @observe + finalize_trace + TraceLogger (8 tests)
│       └── test_time_and_settings.py   # now_utc, iso_z, webhook_url (8 tests)
│
└── manual/                         # Debug scripts (not in pytest)
```

**Total: 243 tests** - all unit tests with mocked dependencies.

## Configuration

Testing configuration lives in [`pyproject.toml`](../pyproject.toml):

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src", "."]
asyncio_mode = "auto"
```

- **`pythonpath`**: `"src"` for `flashcard` imports, `"."` for `tests.helpers` imports
- **`asyncio_mode = "auto"`**: no need for `@pytest.mark.asyncio` decorators

## Key Patterns

### Mocked MongoDB

Services that depend on MongoDB use `MagicMock` / `AsyncMock` collections:

```python
def _make_service():
    mock_cols = {
        "users": MagicMock(),
        "expression": MagicMock(),
    }
    mock_cols["users"].find_one = AsyncMock(return_value=None)
    return ExpressionService(mock_cols), mock_cols
```

### Async Cursor Mock

For MongoDB `.find()` which returns an async cursor, use `AsyncCursorMock` from `tests/helpers.py`:

```python
from tests.helpers import AsyncCursorMock

cols["expression"].find = MagicMock(
    return_value=AsyncCursorMock([doc1, doc2])
)
```

### Parametrized Tests

Use `@pytest.mark.parametrize` to test multiple inputs with one function:

```python
@pytest.mark.parametrize("raw, expected", [
    ("EN", "en"),
    ("Farsi", "fa"),
    ("english", "en"),
])
def test_normalizes_valid_input(self, raw, expected):
    assert normalize_language_input(raw) == expected
```

### Temporary Files

Use pytest's `tmp_path` fixture for tests that write to disk:

```python
def test_logger_writes(self, tmp_path):
    logger = TraceLogger(log_dir=str(tmp_path))
    # writes to tmp_path/traces.jsonl — cleaned up automatically
```

## Conventions

- **File naming**: `test_{module_name}.py`
- **Class naming**: `Test{ComponentName}` — group by feature
- **Helper naming**: `_make_service()`, `_make_card()` — private helpers per file
- **No real I/O**: Never hit real DB, APIs, or Telegram in unit tests
- **Async**: Just write `async def test_...` — `asyncio_mode = "auto"` handles the rest
