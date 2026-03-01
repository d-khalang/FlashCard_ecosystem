---
name: conventional-commits
description: >
  Enforces standardized commit messages following the Conventional Commits
  specification. Use when: making any git commit. Generates structured commit
  messages with type, scope, and description for consistent project history
  and potential automated versioning.
---

# Conventional Commits

## Purpose

Enforce the [Conventional Commits](https://www.conventionalcommits.org/)
specification for all git commits in this project. This enables:

- Consistent, machine-readable commit history
- Automated semantic versioning (future)
- Easier code review and change tracking
- Clear intent for every commit

## Commit Message Format

```
type(scope): short description

[optional body]

[optional footer]
```

### Rules

1. **Subject line** must be imperative mood, lowercase, no period at end
2. **Max 72 characters** for the subject line
3. **Single type per commit** — do not mix types (e.g., feat + fix)
4. **Scope** should match a project architecture component
5. **Body** explains *what* and *why*, not *how*
6. **Breaking changes** must include `BREAKING CHANGE:` in the footer

## Types

| Type | When to Use |
|------|-------------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `docs` | Documentation only |
| `style` | Formatting, whitespace, missing semicolons (no logic change) |
| `perf` | Performance improvement |
| `chore` | Maintenance, dependencies, tooling, CI/CD |
| `ci` | CI/CD pipeline changes |
| `build` | Build system or external dependency changes |
| `revert` | Reverting a previous commit |

## Project Scopes

Use these scopes matching the FlashCard architecture:

| Scope | Covers |
|-------|--------|
| `bot` | Telegram bot setup, dispatcher, main bot.py |
| `handlers` | Telegram command/callback/message handlers |
| `services` | Business logic layer (expression, user, verb, LLM) |
| `schemas` | Pydantic models, data validation |
| `algorithm` | Spaced repetition, grading, priority |
| `api` | FastAPI layer, routes, lifecycle |
| `db` | MongoDB connection and queries |
| `scheduler` | Background scheduler loop |
| `ui` | Telegram message formatters, keyboards |
| `middleware` | aiogram middlewares, tracing |
| `i18n` | Internationalization, locale files |
| `config` | Settings, environment, .env |
| `docker` | Dockerfile, docker-compose |
| `deps` | Dependencies, pyproject.toml |
| `scraper` | WR Scraper module |

## Examples

```
feat(handlers): add /export command for flashcard collection

fix(algorithm): correct EWMA calculation for grade=0 edge case

refactor(services): extract LLM prompt building into dedicated module

test(scheduler): add unit tests for review push timing logic

docs(architecture): update router registration order table

chore(deps): bump aiogram to 3.4.0

fix(middleware): prevent trace ID leak in error responses

feat(i18n): add Italian locale strings for review flow

style(handlers): apply consistent import ordering across all handlers
```

## Commit Workflow

1. **Stage changes** that belong to a single logical unit
2. **Determine type** from the table above
3. **Choose scope** from the project scopes
4. **Write subject** in imperative mood: "add", "fix", "update", not "added", "fixed"
5. **Add body** if the change isn't self-explanatory
6. **Add footer** for breaking changes or issue references

## Security

Before committing, verify:
- No secrets, API keys, or tokens in the diff
- No `.env` files with real values
- No hardcoded credentials
