---
description: Scan git history for code changes and update project documentation to stay in sync
---

# Update Documentation Workflow

Updates `flashcard-project/docs/` to reflect recent code changes. Covers application docs AND test documentation.

## Documentation Map

| Changed code path | Docs to update |
|-------------------|----------------|
| `telegram/handlers/` | `handlers.md` (inventory, router table) |
| `telegram/bot.py` | `handlers.md` (router order), `architecture.md` (DI kwargs) |
| `services/` | `services.md` (method tables) |
| `services/algorithm/` | `services.md` (algorithm section) |
| `services/llm/` | `services.md` (LLMService section) |
| `schemas/` | `services.md` (schema tables), `configuration.md` (defaults) |
| `settings.py` | `configuration.md` (env vars table) |
| `telegram/ui/`, `telegram/keyboards.py` | `handlers.md` (UI/keyboard sections) |
| `scheduler/` | `architecture.md` (scheduler section) |
| `pyproject.toml` | `configuration.md`, `README.md` |
| `docker-compose.yml`, `.env.example` | `configuration.md`, root `README.md` |
| `tests/` | `testing.md` (structure, counts, patterns) |

## Steps

// turbo-all

### 1. Identify Changes

Run ONE command to get all committed + uncommitted changes:

```
git -C "c:\Users\Noor\Desktop\Programming\Git\Flashcard_Bot\FlashCard-ecosystem" log --oneline --name-only --since="1 week ago" -- flashcard-project/src/ flashcard-project/tests/ flashcard-project/pyproject.toml docker-compose.yml .env.example
```

If the log is empty, check for uncommitted work:

```
git -C "c:\Users\Noor\Desktop\Programming\Git\Flashcard_Bot\FlashCard-ecosystem" diff --name-only HEAD -- flashcard-project/src/ flashcard-project/tests/ flashcard-project/pyproject.toml
```

### 2. Map Changes → Read Affected Docs → Update

Using the **Documentation Map**, identify which docs need updating. Then for each affected doc:

1. **Read the doc** — focus on the sections that correspond to the changed code
2. **Read the changed source** — use `view_file_outline` for current signatures/structure
3. **Apply surgical edits** — only update what actually drifted, keep existing style

**What to check per doc:**

- **handlers.md**: handler file count, router order (vs `bot.py`), new commands
- **services.md**: method signatures, schema field tables, new services
- **configuration.md**: env vars (vs `settings.py`), defaults (vs `defaults.py`), entry points
- **architecture.md**: package tree, DI kwargs, scheduler config
- **testing.md**: test file count, directory structure, total test count, new patterns
- **contributing.md**: doc table (any new docs?), new conventions
- **README.md**: doc table, testing section, dependency list

### 3. Test Documentation Checks

If any files under `tests/` changed, update `testing.md`:

1. Run `pytest tests/ --collect-only -q` to get the current total test count
2. Verify the directory tree in `testing.md` matches reality (new test files/directories)
3. Update per-file test counts if they changed
4. If new testing patterns were introduced, add them to the "Key Patterns" section

### 4. Summary

Provide a brief summary of:
- Which docs were updated and what sections changed
- Any new files/features that were documented
