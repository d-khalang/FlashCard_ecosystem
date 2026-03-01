---
name: self-improvement
description: >
  Captures learnings, errors, and corrections to enable continuous improvement.
  Use when: (1) A command or operation fails unexpectedly, (2) User corrects
  the agent's approach, (3) User requests a missing capability, (4) An external
  API or tool fails, (5) A better approach is discovered for a recurring task.
---

# Self-Improvement Skill

> Adapted from [pskoett/pskoett-ai-skills](https://github.com/pskoett/pskoett-ai-skills/tree/main/skills/self-improvement) (v1.0.11)

Log learnings and errors to markdown files for continuous improvement. Important
learnings get promoted to project memory.

## Quick Reference

| Situation | Action |
|-----------|--------|
| Command/operation fails | Log to `.learnings/ERRORS.md` |
| User corrects you | Log to `.learnings/LEARNINGS.md` with category `correction` |
| User wants missing feature | Log to `.learnings/FEATURE_REQUESTS.md` |
| API/external tool fails | Log to `.learnings/ERRORS.md` with integration details |
| Knowledge was outdated | Log to `.learnings/LEARNINGS.md` with category `knowledge_gap` |
| Found better approach | Log to `.learnings/LEARNINGS.md` with category `best_practice` |
| Similar to existing entry | Link with `**See Also**`, consider priority bump |
| Broadly applicable learning | Promote to project memory files |

## Setup

Create `.learnings/` directory in project root if it doesn't exist:

```bash
mkdir -p .learnings
```

## Logging Format

### Learning Entry

Append to `.learnings/LEARNINGS.md`:

```markdown
## [LRN-YYYYMMDD-XXX] category

**Logged**: ISO-8601 timestamp
**Priority**: low | medium | high | critical
**Status**: pending
**Area**: telegram | services | api | schemas | algorithm | db | infra | tests | docs | config

### Summary
One-line description of what was learned

### Details
Full context: what happened, what was wrong, what's correct

### Suggested Action
Specific fix or improvement to make

### Metadata
- Source: conversation | error | user_feedback
- Related Files: path/to/file.ext
- Tags: tag1, tag2
- See Also: LRN-20260101-001 (if related to existing entry)

---
```

### Error Entry

Append to `.learnings/ERRORS.md`:

```markdown
## [ERR-YYYYMMDD-XXX] skill_or_command_name

**Logged**: ISO-8601 timestamp
**Priority**: high
**Status**: pending
**Area**: telegram | services | api | schemas | algorithm | db | infra | tests | docs | config

### Summary
Brief description of what failed

### Error
```
Actual error message or output
```

### Context
- Command/operation attempted
- Input or parameters used
- Environment details if relevant

### Suggested Fix
If identifiable, what might resolve this

### Metadata
- Reproducible: yes | no | unknown
- Related Files: path/to/file.ext
- See Also: ERR-20260101-001 (if recurring)

---
```

### Feature Request Entry

Append to `.learnings/FEATURE_REQUESTS.md`:

```markdown
## [FEAT-YYYYMMDD-XXX] capability_name

**Logged**: ISO-8601 timestamp
**Priority**: medium
**Status**: pending
**Area**: telegram | services | api | schemas | algorithm | db | infra | tests | docs | config

### Requested Capability
What the user wanted to do

### User Context
Why they needed it, what problem they're solving

### Complexity Estimate
simple | medium | complex

### Suggested Implementation
How this could be built, what it might extend

### Metadata
- Frequency: first_time | recurring
- Related Features: existing_feature_name

---
```

## ID Generation

Format: `TYPE-YYYYMMDD-XXX`
- TYPE: `LRN` (learning), `ERR` (error), `FEAT` (feature)
- YYYYMMDD: Current date
- XXX: Sequential number (e.g., `001`, `002`)

## Resolving Entries

When an issue is fixed, update the entry:

1. Change `**Status**: pending` → `**Status**: resolved`
2. Add resolution block after Metadata:

```markdown
### Resolution
- **Resolved**: 2026-03-01T12:00:00Z
- **Commit/PR**: abc123 or #42
- **Notes**: Brief description of what was done
```

Other status values:
- `in_progress` — Actively being worked on
- `wont_fix` — Decided not to address (add reason)
- `promoted` — Elevated to project memory

## Promoting to Project Memory

When a learning is broadly applicable, promote it to permanent project memory.

### When to Promote

- Learning applies across multiple modules
- Knowledge any contributor (human or AI) should know
- Prevents recurring mistakes
- Documents project-specific conventions

### How to Promote

1. **Distill** the learning into a concise rule or fact
2. **Add** to the appropriate project memory file
3. **Update** original entry status to `promoted`

### Promotion Examples

**Learning** (verbose):
> Project uses aiogram 3.x dispatcher. Handler parameter names must exactly
> match the keyword arguments passed to `dp.start_polling()` for DI to work.

**In project memory** (concise):
```markdown
## aiogram DI
- Handler parameter names must exactly match kwargs in dp.start_polling()
- Services are injected by name, not by type
```

## Detection Triggers

Automatically log when you notice:

**Corrections** (→ learning with `correction` category):
- "No, that's not right..."
- "Actually, it should be..."
- "You're wrong about..."

**Feature Requests** (→ feature request):
- "Can you also..."
- "I wish you could..."
- "Is there a way to..."

**Knowledge Gaps** (→ learning with `knowledge_gap` category):
- User provides information you didn't know
- Documentation referenced is outdated
- API behavior differs from understanding

**Errors** (→ error entry):
- Command returns non-zero exit code
- Exception or stack trace
- Unexpected output or behavior
- Timeout or connection failure

## Priority Guidelines

| Priority | When to Use |
|----------|-------------|
| `critical` | Blocks core functionality, data loss risk, security issue |
| `high` | Significant impact, affects common workflows, recurring issue |
| `medium` | Moderate impact, workaround exists |
| `low` | Minor inconvenience, edge case, nice-to-have |

## Area Tags

Use to filter learnings by codebase region:

| Area | Scope |
|------|-------|
| `telegram` | Handlers, middlewares, keyboards, UI formatters, FSM states |
| `services` | Business logic, LLM integration, algorithm, tracing |
| `api` | FastAPI layer, routes, lifecycle hooks |
| `schemas` | Pydantic models, data validation |
| `algorithm` | Spaced repetition, grading, priority |
| `db` | MongoDB connection, queries, collections |
| `infra` | Docker, deployment, CI/CD |
| `tests` | Test files, fixtures, mocks |
| `docs` | Documentation, READMEs |
| `config` | Settings, environment, .env |

## Recurring Pattern Detection

If logging something similar to an existing entry:

1. **Search first**: Check `.learnings/` for related entries
2. **Link entries**: Add `**See Also**: ERR-20260101-001` in Metadata
3. **Bump priority** if issue keeps recurring
4. **Consider systemic fix**: Recurring issues often indicate:
   - Missing documentation (→ promote to project memory)
   - Missing automation (→ create a workflow)
   - Architectural problem (→ create tech debt ticket)

## Best Practices

1. **Log immediately** — context is freshest right after the issue
2. **Be specific** — future agents need to understand quickly
3. **Include reproduction steps** — especially for errors
4. **Link related files** — makes fixes easier
5. **Suggest concrete fixes** — not just "investigate"
6. **Use consistent categories** — enables filtering
7. **Promote aggressively** — if in doubt, promote
8. **Review regularly** — stale learnings lose value
