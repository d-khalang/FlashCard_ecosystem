# Contributing Guide

How to extend the FlashCard Bot — adding commands, services, and following project conventions.

## Prerequisites

- Python 3.9+
- MongoDB (local or Atlas)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A logger bot token (separate bot for admin notifications)

## Local Setup

```bash
# Clone and enter repo
git clone https://github.com/your-org/FlashCard-ecosystem.git
cd FlashCard-ecosystem/flashcard-project

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux

# Install in editable mode
pip install -e .

# Copy and fill env vars
cp ../.env.example ../.env
# Edit ../.env with your values

# Run in dev polling mode
flashcard-bot-dev-poll
```

---

## Adding a New Command

Example: adding a `/quiz` command.

### 1. Create the handler file

```python
# src/flashcard/telegram/handlers/quiz.py
from aiogram import Router, flags
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ChatAction

from flashcard.services.expression import ExpressionService
from flashcard.services.i18n import i18n
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)
router = Router()


@router.message(Command("quiz"))
@flags.chat_action(ChatAction.TYPING)
async def cmd_quiz(message: Message, expression_service: ExpressionService):
    """Handle /quiz command."""
    user_id = message.from_user.id
    # Your logic here...
    await message.answer(i18n.get("commands.quiz.start"))
```

### 2. Add i18n strings

Add to [`resources/locales/en.json`](../src/flashcard/resources/locales/en.json):

```json
"commands": {
    "quiz": {
        "start": "Let's start a quiz! 🎯",
        "correct": "Correct! ✅",
        "wrong": "Not quite. The answer was: {answer}"
    }
}
```

### 3. Register the router

In [`bot.py`](../src/flashcard/telegram/bot.py), import and register:

```python
from flashcard.telegram.handlers import quiz

# Register BEFORE unknown.router (position 4 — Domain Features)
dp.include_router(quiz.router)  # /quiz
```

> [!WARNING]
> New command routers must be registered **before** `unknown.router`. Otherwise, the unknown command catch-all (`F.text.startswith("/")`) will intercept your command.

### 4. Add callback handlers (if needed)

If your command has inline keyboard buttons, add callback handlers in the same file:

```python
@router.callback_query(F.data.startswith("quiz_answer:"))
async def handle_quiz_answer(callback: CallbackQuery):
    answer = callback.data.split(":", 1)[1]
    # Process answer...
```

---

## Adding a New Service

### 1. Create the service class

```python
# src/flashcard/services/quiz.py
from flashcard.utils.logger import get_logger

logger = get_logger(__name__)

class QuizService:
    def __init__(self, cols: dict):
        self.cols = cols

    async def get_random_quiz(self, user_id: str):
        """Your business logic here."""
        ...
```

### 2. Wire it up in bot.py

In both `init_telegram_bot()` and `init_telegram_without_fastapi()`:

```python
quiz_service = QuizService(cols=cols)

# Pass to start_polling or dispatcher
dp.start_polling(bot, ..., quiz_service=quiz_service)
```

### 3. Use in handlers

```python
async def cmd_quiz(message: Message, quiz_service: QuizService):
    result = await quiz_service.get_random_quiz(str(message.from_user.id))
```

---

## Conventions

### Logging

Use the project logger, never `print()`:

```python
from flashcard.utils.logger import get_logger
logger = get_logger(__name__)

logger.info("Success: processed %d items", count)
logger.error(f"Failed for user {user_id}: {e}")
```

### Error Handling in Handlers

- **Catch and log** — don't let exceptions propagate silently
- **Notify admin** — for unexpected errors, send to `logger_bot`
- **User-friendly message** — show i18n error text, not stack traces
- **HTML escaping** — any dynamic content in bot messages must be escaped

```python
import html

try:
    result = await some_service.do_thing()
except Exception as e:
    logger.error(f"Error: {e}")
    error_text = html.escape(str(e)[:300])
    await logger_bot.send_message(settings.ADMIN_ID, f"Error: {error_text}")
    await message.answer(i18n.get("messages.errors.service_unavailable"))
    return
```

> [!CAUTION]
> The bot uses `ParseMode.HTML` globally. If error messages or user input contain `<` or `>` (e.g., MongoDB's `<TopologyDescription>`), they will break Telegram's parser. Always use `html.escape()` on dynamic content.

### i18n Keys

Follow the naming convention: `{layer}.{feature}.{key}`

```
commands.quiz.start           ✅ Good
quiz_start_message            ❌ Bad (no structure)
commands.quiz.startMessage    ❌ Bad (camelCase)
```

### File Organization

| Layer | Location | Naming |
|-------|----------|--------|
| Handler | `telegram/handlers/` | Domain-based: `quiz.py`, `review.py` |
| Service | `services/` | Domain-based: `quiz.py`, `expression.py` |
| Schema | `schemas/` | Model-based: `quiz.py`, `user.py` |
| UI Formatter | `telegram/ui/` | Domain-based: matches handler |
| Constants | `schemas/defaults.py` | Centralized |
| i18n | `resources/locales/en.json` | Single file per locale |

---

## Project Documentation

| Document | Purpose |
|----------|---------|
| [Architecture](./architecture.md) | System overview, data flows, package structure |
| [Services](./services.md) | Service layer API reference |
| [Handlers](./handlers.md) | Handler inventory, router order, UI layer |
| [Configuration](./configuration.md) | Env vars, defaults, Docker setup |
| This guide | How to contribute |
