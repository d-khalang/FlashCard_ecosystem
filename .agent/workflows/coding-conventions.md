---
description: Project coding conventions — check before writing or modifying code
---

# FlashCard Bot — Coding Conventions

## Time & Dates

- **Always** use `now_utc()` from `flashcard.utils.time` for current time. Never use `datetime.now()`, `datetime.utcnow()`, or `date.today()`.
- Use `iso_z(dt)` from `flashcard.utils.time` to format datetime objects for MongoDB storage (produces `YYYY-MM-DDTHH:MM:SSZ`).
- For date-only comparisons (e.g. daily resets), use `now_utc().date().isoformat()`.

## Services & DI

- All services are instantiated in `telegram/bot.py` and injected via aiogram's DI kwargs in `start_polling()`.
- When creating a new service, follow the pattern: `class MyService: def __init__(self, cols: dict)` where `cols` is the MongoDB collections dict.
- `ConsumptionService` is the single entry point for usage tracking. Call `consumption_service.increment(user_id, metric, uses_own_key)` in handlers after successful actions.

## Consumption Tracking

- Only track actions that consume external resources (LLM API calls, third-party APIs).
- LLM metrics (`cards_generated`, `stories_generated`) are split into `system_api` and `user_api` buckets based on whether the user has their own API key (`user.api_config is not None`).
- `verb_lookups` is always system-side (third-party scraper).
- Internal operations (save, grade, import, feedback) are not tracked.

## MongoDB

- All user data lives in the `users` collection; consumption is a nested subdocument under `consumption`.
- Use `$inc` for atomic counter increments, `$set` for field updates.
- Always `upsert=True` when updating user documents to handle first-time users.

## Handler Patterns

- Handlers receive services via aiogram DI (function parameters).
- Track consumption **after** a successful action, not before.
- Use `i18n.get()` for all user-facing strings.

## Logging

- Use `from flashcard.utils.logger import get_logger` then `logger = get_logger(__name__)`.
- Log at `info` for successful operations, `warning` for recoverable issues, `error` for failures.
