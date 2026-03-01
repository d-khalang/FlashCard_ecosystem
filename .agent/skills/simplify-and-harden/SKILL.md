---
name: simplify-and-harden
description: >
  Post-completion code quality and security review. Activates after the agent
  finishes a non-trivial coding task. Performs two focused passes: (1) Simplify
  to reduce complexity, (2) Harden to close security and resilience gaps, plus
  a micro documentation pass for non-obvious decisions.
---

# Agent Skill: Simplify & Harden

> Adapted from [pskoett/pskoett-ai-skills](https://github.com/pskoett/pskoett-ai-skills/tree/main/skills/simplify-and-harden) (v0.1.0)

| Field         | Value                          |
|---------------|--------------------------------|
| Skill ID      | `simplify-and-harden`          |
| Trigger       | Post-completion hook           |
| Category      | Code Quality / Security        |
| Priority      | Recommended                    |

## Rationale

When a coding agent completes a task, it holds peak contextual understanding of
the problem, the solution, and the tradeoffs it made. This context degrades
immediately — the next task wipes the slate. Simplify & Harden exploits that
peak context window to perform two focused review passes before the agent moves
on.

Most agents solve the ticket and stop. This skill turns "done" into "done well."

## Trigger Conditions

The skill activates automatically when ALL of the following are true:

- The agent has completed its primary coding task
- The diff contains a non-trivial code change (see below)
- The skill has not already run on this task (no re-entry loops)

**Non-trivial code change definition:**

Treat a diff as non-trivial when it satisfies BOTH:

1. It touches at least one executable source file (`.py`, `.sh`, etc.)
2. It includes either:
   - At least 10 changed non-comment, non-whitespace lines, OR
   - At least one high-impact logic change (auth checks, input validation,
     data access/query logic, external API calls, file path handling, or
     concurrency control)

The skill does NOT activate when:
- The change is documentation-only
- The change is tests-only
- The change is generated files (lockfiles, build artifacts)
- The user explicitly skips it

## Scope Constraints

**Hard rule: Only touch code modified in this task.**

The agent MUST NOT:
- Refactor adjacent code it did not modify
- Pursue "while I'm here" improvements outside the diff
- Introduce new dependencies or architectural changes
- Make speculative fixes based on patterns noticed elsewhere

The agent SHOULD flag out-of-scope concerns in the summary output rather than
acting on them.

**Budget limits:**
- Maximum additional changes: 20% of the original diff size (measured in lines)
- If the limit is hit, stop and output what you have with a `budget_exceeded` flag

---

## Pass 1: Simplify

**Objective:** Reduce unnecessary complexity introduced during implementation.

**Default posture: simplify, don't restructure.** The primary goal is
lightweight cleanup — removing noise, tightening naming, killing dead code.
Bias heavily toward cosmetic fixes that make the code cleaner without changing
its structure.

**Fresh-eyes start (mandatory):** Before making any edits, re-read all code
added or modified in this task with "fresh eyes" and actively look for obvious
bugs, errors, confusing logic, brittle assumptions, naming issues, and missed
hardening opportunities.

The agent asks:

> "Now that I understand the full solution, is there a simpler way to express this?"

### Review Checklist

1. **Dead code and scaffolding** — Debug logs, commented-out attempts, unused
   imports, temporary variables from iteration? Remove them.

2. **Naming clarity** — Do function names, variables, and parameters make sense
   when read fresh? Rename if needed.

3. **Control flow** — Can nested conditionals be flattened? Can early returns
   replace deep nesting? Tighten them.

4. **API surface** — Did I expose more than necessary? Could public
   methods/functions be private? Reduce visibility.

5. **Over-abstraction** — Classes, interfaces, or wrappers that aren't justified
   by the current scope? Flag, but don't restructure unless the win is
   significant.

6. **Consolidation** — Logic spread across multiple functions/files when it
   could live in one place? Flag, but only propose if duplication is egregious.

### Simplify Actions

- **Cosmetic fix** (dead code, unused imports, naming, control flow, visibility)
  — applied automatically within budget.
- **Refactor** (consolidation, restructuring, abstraction changes) — proposed
  ONLY when genuinely necessary. Bar: "Would a senior engineer say the current
  state is clearly wrong, not just imperfect?"

**Refactor Stop Hook (mandatory):**

Any refactor triggers a prompt. The agent MUST:
1. Describe what it wants to change and why
2. Show before/after
3. Wait for explicit approval before applying

Cosmetic fixes do not trigger the stop hook.

---

## Pass 2: Harden

**Objective:** Close security and resilience gaps while the agent still
understands the code's intent.

The agent asks:

> "If someone malicious saw this code, what would they try?"

### Review Checklist

1. **Input validation** — All external inputs validated before use? Check for
   type coercion, missing bounds checks, unconstrained string lengths.
   Especially important for Telegram message handlers and callback data.

2. **Error handling** — Catch blocks specific? Errors logged with context but
   without leaking sensitive data? Any swallowed exceptions?

3. **Injection vectors** — Check for command injection, path traversal, NoSQL
   injection (MongoDB queries), and template injection in any code building
   strings from external input.

4. **Authentication and authorization** — Do new handlers enforce proper user
   checks? Are there privilege escalation risks in admin commands?

5. **Secrets and credentials** — Hardcoded secrets, API keys, tokens? Are
   connection strings parameterized? Check for credentials in log output.

6. **Data exposure** — Does error output, logging, or bot responses leak
   internal state, stack traces, database schemas, or PII?

7. **Dependency risk** — New dependencies introduced? Well-maintained, properly
   versioned, free of known vulnerabilities?

8. **Race conditions** — For async code: are shared resources properly handled?
   TOCTOU vulnerabilities in MongoDB operations?

### Harden Actions

- **Patch** (adding validation, escaping output, removing hardcoded secrets) —
  applied automatically within budget.
- **Security refactor** (restructuring auth flow, replacing vulnerable patterns)
  — ALWAYS requires human approval.

The same Refactor Stop Hook applies. Security refactors include severity and
attack vector context.

---

## Pass 3: Document (Micro-pass)

**Objective:** Capture non-obvious decisions while the agent still remembers why
it made them.

This is deliberately lightweight — not a documentation pass, just decision
capture.

### Rules

1. Add a brief inline comment only when:
   - The code does something surprising or counter-intuitive
   - A workaround is in place for a known issue
   - A design tradeoff was made that isn't obvious from the code

2. Do NOT comment:
   - What the code does (let the code speak)
   - Standard patterns or idioms
   - Anything obvious from naming

3. Format: `# REASON: <why this approach was chosen>`

---

## Self-Improvement Integration

After each run, findings feed into the `self-improvement` skill:

1. Normalize findings into pattern keys (e.g., `simplify.dead_code`,
   `harden.input_validation`)
2. Log or update entries in `.learnings/LEARNINGS.md`
3. Mark patterns as promotion-ready when they recur (≥3 occurrences across ≥2
   distinct tasks within 30 days)
4. Promote recurring patterns into project memory

## Core Invariants

1. **Scope lock** — only files modified in the current task
2. **Budget cap** — 20% max additional diff
3. **Simplify-first posture** — cleanup is the default, refactoring is the exception
4. **Refactor stop hook** — structural changes always require human approval
5. **Three passes** — simplify, harden, document (in that order)
