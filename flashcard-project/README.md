# Flashcard Bot

The core Python service for the FlashCard ecosystem — a Telegram bot for learning Italian with AI-generated flashcards and spaced repetition.

## Package Structure

```
src/flashcard/
├── api/            # FastAPI layer (webhook, health)
├── db/             # MongoDB connection
├── scheduler/      # Background review scheduler
├── schemas/        # Pydantic data models & defaults
├── services/       # Business logic (expression, user, verb, LLM, i18n)
├── telegram/       # aiogram bot (handlers, UI, keyboards, FSM states)
├── utils/          # Logger, time helpers
├── resources/      # i18n locale files
├── settings.py     # Environment configuration
└── __main__.py     # Entry points
```

For detailed architecture and data flow diagrams, see [docs/architecture.md](docs/architecture.md).

## Running Locally

### Prerequisites

- Python 3.9+
- MongoDB (local instance or Atlas)
- Bot tokens from [@BotFather](https://t.me/BotFather) (main bot + logger bot)

### Setup

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux

# Install in editable mode
pip install -e .

# Configure environment
cp ../.env.example ../.env
# Edit ../.env with your values (see docs/configuration.md for reference)
```

### Entry Points

| Command | Mode | Use Case |
|---------|------|----------|
| `flashcard-bot-dev-poll` | Polling + dev | **Recommended for local dev** |
| `flashcard-bot-dev` | Webhook + reload | Development with webhook |
| `flashcard-bot-poll` | Polling | Production polling |
| `flashcard-bot` | Webhook | Production webhook |

```bash
# Start in dev polling mode (no webhook needed)
flashcard-bot-dev-poll
```

## Running via Docker

From the repository root:

```bash
docker compose up --build flashcard-bot
```

The root [`docker-compose.yml`](../docker-compose.yml) builds and runs all services (bot, scraper, Caddy).

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | System architecture, data flows, router order |
| [Services](docs/services.md) | Service layer reference (methods, schemas, algorithm) |
| [Handlers](docs/handlers.md) | Handler inventory, DI, UI layer, i18n |
| [Configuration](docs/configuration.md) | All env vars, defaults, Docker |
| [Testing](docs/testing.md) | Test suite structure, patterns, conventions |
| [Contributing](docs/contributing.md) | How to add features, conventions |

## Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests (234 unit tests)
pytest tests/ -v --tb=short
```

See [docs/testing.md](docs/testing.md) for full details on test structure, mocking patterns, and conventions.

## Dependencies

Core dependencies (see [`pyproject.toml`](pyproject.toml) for versions):

- **aiogram** — Async Telegram bot framework
- **FastAPI + uvicorn** — HTTP server
- **pymongo** — MongoDB async driver
- **google-genai** — Google Gemini LLM client
- **httpx** — Async HTTP client
- **pydantic-settings** — Configuration management
