---
name: intent-framed-agent
description: >
  Prevents scope drift during implementation by creating an explicit intent
  contract before coding starts. Use when: transitioning from planning to
  execution on non-trivial coding work. Monitors for scope creep during
  implementation and closes with a resolution record.
---

# Intent Framed Agent

> Adapted from [pskoett/pskoett-ai-skills](https://github.com/pskoett/pskoett-ai-skills/tree/main/skills/intent-framed-agent)

## Purpose

This skill turns implicit intent into an explicit, trackable artifact at the
moment execution starts. It creates a lightweight intent contract, watches for
scope drift while work is in progress, and closes each intent with a short
resolution record.

## Scope

Use this skill for **coding tasks only**. It is designed for implementation work
that changes executable code.

Do not use it for:
- Broad research
- Planning-only conversations
- Documentation-only work
- Operational/admin tasks with no coding implementation

For trivial edits (simple renames, typo fixes), skip the full intent frame.

## Trigger

Activate at the planning-to-execution transition for non-trivial coding work.

Common cues:
- User says: "go ahead", "implement this", "let's start building"
- Agent is about to move from discussion into code changes

---

## Workflow

### Phase 1: Intent Capture

At execution start, emit:

```markdown
## Intent Frame #N

**Outcome:** [One sentence. What does done look like?]
**Approach:** [How we will implement it. Key decisions.]
**Constraints:** [Out-of-scope boundaries.]
**Success criteria:** [How we verify completion.]
**Estimated complexity:** [Small / Medium / Large]
```

Rules:
- Keep each field to 1–2 sentences.
- Ask for confirmation before coding:
  - `Does this capture what we are doing? Anything to adjust before I start?`
- Do not proceed until the user confirms or adjusts.

### Phase 2: Intent Monitor

During execution, monitor for drift at natural boundaries:
- Before touching a new area/file outside the stated scope
- Before starting a new logical work unit
- When current action feels tangential

Drift examples:
- Work outside stated scope
- Approach changes with no explicit pivot
- New features/refactors outside constraints
- Solving a different problem than the stated outcome

When detected, emit:

```markdown
## Intent Check #N

This looks like it may be moving outside the stated intent.

**Stated outcome:** [From active frame]
**Current action:** [What is happening]
**Question:** Is this a deliberate pivot or accidental scope creep?
```

If pivot is intentional, update the active intent frame and continue. If not,
return to the original scope.

### Phase 3: Intent Resolution

When work under the active intent ends, emit:

```markdown
## Intent Resolution #N

**Outcome:** [Fulfilled / Partially fulfilled / Pivoted / Abandoned]
**What was delivered:** [Brief actual output]
**Pivots:** [Any acknowledged changes, or None]
**Open items:** [Remaining in-scope items, or None]
```

Resolution is preferred but optional if the session ends abruptly.

---

## Multi-Intent Sessions

If multiple intents arise in one session:
- Close the current intent before opening a new one
- Number intents sequentially (#1, #2, #3)
- Each intent is independently tracked

## Guardrails

- Never silently expand scope — always surface drift explicitly
- Keep intent frames concise — they are contracts, not plans
- If uncertain whether something is drift, ask rather than assume
- Intent frames do not replace task.md or implementation plans — they are
  a lightweight execution-time overlay
