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
creates new users and counts as an interaction. The rate limit comes first, so a client stuck on 429
writes nothing to `users`.

**Users who never opened the bot chat.** A user who arrives through the app may never have started the bot
chat, and the bot cannot message them (Telegram answers "can't initiate conversation", which deliberately
does not pause a user). New optional field `UserDB.bot_chat_open`; missing means true, which covers every
existing user.

- A user newly inserted by the Mini App gets `bot_chat_open: false` (`$setOnInsert`), unless the signed
  `user.allows_write_to_pm` is true, which sets it true. The app never closes a chat that is open.
- Any bot-path `record_seen` (a message from the user) sets it true.
- The scheduler's due-user queries exclude `bot_chat_open: false`, before any LLM call. `/me` reports
  `reminders_available` so the app can say why no reminders arrive. `USER_GONE_REASONS` is unchanged.
- Tradeoff: reminders start only after the user writes to the bot (or allows it in Telegram). A user who
  only ever uses the app gets none, by design; the cost is one extra step instead of a failing LLM call and
  an admin report on every tick.

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
  resumes that same card, with the same delivery id. Grading it there resolves it and removes the
  buttons from the old bot message; undoing that grade puts them back (`miniapp/bot_buttons.py`). This runs
  after the response, in order per user, and a failure is only logged: a tap on a button left behind answers
  "already graded" and removes them. Direction `unknown` is treated as `forward`. No stored card: deliver a new one.
- `from_storage` on resume: true when `last_card.generated_at` is more than 60 s older than `sent_at`.

## Undo

One level: the last grade made in the app, until the next app grade, for at most 1 hour.

- `ExpressionService.grade_expression` gains an option to also write, in the same update,
  `grade_undo: {delivery_id, direction, stats_before, activity_before}` on the expression. Every grade
  without that option unsets it.
- `ReviewStateStore` writes `users.last_app_grade: {expression_id, direction, delivery_id,
  previous_reviewed_at, sent_at, graded_at}`, where `graded_at` is the exact time `record_reviewed` wrote to
  `last_reviewed_at`.
- Undo restores the stats, `last_activity_at` and `pending_message_id` with a compare-and-set on
  `grade_undo.delivery_id` and `pending_message_id: null`. If the card was re-sent or graded elsewhere, the
  compare-and-set fails and the result is "nothing to undo". Usage is not refunded.
- Then, without overwriting anything newer: `last_reviewed_at` goes back only if it still equals this grade's
  time (a later bot grade keeps the interval it started), and `current_review` is restored only if there is
  none or it is an app card (a newer unanswered bot card stays the current review). Finally `last_app_grade`
  is cleared. Stats always come back; these two user fields are best effort.
- Accepted limitation: a next card already delivered keeps its 12 h cooldown after undo.

## Prepare one card ahead

`prefetch.py`: one in-memory slot per user in this process, holding a task or a finished fresh `ReviewReady`
(a stored card costs nothing to derive again, so it is never kept), with a 10-minute lifetime. A restart
just loses it.

- `POST /study/prepare` starts the task unless one exists; repeated calls are no-ops. A task that makes no
  card keeps the slot empty for 30 s, so failures cannot be used to spam the LLM.
- That hold is a refusal when it follows an error: `POST /study/next` also answers 503 `generation_failed`
  without an LLM call during the hold, and a failing `next` starts it. A waiting card is still returned
  during the hold, and "nothing to study" is not a failure. A word the LLM could not read does not start
  the hold (it is deferred already), and a refusal never blocks a word with a stored card.
- Over quota, the app delivers the best due word that has a stored card when the top word has none, so "free
  stored cards after the limit" holds for backlogs of new words. The bot and scheduler keep the top-word
  rule: a scheduled push is not something the user is waiting for.
- `POST /study/next` takes the slot if valid and otherwise generates. Valid means: the expression is still
  active and past its cooldown (add `ExpressionService.still_due`), the settings and `review_mode` still
  match (a reverse card is not delivered after switching to standard), and quota still allows it (a fresh
  card over quota is generated again, which falls back to its stored card, or quota result).
- Usage is counted only on delivery, as now. An abandoned prepared card costs one LLM call and no quota.

## Credits

Card quota is paid in daily credits (`TIER_LIMITS_*_CREDITS`, reset at 00:00 UTC): a new card, a bot
regenerate or an `/import` costs 2 (`CARD_CREDITS`), a refreshed card part 1 (`SECTION_CREDITS`). A
generation is refused when its cost does not fit, so with 1 credit left a part refresh still works and a new
card does not. Stories and audio keep their own daily counts. Own-key and admin users are not limited.

- Mini App: a chip in the Today top bar shows the credits left with a small meter, and turns to its low look
  when fewer than two new cards are left. Tapping it opens a sheet with the costs and the time to the refill.
  When `quota.limit` is null it shows `∞` with a full meter and the same sheet. The refresh buttons show no cost.
- Bot: `/settings` shows a credits line ("unlimited" when there is no limit); the limit message names the daily
  credits and the card cost.

Open: the unlimited view was added so admins can see the normal layouts. Own-key users get it too, because the
API sends `limit: null` for both, but the own-key feature is not active today. Before activating it, design a
better counter for those users: costs and "Refills in" mean little to someone paying with their own key.

## Unintelligible words and LLM allowance

**One word must not block study.** When the LLM answers `success=false` and the expression has no stored
card, `ReviewUseCases.prepare_next` first defers that expression (`ExpressionService.defer_review`: sets only
`last_activity_at`, the user's own card, so the 12 h cooldown applies) and then raises
`CardGenerationFailed` as before. A provider error or timeout defers nothing. For the bot this means the
scheduler and `/get` fail once for that word, as before, and then pick other words instead of the same one on
every tick; the word is tried again after 12 h. `POST /study/next` retries once with the next candidate, then
answers 503.

**Free LLM calls.** Quota counts delivered results only, so unclear previews, imports that save nothing,
refresh-grade-undo loops and failing `next` calls could repeat for free. Each LLM attempt is therefore
charged, at the moment the call really starts, against two in-memory per-user allowances: 20 per minute and
`MINIAPP_LLM_DAILY_ATTEMPTS` per UTC day (default 300, three times the largest non-admin daily credit limit
of 100, and every LLM call costs at least one credit; admins are exempt from the daily one). Over either: `rate_limited` 429 with `Retry-After`. Resuming a
waiting card, using the prepared card, a `prepare` that makes no LLM call and a refresh of a card that is no
longer pending cost nothing. Use cases stay free of HTTP: they take an optional `before_generation`
callback and return a typed `Throttled`/`GenerationHeld` result. A `prepare` is charged inside its task, right
before the LLM call, so it always answers 202: a refused one just leaves nothing prepared, and `next` then
answers for itself.

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
`generation_failed` 503, `payload_too_large` 413. Rate limits per user, in memory: 120/min on every route,
and on top of that 20/min and `MINIAPP_LLM_DAILY_ATTEMPTS`/day for each real LLM call (routes marked *; see
above). Request bodies over 64 KB are refused with 413 before sign-in (by `Content-Length`, and while
streaming when it is missing or wrong). `GET /health` needs no auth.

Types:

```
Translation  {label: str, country: str|null, text: str}   // country: "ir", from the label's flag emoji
Content      {definition: str|null, translations: Translation[], example: str|null, note: str|null}
StudyCard    Content + {delivery_id: int, expression_id: str, value: str, direction: "forward"|"reverse",
                        from_storage: bool, older_settings: bool}
Settings     {target_level, primary_language, secondary_language: str|null, review_mode: "standard"|"dual",
              review_interval_minutes: int, is_active: bool}
QuotaResult  {status: "quota", tier: str, limit: int}   (limit: today's credits)
```

| Route | Body / query | Response |
|---|---|---|
| `GET /me` | | `{reminders_available: bool, language: {code, name, country}, settings: Settings, quota: {used, limit: int\|null, card_cost, section_cost}, words: {total, ready, pending: bool}, options: {levels: str[], languages: [{code, name, country}], min_interval, max_interval}}` |
| `GET /study/current` | | `{card: StudyCard\|null, undo_available: bool}` |
| `POST /study/next` * | | `{status: "ready", card}` or `{status: "none"}` or `QuotaResult`. Returns the pending card if one exists, so a double tap is safe |
| `POST /study/prepare` * | | `202 {}` |
| `POST /study/grade` | `{delivery_id, expression_id, direction, grade: 0..5}` | `{status: "graded", undo_available: true}` or `{status: "not_pending"}`; 404 if the card is gone |
| `POST /study/undo` | | `{status: "undone", card: StudyCard}` or `{status: "nothing_to_undo"}` |
| `POST /study/refresh` * | `{delivery_id, section}` | `{status: "ready", card}` or `{status: "not_pending"}` or `QuotaResult` |
| `POST /cards/preview` * | `{text}` (max 200) | `{status: "ready", norm, content: Content}` or `{status: "unclear", note, suggestions}` or `{status: "invalid", suggestions}` or `QuotaResult` |
| `GET /collection` | `limit` (max 50), `cursor`, `q` | `{items: [{id, value, reps, lapses, created_at}], next_cursor: str\|null}`. Newest first. `q` of 2+ characters searches, without paging. A shorter `q` is 422 |
| `POST /collection` | `{value}` (max 200) | `201 {status: "saved"\|"already_saved"}`, or `200 {status: "invalid", suggestions}` (the instance's language validator refused it; the built-in validators make no LLM call), or `200 {status: "too_many", limit}` |
| `GET /collection/{id}` | | `{id, value, reps, lapses, created_at, content: Content\|null, generated_at}` |
| `DELETE /collection/{id}` | | 204 or 404 |
| `POST /collection/import` * | `{text}` (max 1000) | `{status: "imported", items}` or `{status: "all_duplicates"\|"parse_failed"\|"nothing_found"\|"invalid_language"}` or `{status: "too_long", limit}` or `{status: "too_many", limit}` or `QuotaResult`. `items` is `str[]`: the values newly saved. The body schema allows up to 5000 characters so that `too_long` (over 1000) can be answered |
| `PATCH /settings` | any `Settings` fields | `Settings`. Bad values are 422 (`SettingsUseCases` raises `ValueError`) |
| `GET /audio/{expression_id}/{part}` | part: `word`, `definition`, `example`, `translation_0`, `translation_1` | `audio/mpeg` of that part of the user's stored card. 404 if the card or part is gone, 429 `audio_limit` (no `Retry-After`) when the daily audio limit is used up, 429 `rate_limited` above 30 generated clips a minute, 503 `generation_failed` when the speech service fails |

`words.pending` is true when a delivered card is waiting for a grade, by the same rule as resuming it (the review
exists, its expression still has a stored card and is still pending under that delivery id).
`MINIAPP_MAX_WORDS` (default 5000) limits saved words per user in the Mini App, for save and import; the bot
has no limit. An import is refused whole when the collection is full before the LLM call, or when the parsed
items would pass the limit (duplicates among them count, so it errs on the strict side).

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
