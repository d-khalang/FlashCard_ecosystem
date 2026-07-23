# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## v1.1.1 (2026-07-23)

### CI

- Publish versioned flashcard-bot and conjugator images to GHCR from GitHub Releases.

### Test

- Stabilize provider race tests and align smoke checks with the release pipeline.


### Added
- Existing project functionality before automated release tracking was introduced.

## v1.1.0 (2026-07-17)

### Feat

- **config**: load application secrets at runtime

## v1.0.0 (2026-07-17)

### Feat

- **language**: make learning language configurable

### Fix

- **config**: make docker mongo defaults usable
- **config**: align docker conjugator service name

## v0.11.0 (2026-06-26)

### Feat

- **services**: inherit parent created_at for simulated reverse stats
- **priority**: increase the recency devisor to 24 to avoid Leech Trap

## v0.10.0 (2026-06-01)

### Feat

- **docker**: migrate scraper to offline it-conjugator-api submodule

## v0.9.0 (2026-05-27)

### Feat

- **locales**: add instructional video links and fix Italian encodings - Added Telegram post links for the new instructional videos in en.json and it.json:   - Video 1 (how it works) added to /start command.   - Video 3 (verb guide) added to /verb command. - Added missing settings menu translations for Italian locale. - Fixed corrupted Unicode emojis and characters in the modified parts of it.json.
- **llm**: race Groq with Gemini fallback and trace final provider
- **handlers**: notify user during active LLM provider fallback
- **services**: implement Groq strategy and Google fallback mechanism
- **deps**: add Groq dependencies and multi-provider schema support

### Fix

- session cookie
- **scraper**: use curl-cffi impersonating chrome browser
- **scraper**: scraper headers updated to normal
- **user-quota**: enforce daily resets in local generation checks
- **services**: mock LLMService in lifecycle tests and skip web submodule tests in CI

### Refactor

- **consumption**: consolidate daily reset logic to single source of truth

## v0.8.0 (2026-04-11)

### Feat

- **web**: give landing page CTAs a custom Kartino button system

### Refactor

- **services**: improve expression prompt for definition quality and acceptance - prevent self-referencing in def_it so reversed-mode guessing works - handle qualcosa/qualcuno as grammatical placeholders in norm and def_it - restore clearly missing accents during normalization - accept longer Italian phrases/sentences instead of rejecting as unclear - raise def_it word limit to 25, make emojis conditional - fix duplicate rule numbering (3 → 3, 4)

## v0.7.0 (2026-03-23)

### Feat

- **telegram**: add /remove guide for inline flashcard deletion

### Refactor

- **runtime**: deprecate standalone production polling entrypoint

## v0.6.0 (2026-03-23)

### Feat

- **telegram**: add inline flashcard removal with safe confirmation

### Fix

- **webhook**: include inline_query in Telegram allowed updates
- **telegram**: ignore bot-originated messages and cap inline query length

## v0.5.1 (2026-03-17)

### Fix

- **telegram**: force IPv4 for bot sessions to prevent Docker bridge timeouts

## v0.5.0 (2026-03-17)

### Feat

- **user**: sync telegram usernames in background via trace middleware
- **quota**: implement user tiered limits and daily generation quotas.

### Fix

- **quota**: lazily initialize trial period on first active interaction

### Refactor

- **user**: User quota variables moved to .env file
- **service**: add refactoring TODOs for centralized user document management

## v0.4.0 (2026-03-14)

### Feat

- **docker**: migrate to secure local mongodb 8 instance
- **middleware**: add global 10s timeout for Telegram handlers - Create HandlerTimeoutMiddleware to cap all bot interactions - Register middleware for messages and callback queries - Remove redundant local timeouts in review handlers
- **api**: split health endpoint into liveness and readiness probes
- **db**: enhance MongoDB resilience with granular timeouts and monitoring
- **llm**: dynamically instantiate clients for all core API keys Refactor LLMKeyProvider to expose all keys in the 'core' configuration and update LLMService to iterate over these keys during initialization. This removes the need for hardcoded client names and enables automatic

### Fix

- **docker**: healthcheck command fixed to comply with auth
- **handlers**: use contextlib.suppress in safe_call

## v0.3.0 (2026-03-10)

### Feat

- **handlers**: add centralized exception-to-user-message mapping Enhance errors.py with a mapping system that identifies Gemini and MongoDB failures to provide specific, friendly feedback (e.g., "AI overloaded"). This centralizes decision-making, removes redundant catch logic in story/collection handlers, and improves the overall UX when external services are degraded.

## v0.2.1 (2026-03-10)

### Fix

- **db**: add CSOT timeout and deep health check to prevent silent outages MongoDB Atlas network blip caused 180s handler stalls while /health returned 200. Root fix: timeoutMS=10_000 caps any DB operation at 10s, health endpoint now pings MongoDB (returns 503 when unreachable), and handle_grade is wrapped in asyncio.timeout(15) to prevent cascading stalls in the error path.

### Refactor

- **handlers**: extract safe_answer_callback to shared helpers module Move safe_answer_callback from review.py into telegram/helpers/callback_utils.py and replace all bare callback.answer() calls across verb, creation, user_settings, and errors handlers. Add safe_call helper for timeout-guarded fire-and- forget coroutines.

## v0.2.0 (2026-03-09)

### Feat

- **web**: enhance feature card animations for desktop and mobile
- **web**: enhance feature card animations for desktop and mobile
- configure domains and private web submodule
- **env**: .env.prod added
- **deploy**: add domain-based caddy setup and webhook/polling mode toggle
- **security**: harden input validation and LLM prompt
- **i18n**: command explanations on help
- **i18n**: content improvement in locale start message
- **i18n**: content improvement in locale accross communications
- **llm**: add fallback retry mechanism and robust generic error propagation
- **handlers**: notify admin on LLM generation errors
- **ui**: refine flashcard message formatting and success tag
- **handlers**: display saved expression in save confirmation message
- **config**: add agent skills and consolidate .agent directory
- support dynamic number of translation languages (1 or 2)

### Fix

- **docker**: route only webhook path and health in caddy
- **docker**: route only webhook path and health in caddy
- **ui**: use i18n locale strings for review keyboard grade 0 and 5 buttons
- **resilience**: harden webhook processing and asyncio background error handling
- docker compute volume for the logs
- **scheduler**: only report users who actually received a flashcard
- **caddy**: proxy all bot subdomain paths to flashcard service
- **caddy**: use webhook prefix matcher for nested webhook paths
- **testing**: lazy-load api key config to avoid import-time failures
- **packaging**: include resource json files in python package
- **handlers**: propagate trace id to global errors and handle expired callbacks
- **services**: handle missing onboarding_step field in DB for legacy users
- **settings**: suppress TelegramBadRequest on identical keyboard clicks

### Refactor

- **resources**: load api keys and locales via importlib.resources
- **tracing**: unify trace finalization and add scheduler spans
- **i18n**: align user-facing texts with Kartino brand identity
- **i18n**: move hardcoded UI and handler texts to locale files - Add new translation keys to [en.json] - Replace hardcoded strings with `i18n.get()` calls in UI components
- return Pydantic UserDB model from UserService instead of dict
