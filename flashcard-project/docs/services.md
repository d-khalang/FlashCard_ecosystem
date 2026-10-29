# Services Reference

This document covers the service layer — the business logic behind every bot feature.

## Overview

```mermaid
graph TD
    H[Handlers] --> ES[ExpressionService]
    H --> US[UserService]
    H --> VS[VerbService]
    H --> LLM[LLMService]
    H --> I18N[I18nService]
    H -.-> TL[TraceLogger]
    
    ES --> DB[(MongoDB)]
    US --> DB
    H --> QP[QuotaPolicy]
    QP --> CS[ConsumptionService]
    H --> RS[ReviewStateStore]
    RS --> DB
    VS --> DB
    VS --> SCRAPER[WR Scraper API]
    LLM --> GEMINI[Google Gemini API]
    LLM --> GROQ[Groq API]
    CS --> DB
    
    ES --> ALG[Algorithm]
    ALG --> PRI[priority.py]
    ALG --> GRD[grading.py]
```

All services are built by `build_core` in [`composition.py`](../src/flashcard/composition.py), the only
place that hands out collections: each service receives only its own collection, never the
whole `cols` dict (guarded by `tests/unit/test_data_ownership.py`). Handlers do not receive services: they call use cases (`flashcard/app/`), which `build_core` wires to the services. See [Architecture — Dependency Injection](./architecture.md#dependency-injection).

---

## ExpressionService

**File:** [`services/expression.py`](../src/flashcard/services/expression.py)  
**Collection:** `expressions`  
**Dependencies:** `expressions` (the expression collection only)

Manages flashcard CRUD and the review candidate selection algorithm. Every read and remove
uses one definition of an active card, `ACTIVE`: `status` is `"active"` or missing.

| Method | Signature | Description |
|--------|-----------|-------------|
| `add_expression` | `(user_id, value) → bool` | Adds expression if not duplicate (case-insensitive). Returns `True` if inserted. Never writes `users`. |
| `add_expressions_bulk` | `(user_id, expressions) → list[str]` | Bulk insert, skipping duplicates. Returns list of actually inserted values. |
| `get_all_expressions` | `(user_id) → list[str]` | The user's active expressions, each value once, oldest first. |
| `get_review_candidate` | `(user_id, review_mode) → dict \| None` | Selects the highest-priority card for review using the SRS algorithm. Filters by 12-hour cooldown. The caller passes the user's `review_mode`. Returns `{doc, direction}`. |
| `update_expression_sent` | `(expression_id, message_id)` | Marks expression as sent with the Telegram message ID. |
| `grade_expression` | `(user_id, expression_id, grade, direction="forward")` | Processes a grade (0–5) using the SRS algorithm and updates the expression's stats only. Raises `ValueError` for a bad grade or direction; returns `None` only when the card is not found. |

### Review Candidate Selection

The `get_review_candidate` method implements the core spaced repetition logic:

1. **Cooldown filter** — Excludes cards interacted with in the last 12 hours. For cards with no `last_activity_at`, uses `created_at` instead.
2. **Priority scoring** — Each candidate gets a priority score via `calculate_priority()`.
3. **Direction selection** — In `"dual"` review mode, both forward and reverse directions are scored. The highest overall priority wins.

---

## UserService

**File:** [`services/user.py`](../src/flashcard/services/user.py)  
**Collection:** `users`  
**Dependencies:** `users` (the users collection). Quota (limits, trial, own key) lives in [`app/quota.py`](../src/flashcard/app/quota.py) (`QuotaPolicy`).

Manages user profiles and settings. The only service that creates user documents.

| Method | Signature | Description |
|--------|-----------|-------------|
| `record_seen` | `(user_id, username)` | Called by the trace middleware before every handler. Creates the user on first contact (`created_at`, the trial start) and updates `last_seen_at` and `username`. The only upsert on `users`. |
| `get_user` | `(user_id) → UserDB` | Returns the user document, or unsaved defaults if not found. |
| `active_users_reviewed_before` | `(cutoff, *, exclude_pending, on_unreadable) → list[UserDB]` | The scheduler's prefilter. Unreadable documents go to `on_unreadable` and are skipped. |
| `active_users_possibly_paused` | `(on_unreadable) → list[UserDB]` | Migration only: users the shadow compare reads. |
| `set_active` | `(user_id, active)` | Pauses (`False`) or resumes (`True`) scheduled reviews. Idempotent. |
| `set_target_level` / `set_review_interval` / `set_primary_language` / `set_secondary_language` / `set_review_mode` | `(user_id, value)` | One setter per setting, all idempotent single `$set`s. Each enforces the allowed values (rules in `schemas/user.py`) and raises `ValueError`; there is no generic field writer. |
| `advance_onboarding` | `(user_id, current_step) → bool` | Atomically advances user's onboarding step if it matches `current_step`. |
| `backfill_created_at` | `(user_id, created_at) → bool` | Migration only: sets a missing `created_at`, never overwrites. |

Only `UserService`, `ConsumptionService` and `ReviewStateStore` read or write `users`
(guarded by `tests/unit/test_data_ownership.py`; the one-off migrations also read it).
Other code asks an owner, e.g. the review use case passes `review_mode` to `ExpressionService`.

### UserDB Schema

Defined in [`schemas/user.py`](../src/flashcard/schemas/user.py):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `user_id` | `str` | required | Telegram user ID |
| `primary_language` | `LanguageCode` | `"en"` | Translation language |
| `secondary_language` | `LanguageCode?` | `None` | Optional second translation language |
| `target_level` | `LanguageLevel` | `"A2"` | CEFR level (A1–C2) |
| `review_mode` | `str` | `"standard"` | `"standard"` or `"dual"` |
| `review_interval_minutes` | `int` | `30` | Minutes between review batches |
| `is_active` | `bool` | `True` | Whether scheduler sends reviews |
| `has_pending` | `bool` | `False` | Legacy pause flag; replaced by `current_review` + `last_seen_at` (review-state migration) |
| `current_review` | `CurrentReview?` | `None` | Delivered card still waiting for a grade (`expression_id`, `direction`, `message_id`, `sent_at`) |
| `onboarding_step` | `int` | `0` | Tracks user's progress through contextual onboarding tips |
| `created_at` | `str?` | `None` | ISO timestamp of first contact; the trial start |
| `last_seen_at` | `str?` | `None` | ISO timestamp of the user's last interaction |
| `last_push_at` | `str?` | `None` | Legacy, no longer written or read |
| `last_reviewed_at` | `str?` | `None` | ISO timestamp of last graded review (starts the review interval) |
| `api_config` | `UserAPIConfig?` | `None` | Custom LLM provider/model/key config |
| `consumption` | `UserConsumption` | `{...}` | Nested usage counters (`cards_generated`, etc.) with daily reset |

---

## ReviewStateStore

**File:** [`services/review_state.py`](../src/flashcard/services/review_state.py)
**Collection:** `users` (review-state fields)
**Dependencies:** `users` (the users collection)

Sole writer of the user's review state. Never creates users. See the migration plan in
[bot-architecture-refactor.md](../../docs/bot-architecture-refactor.md).

| Method | Signature | Description |
|--------|-----------|-------------|
| `record_sent` | `(user_id, expression_id, direction, message_id)` | Sets `current_review`; a newer card replaces it. |
| `record_graded` | `(user_id, expression_id, direction)` | Clears `current_review` if the grade is for it. |
| `record_removed` | `(user_id, expression_id)` | Clears `current_review` if that card was removed. |
| `record_reviewed` | `(user_id)` | On grade: sets `last_reviewed_at` and clears the legacy `has_pending`. |
| `mark_pending` / `clear_pending` | `(user_id)` | Legacy `has_pending` writes (send / save, import, remove). |
| `backfill_from_legacy` | `(user_id, expression_id, message_id, sent_at) → bool` | Migration only: sets `current_review` from legacy fields, never overwrites. |

---

## ConsumptionService

**File:** [`services/consumption.py`](../src/flashcard/services/consumption.py)
**Collection:** `users` (subdocument `consumption`)
**Dependencies:** `users` (the users collection)

Tracks resource usage (LLM tokens, API calls) with lazy daily resets.

| Method | Signature | Description |
|--------|-----------|-------------|
| `increment` | `(user_id, metric, uses_own_key=False)` | Increments a daily counter. Auto-resets if day changed. |
| `resolve_consumption` | `(consumption) → UserConsumption` | Pure, no DB call: today's counters, or zeroed ones if the stored date is stale. The single source of the daily reset; `QuotaPolicy.check` uses it. |
| `get_consumption` | `(user_id) → UserConsumption` | Returns current usage stats. Auto-resets if stale. |

### Metrics

| Metric | Bucket | Description |
|--------|--------|-------------|
| `cards_generated` | `system_api` / `user_api` | LLM card generations (text→card, regen, /get, scheduled) |
| `stories_generated` | `system_api` / `user_api` | LLM story generations (/story) |
| `verb_lookups` | top-level | Third-party verb scraper calls (always system-side) |

---

## LLMService

**File:** [`services/llm/llm.py`](../src/flashcard/services/llm/llm.py)  
**Dependencies:** Google Gemini and Groq API keys (via `LLMKeyProvider`)

Manages all LLM-powered features using a multi-provider strategy (Groq + Google Gemini) with structured JSON output.

| Method | Signature | Description |
|--------|-----------|-------------|
| `generate_expression_card` | `(raw, *, level, lang1_code, lang2_code?, lang1_label, lang2_label?, on_fallback?) → ExpressionCard` | Generates a flashcard with definition, translations, and example. |
| `parse_import_list` | `(raw_text) → ImportResponse` | Parses user's bulk import text into structured items. |
| `generate_story` | `(words, target_lang, target_level, story_length) → StoryResponse` | Generates a story incorporating user's vocabulary. |

**Models:** 
- **Primary:** Groq (`openai/gpt-oss-120b`)
- **Fallback:** Google Gemini (`gemini-2.5-flash-lite`)

**Resilient Fallback:** 
Requests are initially sent to high-speed Groq with a configurable timeout (`LLM_GROQ_FALLBACK_DELAY_SECONDS`, default 4.0s). If the primary request fails or times out, the service triggers an optional `on_fallback` callback to notify the user, and seamlessly runs a fallback request against the Google Gemini API to fulfill the request.

**Output Structure:**
- **Google Gemini:** Leverages the native GenAI SDK `response_schema` parameter to return structured JSON.
- **Groq:** Implements strict JSON schemas via `strict_json_schema()`, converting model constraints so that nullable and optional Python fields are correctly required in the JSON schema for schema enforcement.

**Key Rotation & Management:**
At startup, `LLMService` parses configured keys from `llm_key.json` and groups them by their `provider` field (`"google"` or `"groq"`). It dynamically instantiates the correct client strategy (`GoogleGenAIProvider` or `GroqProvider`) and sets up separate `itertools.cycle` iterators (`google_cycle` and `groq_cycle`) to load-balance and rotate api calls across available keys.

### Related Files

| File | Purpose |
|------|---------|
| [`llm_key.py`](../src/flashcard/services/llm/llm_key.py) | API key resolution and core key management |
| [`prompts.py`](../src/flashcard/services/llm/prompts.py) | System prompt templates for each LLM task |

---

## TraceLogger

**File:** [`services/trace_logger.py`](../src/flashcard/services/trace_logger.py)  

Writes execution traces to flat files in JSON Lines format for performance monitoring.

| Method | Signature | Description |
|--------|-----------|-------------|
| `log_trace_json` | `(trace_json: str)` | Writes a completed trace JSON line to the active log file asynchronously on a background thread. |
| `shutdown` | `()` | Ensures all pending logs are flushed to disk before application exit. |

Traces are automatically rotated and keep track of latencies, errors, and nested `@observe` spans.

Trace lifecycle finalization is centralized in [`utils/tracing.py`](../src/flashcard/utils/tracing.py) via `finalize_trace(...)`, used by both Telegram update middleware and the scheduler loop.

---

## VerbService

**File:** [`services/verb.py`](../src/flashcard/services/verb.py)  
**Collections:** `conjugation`  
**Dependencies:** `conjugations` (the conjugation cache collection), `http_client` (httpx)

Handles verb conjugation lookup with DB caching.

| Method | Signature | Description |
|--------|-----------|-------------|
| `extract_verb` | `(message_text) → str?` | Extracts verb from `/verb <word>` command text. |
| `is_valid_verb` | `(verb) → bool` | Validates Italian verb format (regex). |
| `get_verb_data` | `(verb) → ConjugationResponse?` | Orchestrates: check DB → check API → cache to DB. |
| `get_verb_from_db` | `(verb) → dict?` | Direct DB lookup. |
| `get_verb_from_api` | `(verb) → ConjugationResponse?` | Calls WR Scraper API. |
| `get_verb_keyboard` | `(data) → InlineKeyboardMarkup` | Builds tense selection keyboard. |

### Lookup Strategy

```mermaid
graph LR
    REQ[get_verb_data] --> DB{In DB?}
    DB -->|Yes| RET[Return cached]
    DB -->|No| API{Call Scraper API}
    API -->|Found| SAVE[Cache to DB] --> RET2[Return]
    API -->|Not found| NONE[Return None]
```

---

## I18nService

**File:** [`services/i18n.py`](../src/flashcard/services/i18n.py)  
**Resources:** [`resources/locales/en.json`](../src/flashcard/resources/locales/en.json)

Manages bot UI strings with dot-notation key access and variable interpolation.

```python
# Usage examples
i18n.get("commands.start.welcome")                    # Simple key
i18n.get("commands.story.writing", count=5)            # With variable
i18n.get("callbacks.grade.rated", grade="3")           # With formatting
```

**Key format:** `{category}.{subcategory}.{key}` (e.g., `commands.verb.instruction`)

> [!TIP]
> All user-visible strings should go in `en.json`, never hardcoded in handler code. To add a new string, add the key to `en.json` and reference it with `i18n.get("your.key")`.

---

## Algorithm

### Priority Calculation

**File:** [`services/algorithm/priority.py`](../src/flashcard/services/algorithm/priority.py)

The `calculate_priority(stats)` function scores each card for review urgency:

```
Priority = 0.40 × Recency + 0.35 × Difficulty + 0.10 × Stability 
         + 0.05 × Novelty + 0.05 × Lapses + Randomness
```

| Factor | Weight | Formula | Meaning |
|--------|--------|---------|---------|
| Recency | 40% | `t / (24 + t)` where `t` = hours since last interaction | Longer unseen → higher priority |
| Difficulty | 35% | `1 - (ewma_grade / 5)` | Lower grades → higher priority |
| Stability | 10% | `1 / (1 + streak)` | Shorter streak → higher priority |
| Novelty | 5% | `1` if zero reps, else `0` | New cards get a boost |
| Lapses | 5% | `min(lapses, 5) / 5` | More failures → higher priority |
| Randomness | ~4% | `random() × 0.08` | Breaks ties, adds variety |

### Grade Processing

**File:** [`services/algorithm/grading.py`](../src/flashcard/services/algorithm/grading.py)

The `calculate_new_stats(stats, grade, is_reverse=False)` function updates SRS stats after a grade:

- **EWMA grade:** `α × grade + (1-α) × previous` where α = 0.30
- **Success:** grade ≥ 3 → increment reps, extend streak
- **Failure:** grade < 3 → increment lapses, reset streak

---

## Centralized Constants

**File:** [`schemas/defaults.py`](../src/flashcard/schemas/defaults.py)

| Constant | Value | Used by |
|----------|-------|---------|
| `DEFAULT_LANG_LEVEL` | `"A2-B1"` | Review card generation, scheduler |
| `DEFAULT_LANG_1_CODE` | `"en"` | Fallback language code |
| `DEFAULT_LANG_1_LABEL` | `"🇬🇧 EN"` | Fallback language flag |
| `DEFAULT_SCHEDULER_INTERVAL_MINUTES` | `30` | Scheduler review cutoff |
