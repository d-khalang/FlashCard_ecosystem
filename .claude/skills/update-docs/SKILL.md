---
name: update-docs
description: Bring flashcard-project/docs/ back in sync with recent code changes (handlers, services, use cases, settings, tests). Use after changing bot code, or when asked to update or check the docs.
---

# Update docs

Updates `flashcard-project/docs/` to match the code. Run commands from the repo root.

## Doc map

| Changed code (under `flashcard-project/src/flashcard/`) | Docs to update |
|---|---|
| `telegram/handlers/` | `handlers.md` (inventory, router table) |
| `telegram/bot.py`, `composition.py` | `handlers.md` (router order), `architecture.md` (wiring, DI) |
| `app/` | `architecture.md`, `contributing.md` (use cases) |
| `services/` (incl. `algorithm/`, `llm/`) | `services.md` |
| `miniapp/` | `architecture.md`, root `docs/mini-app.md` |
| `schemas/` | `services.md` (schema tables), `configuration.md` (defaults) |
| `settings.py` | `configuration.md` (env vars) |
| `telegram/ui/`, `telegram/keyboards.py` | `handlers.md` (UI, keyboards) |
| `scheduler/` | `architecture.md` (scheduler) |
| `flashcard-project/pyproject.toml` | `configuration.md`, `flashcard-project/README.md` |
| `docker-compose.yml`, `.env.example` | `configuration.md`, root `README.md` |
| `flashcard-project/tests/` | `testing.md` |

## Steps

1. Find changes since the base branch (or the last week if on `main`):

   ```bash
   P="flashcard-project/ docker-compose.yml .env.example"
   git diff --name-only origin/main...HEAD -- $P                  # committed on this branch
   git diff --name-only HEAD -- $P                                # uncommitted
   git ls-files --others --exclude-standard -- $P                 # new, untracked
   git log --oneline --name-only --since="1 week ago" -- $P       # on main
   ```

2. For each affected doc (see map): read the matching section and the changed code, then make
   small edits only where the doc drifted. Keep the existing style.
   - `handlers.md`: handler files, router order vs `bot.py`, new commands
   - `services.md`: method signatures, schema fields, new services
   - `configuration.md`: env vars vs `settings.py`, defaults
   - `architecture.md`: package tree, wiring, scheduler
   - `contributing.md`, `README.md`: doc tables, conventions

3. If tests changed, update `testing.md`: directory tree, new files, new patterns. For counts run
   `pytest tests/ --collect-only -q` from `flashcard-project/`.

4. Report which docs changed and which sections.
