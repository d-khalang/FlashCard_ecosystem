# Kartino Mini App

A Telegram Mini App that is a thin client of the use cases in `flashcard/app/`. One deployment per
language instance, like the bot: same database, own URL, no language switch. This replaces the
`kartino-mini-app` branch, whose parallel backend is not used.

## Rules

- Business rules live in `flashcard/app/` use cases and in the services that own the data. HTTP routes
  only authenticate, call one use case, and map typed results to JSON. No raw collections in routes.
- No attempts, job queue, presence, leases, sessions database or authority database.
- The bot and scheduler keep working unchanged, apart from the small changes listed here.
- New document fields are optional, so the running bot image can read them.
- Prefer a small typed result over an exception for expected outcomes (as `app/review.py` does).

## Components

| Part | Where |
|---|---|
| In-app study use cases | `flashcard/app/study.py` (`StudyUseCases`, built in `composition.py`) |
| HTTP app | `flashcard/miniapp/`: `api.py` (`create_app`), `auth.py`, `routes/`, `schemas.py`, `prefetch.py`, `rate_limit.py` |
| Entry point | `flashcard-miniapp` script: FastAPI + `open_resources` + `build_core`. No Telegram polling, webhook or scheduler |
| Frontend | `miniapp/`: React 19, TypeScript, Vite. Built files are served by the API container |
| Image | `miniapp/Dockerfile`, build context = repo root: Node stage builds the frontend, Python stage installs `flashcard-project` |

Routing: Caddy sends `app.<domain>/it/*` to `miniapp-it:8000` and `/en/*` to `miniapp-en:8000`, stripping
the prefix. So the frontend uses relative URLs only (`base: './'`, API at `./api/v1`).

## Authentication

Every API request sends `Authorization: tma <Telegram.WebApp.initData>`. The server checks the HMAC with
this instance's `BOT_TOKEN` (no cookies, sessions or CSRF concerns), rejects `auth_date` older than 24 h,
and takes the user id from the signed `user` field only. Then it calls `UserService.record_seen`, which
creates new users and counts as an interaction.

Optional setting `MINIAPP_ALLOWED_USER_IDS` (comma-separated): when set, others get 403. Used for the
tester stage of the rollout. No development bypass exists in application code: the dev runner signs
real init data with the dev bot's token.

## Delivery and grading without a Telegram message

Grade-once uses `pending_message_id`. A card delivered in the app gets a **negative** random integer as its
delivery id, within JavaScript's safe integer range, so it can never equal a Telegram message id. The same
grade-once code then applies, and `pending_message_id` stays through the contract step.

- `CurrentReview.in_app` is true when `message_id < 0`. `awaiting_answer` returns False for these: closing
  the app on an ungraded card must not stop bot reminders.
- In-app delivery does not call `mark_pending` (the legacy flag). It stores the card, records usage and
  writes `current_review`, as `mark_sent` does otherwise.
- If `current_review` exists and its expression still has a stored card (bot or app delivered), the app
  resumes that same card, with the same delivery id. Grading it there resolves it; the old bot message then
  answers "already graded". Direction `unknown` is treated as `forward`. No stored card: deliver a new one.
- `from_storage` on resume: true when `last_card.generated_at` is more than 60 s older than `sent_at`.

## Undo

One level: the last grade made in the app, until the next app grade, for at most 1 hour.

- `ExpressionService.grade_expression` gains an option to also write, in the same update,
  `grade_undo: {delivery_id, direction, stats_before, activity_before}` on the expression. Every grade
  without that option unsets it.
- `ReviewStateStore` writes `users.last_app_grade: {expression_id, direction, delivery_id,
  previous_reviewed_at, sent_at, graded_at}`.
- Undo restores the stats, `last_activity_at` and `pending_message_id` with a compare-and-set on
  `grade_undo.delivery_id` and `pending_message_id: null`, then restores `current_review` and
  `last_reviewed_at`, and clears `last_app_grade`. If the card was re-sent or graded elsewhere, the
  compare-and-set fails and the result is "nothing to undo". Usage is not refunded.
- Accepted limitation: a next card already delivered keeps its 12 h cooldown after undo.

## Prepare one card ahead

`prefetch.py`: one in-memory slot per user in this process, holding a task or a finished `ReviewReady`,
with a 10-minute lifetime. A restart just loses it.

- `POST /study/prepare` starts the task unless one exists; repeated calls are no-ops. A failed task keeps
  the slot empty for 30 s, so failures cannot be used to spam the LLM.
- `POST /study/next` takes the slot if valid and otherwise generates. Valid means: the expression is still
  active and past its cooldown (add `ExpressionService.still_due`), the settings still match `card_settings`,
  and quota still allows it (a fresh card over quota falls back to its stored card, or quota result).
- Usage is counted only on delivery, as now. An abandoned prepared card costs one LLM call and no quota.

## Refresh a section

`StudyUseCases.refresh_section(user_id, delivery_id, section)`, section `definition`, `translations` or
`example`. Only for the card currently pending with that delivery id. Costs 1 card (`QuotaPolicy`). New
method `LLMService.generate_card_section` (prompt in `services/llm/prompts.py`): keep the expression and
sense, write it differently from the current text, an example must be a new sentence using the expression,
keep the translation labels. Merge the result into `last_card` with a compare-and-set on
`pending_message_id`. On failure the card is unchanged.

## API

Base `/api/v1`. JSON. Errors: `{"error": {"code", "message"}}` with codes `auth_required` 401,
`not_allowed` 403, `not_found` 404, `invalid_request` 422, `rate_limited` 429 (with `Retry-After`),
`generation_failed` 503. Rate limit per user, in memory: 20/min on LLM routes (marked *), 120/min otherwise.
`GET /health` needs no auth.

Types:

```
Translation  {label: str, country: str|null, text: str}   // country: "ir", from the label's flag emoji
Content      {definition: str|null, translations: Translation[], example: str|null, note: str|null}
StudyCard    Content + {delivery_id: int, expression_id: str, value: str, direction: "forward"|"reverse",
                        from_storage: bool, older_settings: bool}
Settings     {target_level, primary_language, secondary_language: str|null, review_mode: "standard"|"dual",
              review_interval_minutes: int, is_active: bool}
QuotaResult  {status: "quota", tier: str, limit: int}
```

| Route | Body / query | Response |
|---|---|---|
| `GET /me` | | `{language: {code, name, country}, settings: Settings, quota: {used, limit: int\|null}, words: {total, ready}, options: {levels: str[], languages: [{code, name, country}], min_interval, max_interval}}` |
| `GET /study/current` | | `{card: StudyCard\|null, undo_available: bool}` |
| `POST /study/next` * | | `{status: "ready", card}` or `{status: "none"}` or `QuotaResult`. Returns the pending card if one exists, so a double tap is safe |
| `POST /study/prepare` * | | `202 {}` |
| `POST /study/grade` | `{delivery_id, expression_id, direction, grade: 0..5}` | `{status: "graded", undo_available: true}` or `{status: "not_pending"}`; 404 if the card is gone |
| `POST /study/undo` | | `{status: "undone", card: StudyCard}` or `{status: "nothing_to_undo"}` |
| `POST /study/refresh` * | `{delivery_id, section}` | `{status: "ready", card}` or `{status: "not_pending"}` or `QuotaResult` |
| `POST /cards/preview` * | `{text}` (max 200) | `{status: "ready", norm, content: Content}` or `{status: "unclear", note, suggestions}` or `{status: "invalid", suggestions}` or `QuotaResult` |
| `GET /collection` | `limit` (max 50), `cursor`, `q` | `{items: [{id, value, reps, lapses, created_at}], next_cursor: str\|null}`. Newest first. `q` of 2+ characters searches, without paging. A shorter `q` is 422 |
| `POST /collection` | `{value}` (max 200) | `201 {status: "saved"\|"already_saved"}` |
| `GET /collection/{id}` | | `{id, value, reps, lapses, created_at, content: Content\|null, generated_at}` |
| `DELETE /collection/{id}` | | 204 or 404 |
| `POST /collection/import` * | `{text}` (max 1000) | `{status: "imported", items}` or `{status: "all_duplicates"\|"parse_failed"\|"nothing_found"\|"invalid_language"}` or `{status: "too_long", limit}` or `QuotaResult` |
| `PATCH /settings` | any `Settings` fields | `Settings`. Bad values are 422 (`SettingsUseCases` raises `ValueError`) |

Later features add routes and a navigation entry only: `stories`, `progress`, `verbs/{verb}`, `feedback`.

Static files and API responses send a CSP with `frame-ancestors https://web.telegram.org https://*.telegram.org`
and `script-src 'self' https://telegram.org`, plus `X-Content-Type-Options: nosniff`. `index.html` is not cached.

## Frontend

Screens: Today, Study (full screen, no bottom nav), Collection, Settings. Interface language English or
Italian, default from Telegram's `language_code`, saved in the browser. A checkpoint offers Continue or
Finish every 5 reviews. No swipe.

- **Themes:** all colors, radii, border widths, shadows and fonts are CSS custom properties, named by role.
  Theme = a `data-theme` value on `<html>`; light or dark = `data-scheme`, from Telegram's `colorScheme`.
  Components never contain a color. Only `sticker` exists now. Adding a theme means adding one CSS file.
- **Reverse cards:** the question shows the definition, or the translations if there is none. The answer
  reveals the word, then the rest.
- **Flags:** small SVG flags from `flag-icons`, by `country`, because Windows does not draw flag emoji. The
  language name is the accessible label. No country: show the raw label.
- **Example sentence:** its own shallow tinted panel.
- Text is `dir="auto"`. Touch targets at least 44 px. Honors reduced motion.
