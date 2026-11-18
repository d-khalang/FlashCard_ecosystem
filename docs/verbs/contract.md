# Verbs page — contract (v1, 2026-11-18)

The single source of truth for the shapes shared by the conjugator, the app (bot core + Mini App API) and the Mini App.
Plan and reasons: [plan.md](plan.md). Sample data: [fixtures/](fixtures/), built by [make_fixtures.py](make_fixtures.py).

**Change rule**: workers don't edit this file or the fixtures. Ask the coordinator; it updates both, then tells every session.
Each side has a test that loads the fixtures into its own types (pydantic / TypeScript) and fails on any mismatch.

## 1. Ids

No spaces, dots or `$` in any id (they are used as Mongo keys and in source refs).

- **mood**: `indicativo`, `congiuntivo`, `condizionale`, `imperativo`.
- **tense**: `presente`, `imperfetto`, `passato_remoto`, `futuro_semplice`, `passato_prossimo`, `trapassato_prossimo`,
  `trapassato_remoto`, `futuro_anteriore`, `passato`, `trapassato`.
- **tense_id** = `{mood}-{tense}`. The 15 ids, in canonical order (the order of `verb.tenses`):
  `indicativo-presente`, `indicativo-imperfetto`, `indicativo-passato_remoto`, `indicativo-futuro_semplice`,
  `indicativo-passato_prossimo`, `indicativo-trapassato_prossimo`, `indicativo-trapassato_remoto`, `indicativo-futuro_anteriore`,
  `congiuntivo-presente`, `congiuntivo-imperfetto`, `congiuntivo-passato`, `congiuntivo-trapassato`,
  `condizionale-presente`, `condizionale-passato`, `imperativo-presente`.
  Compound indicative tenses live under `indicativo` with `compound: true` (v1's `tempi composti` mood is gone).
- **person**: `1s 2s 3s 1p 2p 3p`. Imperativo has `2s 3s 1p 2p 3p` (`3s` = Lei, `3p` = Loro).
  Display labels (io, tu, lui/lei, che io, (Lei)…) belong to the client's i18n, never to the data.

## 2. Verb object (conjugator v2 → app → Mini App unchanged)

```jsonc
{
  "infinitive": "andare",
  "pronominal": null,            // null, or the clitic suffix: "si", "ne", "sene", "ci", "cela", ...
  "auxiliaries": [{"verb": "essere", "primary": true, "note": null}],   // list: some verbs take both
  "principal_forms": {"gerund": "andando", "past_participle": "andato", "present_participle": "andante"},  // each may be null (essere has no present participle)
  "irregular": true,             // any form differs from the regular paradigm
  "data_version": "2026-11-13",  // build date of the conjugator data; informative
  "tenses": [Tense]              // canonical order; a tense with no forms at all is omitted
}
```

**Tense**: `{"id", "mood", "tense", "compound": bool, "slots": [{"person", "forms": [Form]}]}`.
A slot with `forms: []` means the form doesn't exist (defective verb); the client shows "—" and the drill skips it.

**Form** — a slot always holds a list (variants are coming in the data):

```jsonc
{
  "text": "vado",        // what is shown; never contains "/" or "(…)"
  "primary": true,       // exactly one primary per slot
  "tags": [],            // e.g. "feminine", "literary", "regional", "archaic", "colloquial"
  "tts": "vado",         // what speech reads; clean text
  "irregular": true,     // text != the regular-paradigm form
  "parts": SimpleParts | CompoundParts
}
```

- **SimpleParts**: `{"kind": "simple", "clitic": null|"mi"|"me ne"…, "stem", "ending", "enclitic": null|"ti"|"ttene"…, "irregular_stem": bool, "irregular_ending": bool}`.
  `clitic + " " + stem + ending + enclitic == text` (without the space when clitic is null; `l'` joins without a space).
  `enclitic` holds pronouns attached after the verb, mostly in imperatives: `svegli|a|ti`, `v|a|ttene` (doubled consonant
  included), `andiam|o|cene`. Stem, ending and the irregular flags are worked out on the base form (sveglia, va).
- **CompoundParts**: `{"kind": "compound", "clitic", "auxiliary_verb": "essere"|"avere", "auxiliary": "sono", "participle": "andato", "irregular_participle": bool}`.
  No stem/ending on compound forms. Gender: the masculine form is primary, the feminine one is a variant tagged `feminine`.
  Two auxiliaries → one variant per auxiliary.
- **Curated variants**: until the data carries them, the conjugator adds the short tu imperatives `va'`, `da'`, `fa'`, `sta'`, `di'`
  as untagged, non-primary variants of the tu imperative (vai, dai, fai, stai stay primary; for dire, add `di'` only if the data lacks it).

### Stem and ending (deterministic; reference: `make_fixtures.py`)

1. Build the regular form from the verb's class (-are / -ere / -ire / -ire with -isc-), with the spelling rules
   (-care/-gare add h before e/i; -ciare/-giare/-sciare drop the i before e/i; -iare: one i).
2. Candidate endings = the regular ending for this slot + the core endings of this tense and person across classes
   (e.g. futuro: ò ai à emo ete anno; presente 3p: ano ono).
3. `ending` = the longest candidate the form ends with (and is shorter than the form); none fits → `ending = ""`.
   `stem` = the rest.
4. `irregular_stem` = stem ≠ regular stem; `irregular_ending` = ending ≠ regular ending; `irregular` = text ≠ regular form.
   Results for andare: `vad|o*`, `v|a*`, `vanno|*`, `andr|ò*`, `and|iamo`.

### Match

```jsonc
{"query": "vado", "kind": "infinitive" | "form" | "fuzzy",
 "slots": [{"tense_id": "indicativo-presente", "person": "1s"}],   // every slot whose forms contain the query; [] for infinitive/fuzzy
 "candidates": ["andarsene"]}                                         // other infinitives the query could mean
```

Queries may hold spaces: compound forms (`sono andato`), clitic forms (`mi alzo`, `me ne vado`). Max 60 chars, at most 4 words.

## 3. Conjugator v2 (service to service, header `X-API-Key`)

| Route | Answer |
|-------|--------|
| `GET /v2/conjugate?q=` | 200 `{"match", "verb"}` · 404 `{"error": {"code": "verb_not_found", "message"}, "suggestions": [infinitive]}` |
| `GET /v2/suggest?q=&limit=8` | 200 `{"items": [infinitive]}`: prefix match on infinitives, most common first, pronominal verbs right after their base; `q` shorter than 2 → `[]`. Suggest fixtures show the shape, not the exact list |
| `POST /v2/infinitives` `{"words": [...]}` (≤ 500) | 200 `{"infinitives": {word: infinitive or null}}`: **infinitives only** (andare, svegliarsi, andarsene), never inflected forms (letto, porta, sale → null), multi-word → null |

v1 `/conjugate` stays until the bot moves to v2. Fixtures: `fixtures/conjugator/`.

## 4. Mini App API (prefix `/api/v1/verbs`, Telegram auth as today)

| Route | Answer | Fixture |
|-------|--------|---------|
| `GET /home` | `{"recent": [infinitive], "collection": [{"infinitive", "expression_id", "meaning"}]}` | `home.json` |
| `GET /suggest?q=` | `{"items": [infinitive]}`; own rate limit | `suggest-and.json` |
| `GET /lookup?q=` | `{"status": "found", "match", "verb", "level_tenses": [tense_id], "meaning": str or null, "in_collection": bool}` · `{"status": "not_found", "query", "suggestions"}` · `{"status": "invalid", "query"}` | `lookup-*.json` |
| `GET /{infinitive}/drill/{tense_id}` | Drill (below); 404 if the verb or tense doesn't exist | `drill-*.json` |
| `POST /practice` | body `{"infinitive", "tense_id", "score", "out_of", "missed": [person]}` → 204 | `practice-request.json` |
| `GET /{infinitive}/examples?lang=` (phase 3) | `{"status": "ready", "examples": [{"tense_id", "person", "text", "translation"}]}` · `{"status": "pending", "retry_after": s}` · `{"status": "unavailable"}` | `examples-*.json` |

- `lookup` records the verb in the user's recent list and counts `verb_lookups`; it never calls the LLM.
- `level_tenses`: the tenses that matter at the user's `target_level` (unordered set, canonical ids). The client keeps canonical order and may fold the others under "More tenses".
- Deck opens on `match.slots[0].tense_id` when present, else `indicativo-presente`; matched slots are highlighted.
- `/me` gains `"features": {"verbs": bool}` (true when the bot's language has conjugation). Verbs tab only when true.
- Errors other than the statuses above use the existing `{"error": {"code", "message"}}` shape.

### Drill

```jsonc
{"infinitive": "andare", "tense_id": "indicativo-futuro_semplice",
 "strip_prefixes": ["che io", "...", "io", "tu", "lui", "lei", "noi", "voi", "loro", "che"],   // longest first
 "items": [{"person": "1s", "primary": "andrò",
            "accepted": [{"text": "andrò", "note": null}],          // note: null | "feminine" | "variant"
            "accepted_plain": ["andro"],                             // accepted, accents removed
            "hint": {"kind": "irregular_stem", "stem": "andr"} }]}   // or {"kind": "irregular_form"} or null
```

Client grading (the whole algorithm; Italian rules stay on the server):
1. `n` = input → NFC, lowercase, trim, collapse spaces, `’` → `'`.
2. If `n` starts with one of `strip_prefixes` followed by a space, drop it (first match in list order).
3. `n` in `accepted[].text` → **right** (show the note if not null). Else accents removed (NFD, drop U+0300–U+036F) in
   `accepted_plain` → **accent** (right, with "accent: {primary}"). Else **wrong**.
Items come in person order; empty slots are already left out. The clitic of pronominal verbs is part of the answer (`mi alzo`).

## 5. Storage (app, in the language's own database)

- **`verb_practice`** (new collection; unique index `user_id + infinitive`, index `user_id + updated_at`):
  `{"user_id", "infinitive", "tenses": {tense_id: {"attempts", "last_score", "out_of", "best_score", "last_at", "missed": [person]}}, "updated_at"}`.
  One upsert per finished drill (`$set` on `tenses.<tense_id>`, `$inc` attempts). Deleted with the user's data.
- **Recent verbs**: `users.verbs_recent`: array of infinitives, newest first, max 10 (`$pull` then `$push` with `$position: 0, $slice: 10`).
- **`verb_examples`** (phase 3, shared by all users): `{"infinitive", "status": "generating"|"ready"|"failed", "examples": {tense_id: {"person", "text"}}, "translations": {lang: {tense_id: text}}, "model", "attempts", "next_try_at", "updated_at"}`.
- The Mongo `conjugations` cache is removed: the app reads the conjugator directly.

## 6. Audio (phase 3)

Speech source ref `verb:{infinitive}:{tense_id}:{person}:{form_index}`; the resolver reads `forms[form_index].tts`.
Ids contain no `:`, so the ref splits cleanly.

## 7. Who owns what

| Session | Owns | Reads |
|---------|------|-------|
| conjugator (repo it-conjugator-api) | §2, §3 | fixtures/conjugator |
| backend (flashcard-project) | §4 server side, §5, §6 | fixtures/conjugator (as the client of v2), fixtures/miniapp |
| frontend (miniapp) | §4 client side, grading in §4 | fixtures/miniapp |
| coordinator | this file, fixtures, plan | everything |
