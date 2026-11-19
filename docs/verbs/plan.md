# Verbs page (direction B) — plan

Updated 2026-11-18. Shapes and ids: [contract.md](contract.md). Designs: canvas "Kartino — Conjugation page directions" (B · Tense cards, B · Drill).

One line: a deterministic grammar layer in the conjugator (match, variants, stem/ending), thin app routes, three Mini App screens.
Only example sentences use the LLM.

## 0. Data fix — merged, not released

Conjugator d-khalang/it-conjugator-api#2 and app d-khalang/FlashCard_ecosystem#47 are merged (standard forms; checked andare,
essere, fare, avere, dare). Still to do: release, new `it-conjugator` image on IT, clear the Mongo cache on the IT database.
Release path for IT-only changes: local test on the IT shadow bot → rc on IT (final directly if the rc needs a lot of setup).

## 1. Logic

| # | Logic | Where | Notes |
|---|-------|-------|-------|
| 1 | Match, incl. queries with spaces (`sono andato`, `mi alzo`, `me ne vado`) | conjugator | Strip clitic and auxiliary, look up the rest, report every matching slot + candidates. App: relax `VerbService.REGEX_VERB` (single inner spaces, ≤60 chars, ≤4 words) for bot and Mini App. |
| 2 | Canonical ids | conjugator v2 | `tense_id = mood-tense`, persons `1s…3p`; compound indicative tenses under `indicativo` with `compound: true`. |
| 3 | Variants per slot, several auxiliaries | conjugator v2 | Slot = list of forms; one `primary`; tags (`feminine`, `literary`…). Masculine primary, feminine variant. |
| 4 | Stem/ending + irregular flags | conjugator, deterministic | Simple forms only; compound forms expose auxiliary + participle (+ `irregular_participle`, e.g. scritto). Rule in contract §2. |
| 5 | Suggest | conjugator | Prefix over infinitives. |
| 6 | Collection verbs | conjugator `/v2/infinitives` | Infinitives only, so nouns that are also verb forms (letto, porta, sale) don't count. Checked per request (fast), nothing stored on expressions. |
| 7 | Level tenses | app | `level_tenses` from `target_level`. |
| 8 | Drill payload | app | Accepted answers, accent-stripped copies, subject prefixes to strip, hint. Client compares only (contract §4). |
| 9 | Practice results | app | `verb_practice` collection (contract §5). |
| 10 | Recent verbs | app | `users.verbs_recent`, capped at 10. |
| 11 | Examples (phase 3) | app + LLM | See §3. |
| 12 | Audio (phase 3) | speech core | Source ref with ids; reads `tts`, never `/` or `che`. |
| 13 | No Mongo cache | app | Read the conjugator directly; drop `conjugations` after release. |

## 2. Big changes

1. **Conjugator v2**: `/v2/conjugate`, `/v2/suggest`, `/v2/infinitives`; v1 stays until the bot moves.
2. **App**: VerbService on v2 without cache; use cases `home`, `suggest`, `lookup`, `drill`, `record_practice`; routes under
   `/api/v1/verbs`; `/me.features.verbs`; bot `/verb` on v2 (shows primary forms, mood labels from ids).
3. **Mini App**: Verbs tab (only with `features.verbs`), Search, Deck with tense rail, Drill, EN + IT labels.
4. **Speech core** (phase 3): `verb:` source.

## 3. Examples (phase 3)

- Own route `GET /verbs/{infinitive}/examples`: the deck never waits; the client shows examples when `ready`, retries after
  `retry_after` while `pending` (max ~5 tries).
- Only the core tenses (the 6 of `level_tenses` at A1–B1), not all 15: rare tenses gave poor sentences.
- One doc per verb with `status`: an atomic claim (`generating`, with a timeout) stops duplicate LLM calls.
- Check per sentence: contains the slot's form; for forms shared by several slots (andiamo: presente, congiuntivo, imperativo)
  the prompt names the tense and the check also requires the tense's cue where it has one (che + congiuntivo). Failed sentences are dropped.
- Retry policy: `failed` verbs get `next_try_at` = +1 day, then +7 days; max 3 attempts. A global daily cap on generations.
- Batch for the ~300 most common verbs, so most users never wait.

## 4. B refinements (usability)

- **Tense rail**: dots + line grouped by mood; the current dot stretches into a pill with the tense name; tap a dot to jump, drag to scrub.
  To mock on the canvas before the frontend builds it.
- Prev/next buttons (Telegram Desktop has no swipe; screen readers). Swipe via scroll-snap.
- Opens on the matched tense, matched form highlighted.
- Small phones: compound tenses as full-width rows; example under the card.
- Drill: keyboard-safe layout (visualViewport), Enter checks, accent keys at the caret, subject pronouns accepted ("io andrò"),
  accent-only = right with a note, Show answer = wrong, summary + retry wrong ones.
- Imperativo 5 persons; reflexive clitic required in answers; defective slots "—" and skipped in drills.
- States: loading, not found + suggestions, fuzzy ("showing andare for 'andre'"), invalid, offline. Reduced motion.

## 5. Phases

| Phase | Scope | Sessions |
|-------|-------|----------|
| 0 | Data fix release + cache clear | user + coordinator (server steps need OK) |
| 1 | Conjugator v2; app v2 client + lookup/suggest/home + no cache + regex; Search + Deck | conjugator, backend, frontend |
| 2 | Drill + practice | backend, frontend |
| 3 | Examples, audio, bot "Open in app", weak tenses | backend, frontend |

Tests: conjugator (match incl. spaces, stem/ending over a verb list, variants, suggest, infinitives-only, fixtures reproduced);
app (fixture parsing, use cases, routes, practice upsert); Mini App (fixture types, grading algorithm table, screens, one browser e2e).

## 6. Development loop

Coordinator (this session, branch `feature/verbs-page`) owns contract, fixtures and plan. Workers:
- **conjugator**: repo it-conjugator-api, own worktree from its `main`.
- **backend**: this repo, own worktree from `feature/verbs-page`, `flashcard-project/` only.
- **frontend**: this repo, own worktree from `feature/verbs-page`, `miniapp/` only.

Workers commit on their own branches and open PRs into `feature/verbs-page` (conjugator: into its `main`); the coordinator
reviews each diff against the contract. The user merges `feature/verbs-page` into `main`.
