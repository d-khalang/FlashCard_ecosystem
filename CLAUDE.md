# Kartino

Telegram flashcard bot plus a Telegram Mini App. Public repo: never commit secrets, server names,
bot ids or personal setup.

## Layout

- `flashcard-project/` — Python bot and Mini App API (aiogram + FastAPI + MongoDB). Docs in `flashcard-project/docs/`.
  - `src/flashcard/composition.py` — the only place that builds services and use cases.
  - `src/flashcard/app/` — use cases; `services/` — data and outside clients; `telegram/` — handlers and UI;
    `miniapp/` — Mini App API routes.
- `miniapp/` — Mini App frontend (React + Vite + TypeScript).
- `web/`, `it-conjugator-api/` — git submodules (site and conjugator API).
- `docs/` — ecosystem docs (Mini App, CI/CD). `caddy/`, `docker-compose.yml` — local stack.

## Tests

Bot (from `flashcard-project/`, Python 3.12):

```bash
pip install -e ".[dev]"
pytest tests/unit -q --tb=short
pytest tests/integration tests/smoke -q --tb=short
```

- Some layers need MongoDB at `mongodb://127.0.0.1:27019` (override `KARTINO_TEST_MONGO_URI`); locally they skip without it, CI fails.
- Browser tests: build the Mini App first (`(cd ../miniapp && npm run build)`), then `pytest tests/browser -q`.
- Live contract tests (`tests/contract`) run only with `KARTINO_CONTRACT=1` and a Groq key.
- Mini App (from `miniapp/`): `npm ci`, `npm test`, `npm run build`.
- Details: `flashcard-project/docs/testing.md`. CI: `.github/workflows/ci.yml`.

## Coding rules

- Time: use `now_utc()` from `flashcard.utils.time`, never `datetime.now()`, `utcnow()` or `date.today()`.
  Store datetimes with `iso_z(dt)`. Use `real_now_utc()` only for what others sign or stamp.
- Wiring: handlers never call services; they call use cases in `app/`, injected by aiogram by parameter
  name. Build new services and use cases only in `composition.py` and expose them in `Core.handler_data`
  (guarded by `tests/unit/test_composition_root.py`).
- A service gets only its own collection, never the whole `cols` dict (`tests/unit/test_data_ownership.py`).
- Usage tracking: only actions that use outside resources (LLM, speech, verb scraper) count. Go through
  `QuotaPolicy` in `app/quota.py` (check before, record after success); it calls `ConsumptionService`.
  LLM metrics split into `system_api` / `user_api` by whether the user has their own key.
- MongoDB: user data, consumption included (nested under `consumption`), lives in `users`. Use `$inc`
  for counters and `$set` for fields.
- User-facing text: `i18n.get(...)` with keys in `src/flashcard/resources/locales/`. Escape dynamic
  content in bot HTML messages.
- Logging: `logger = get_logger(__name__)` from `flashcard.utils.logger`, never `print()`.
  `info` for success, `warning` for recoverable, `error` for failures.
- Docs: keep `flashcard-project/docs/` in sync with code (skill `update-docs`).
- Changelog: add user-facing changes under `## Unreleased` in `flashcard-project/CHANGELOG.md`.
- Commits: Conventional Commits (skill `conventional-commits`).

## Releases

Full guide: `flashcard-project/docs/releasing.md`.

- Ship in batches: merge reviewed work to `main`; cut at most one release candidate a day.
- Release PR sets the **final** version in `pyproject.toml` and dates the changelog heading.
- Every change ships first as a pre-release `vX.Y.Z-rc.N` on the English bot and Mini App.
- Publish the final `vX.Y.Z` on the same commit only after that rc passes on English;
  a fix found there needs a new `-rc.N`.
- Hotfix (production break or security): own branch from `main`, own rc, own release.
- Deployment lives in a separate private repo, not here.
