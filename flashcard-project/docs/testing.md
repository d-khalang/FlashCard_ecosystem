# Testing

The FlashCard project uses **pytest** with **pytest-asyncio** for testing. The suite covers all major components: algorithms, services, schemas, Telegram UI, FastAPI routes, and infrastructure.

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

## Integration and Smoke Layers

The automated suite now also includes:

- `tests/integration/` - dispatcher, lifecycle, and runtime wiring tests using an in-memory DB plus fake Telegram and HTTP clients
- `tests/smoke/` - ecosystem-level checks for Compose, Caddy, CI, docs, and the static web entrypoint

Common commands:

```bash
# Bot integration + smoke
pytest tests/integration tests/smoke -v --tb=short
```

When adding new runtime tests, prefer the shared harness in `tests/integration/helpers.py` so dispatcher flows use the same fake Telegram session and in-memory Mongo behavior.

## Test Structure

```
tests/
├── conftest.py                     # Env var setup & autouse router state fixtures
├── helpers.py                      # Shared unit test utilities (AsyncCursorMock)
├── __init__.py                     # Makes tests/ importable
│
├── unit/                           # Mocked unit tests
│   ├── api/                        # API layer tests
│   │   ├── test_health.py          # Deep health check + MongoDB ping
│   │   └── test_webhook_route.py   # Webhook security + failure paths
│   │
│   ├── algorithm/                  # Pure function tests (no mocking)
│   │   ├── test_grading.py         # calculate_new_stats
│   │   └── test_priority.py        # calculate_priority, parse_iso
│   │
│   ├── services/                   # Business logic (mocked MongoDB)
│   │   ├── test_expression_service.py  # CRUD + review candidate
│   │   ├── test_verb_service.py        # Verb lookup + scraper cache
│   │   ├── test_user_service.py        # User CRUD + settings FSM
│   │   ├── test_i18n_service.py        # Locale loading & dot-notation keys
│   │   ├── test_consumption_service.py # Daily quota tracking & resolution
│   │   ├── test_user_quota.py          # Daily resets in local generation checks
│   │   └── test_llm_service.py         # Multi-provider + fallback + schemas
│   │
│   ├── schemas/                    # Pydantic models + language normalization
│   │   └── test_schemas.py         # ExpressionDB, UserDB, language normalization
│   │
│   ├── telegram/                   # UI + keyboards (no real Telegram)
│   │   ├── test_bot_setup.py           # Dependency registration
│   │   ├── test_collection_handler.py  # Collection CRUD handlers
│   │   ├── test_creation_handler.py    # Creation input guards
│   │   ├── test_error_handler.py       # Global error handler + exception mapping
│   │   ├── test_keyboards.py           # Button counts, layouts, callback data
│   │   ├── test_expression_card_ui.py  # Card rendering + standard/reverse modes
│   │   ├── test_expression_ui.py       # Expression list formatting and chunking
│   │   ├── test_inline_remove_handler.py # Inline card removal & callbacks
│   │   ├── test_verb_ui.py             # Conjugation table formatting
│   │   ├── test_story_and_callbacks.py # Story UI + callback factories
│   │   └── test_review_handler.py      # Callback timeout helper behavior
│   │
│   ├── scheduler/                  # Background job logic (mocked)
│   │   └── test_scheduler.py       # User filtering, metrics, scheduler tracing
│   │
│   └── utils/                      # General utilities
│       ├── test_tracing.py         # @observe + finalize_trace + TraceLogger
│       └── test_time_and_settings.py   # now_utc, iso_z, webhook_url
│
├── integration/                    # Dispatcher & runtime wiring integration tests
│   ├── conftest.py                 # Integration environment setup
│   ├── helpers.py                  # Integration test harness & fake Telegram session
│   ├── test_dispatcher_runtime.py  # Telegram message routing integration
│   └── test_lifecycle_runtime.py   # Full app lifespan & service wiring integration
│
├── smoke/                          # System-level ecosystem smoke checks
│   └── test_ecosystem_wiring.py    # Compose, Caddy, static assets validation
│
└── manual/                         # Debug scripts (not in pytest)
```

**Total: 413 tests** - combining unit, integration, and smoke layers.

## Resilience-Focused Tests

The following tests cover failure modes added for webhook and background-task robustness:

- `tests/unit/api/test_health.py`
  - Deep health check with MongoDB ping
  - Service unavailability detection (`503`)
- `tests/unit/api/test_webhook_route.py`
  - Secret-token rejection (`403`)
  - Invalid JSON / invalid update payload handling (`400`)
  - Dispatcher failure behavior (`500`) with admin alert attempt
- `tests/unit/telegram/test_error_handler.py`
  - Centralized mapping of `GeminiAPIError` and `PyMongoError` to specific i18n keys
  - Global error handler completion contract (`return True`)
  - Admin notification failure containment
- `tests/unit/utils/test_asyncio_errors.py`
  - Unhandled background task exception logging
  - Shutdown-safe behavior when loop is closed or task scheduling fails

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
