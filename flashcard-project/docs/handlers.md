# Handlers Guide

This document covers the Telegram bot's handler layer — how commands, callbacks, and messages are processed.

## Handler Inventory

Each handler module is a self-contained [aiogram Router](https://docs.aiogram.dev/en/latest/dispatcher/router.html) with its own command/callback registrations.

| Module | Commands / Triggers | Type | Description |
|--------|-------------------|------|-------------|
| [`user_settings.py`](../src/flashcard/telegram/handlers/user_settings.py) | `/settings` + FSM states | Command + FSM | Language, level, interval settings wizard |
| [`feedback.py`](../src/flashcard/telegram/handlers/feedback.py) | `/feedback` + FSM states | Command + FSM | User feedback collection |
| [`reply_commands.py`](../src/flashcard/telegram/handlers/reply_commands.py) | Reply keyboard text | Message filter | Maps reply keyboard buttons to commands |
| [`start.py`](../src/flashcard/telegram/handlers/start.py) | `/start`, `/help` | Commands | Welcome message, help text |
| [`review.py`](../src/flashcard/telegram/handlers/review.py) | `/get` + `grade:*` callbacks | Command + Callback | Review card delivery and grading |
| [`verb.py`](../src/flashcard/telegram/handlers/verb.py) | `/verb` + `VerbCallback` | Command + Callback | Verb conjugation lookup |
| [`story.py`](../src/flashcard/telegram/handlers/story.py) | `/story` | Command | Story generation from user's words |
| [`collection.py`](../src/flashcard/telegram/handlers/collection.py) | `/import`, `/list_my_flashcards` | Commands | Bulk import and collection listing |
| [`unknown.py`](../src/flashcard/telegram/handlers/unknown.py) | `F.text.startswith("/")` | Message filter | Catches unrecognized `/commands` |
| [`creation.py`](../src/flashcard/telegram/handlers/creation.py) | `F.text` + `save:*`, `regen:*` callbacks | Message + Callback | New flashcard creation from plain text |
| [`errors.py`](../src/flashcard/telegram/handlers/errors.py) | Unhandled errors | Error handler | Global error catch-all |

## Router Registration Order

Routers are registered in [`bot.py`](../src/flashcard/telegram/bot.py) in strict priority order. **The first matching handler wins.**

```python
# 1. Settings & Feedback (FSM states — highest priority)
dp.include_router(user_settings.router)
dp.include_router(feedback.router)

# 2. Reply Commands (text → command mapping)
dp.include_router(reply_commands.router)

# 3. Domain Features (specific commands)
dp.include_router(start.router)       # /start, /help
dp.include_router(review.router)      # /get + grade callbacks
dp.include_router(verb.router)        # /verb + conjugation callbacks
dp.include_router(story.router)       # /story
dp.include_router(collection.router)  # /import, /list_my_flashcards

# 4. Unknown Commands (catch-all for unrecognized /commands)
dp.include_router(unknown.router)

# 5. Content Creation (broadest text catch-all)
dp.include_router(creation.router)

# 6. Errors (last resort)
dp.include_router(errors.router)
```

> [!IMPORTANT]
> **Order matters.** The `unknown` router uses `F.text.startswith("/")` which matches ANY slash-prefixed text. It MUST come after all domain command routers (3) so they get first chance to match. Similarly, `creation` uses `F.text` which matches ALL text messages — it must come after `unknown`.

## Dependency Injection

aiogram injects services into handler functions by matching parameter names. Services are passed to the dispatcher in `bot.py`:

```python
dp.start_polling(
    bot,
    expression_service=expression_service,
    user_service=user_service,
    llm_service=llm_service,
    verb_service=verb_service,
    logger_bot=logger_bot,
    # ... other kwargs
)
```

Then in any handler, just declare the parameter:

```python
@router.message(Command("get"))
async def cmd_get(message: Message, expression_service: ExpressionService, user_service: UserService):
    # expression_service and user_service are injected automatically
    ...
```

> [!NOTE]
> The parameter name must exactly match the keyword argument name passed to `start_polling()`.

## UI Layer

### Message Formatters (`telegram/ui/`)

| File | Purpose |
|------|---------|
| [`ui/expression.py`](../src/flashcard/telegram/ui/expression.py) | `format_review_message()` — formats flashcard for display |
| [`ui/expression_lists.py`](../src/flashcard/telegram/ui/expression_lists.py) | Formats collection listings |
| [`ui/verb.py`](../src/flashcard/telegram/ui/verb.py) | `format_verb_conjugation()` — formats conjugation tables |
| [`ui/story.py`](../src/flashcard/telegram/ui/story.py) | `format_story_messages()` — splits story into Telegram-safe chunks |

### Callback Factories (`telegram/ui/factories/`)

Callback factories define structured callback data patterns using aiogram's `CallbackData`:

| Factory | Pattern | Used by |
|---------|---------|---------|
| `VerbCallback` | Verb tense selection | `verb.py` |
| Review callbacks | `grade:{id}:{grade}:{direction}` | `review.py` |
| Creation callbacks | `save:{norm}`, `regen:{expression}` | `creation.py` |

### Keyboards (`telegram/keyboards.py`)

Central keyboard builder for inline and reply keyboards:
- `get_review_keyboard()` — grade buttons (0–5)
- `get_verb_keyboard()` — tense selection buttons
- Reply keyboard for quick command access

### FSM States (`telegram/states/`)

Finite State Machine states for multi-step conversations:
- **Settings FSM** — Language selection, level selection, interval configuration
- **Feedback FSM** — Feedback message collection

## Error Handling Notes

- [`errors.py`](../src/flashcard/telegram/handlers/errors.py) appends trace IDs to admin alerts when available.
- Global error alerts resolve trace ID from handler DI (`trace_id`) or from exception metadata set in middleware (`event.exception.trace_id`).
- The global error handler returns `True` after processing, so aiogram treats the exception as handled and does not re-propagate it.
- Callback-query error replies are guarded for missing `callback_query.message` (inline/no-message updates), while still answering the callback query to stop Telegram client spinners.
- [`review.py`](../src/flashcard/telegram/handlers/review.py) uses `safe_answer_callback(...)` to suppress expected Telegram callback-expiry errors (`query is too old` / invalid query id) while re-raising other `TelegramBadRequest` errors.

## Helpers (`telegram/helpers/`)

| File | Purpose |
|------|---------|
| [`card_generator.py`](../src/flashcard/telegram/helpers/card_generator.py) | `generate_and_render_card()` — orchestrates LLM call + formatting. Returns `(content, success, card, user)`. |

## i18n Strings

All user-visible bot text lives in [`resources/locales/en.json`](../src/flashcard/resources/locales/en.json).

### Key Naming Convention

```
{layer}.{feature}.{key}
```

Examples:
- `commands.start.welcome` — `/start` welcome message
- `callbacks.save.success_alert` — Save button feedback
- `messages.errors.service_unavailable` — Generic error

### Adding a New String

1. Add the key to `en.json`:
   ```json
   "commands": {
       "your_command": {
           "your_key": "Your message with {variable}"
       }
   }
   ```
2. Use in handler:
   ```python
   await message.answer(i18n.get("commands.your_command.your_key", variable="value"))
   ```

> [!WARNING]
> Since the bot uses `ParseMode.HTML`, any error messages or dynamic content that might contain `<` or `>` must be escaped with `html.escape()` before sending. See the scheduler error handling for an example.
