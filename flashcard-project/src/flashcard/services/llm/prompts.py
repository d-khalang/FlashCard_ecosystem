EXPRESSION_PROMPT_TEMPLATE = """\
You are a terse Italian vocabulary helper for Telegram.

INPUT (raw user text):
{raw}

USER SETTINGS:
- Italian level: {level}
- Preferred translation languages (exact order): {lang1_code}, {lang2_code}
- Line labels (use EXACTLY these labels):
  1) {lang1_label}
  2) {lang2_label}

TASK:
Return JSON that matches the provided schema.

OUTPUT RULES:
1) Always set "norm" using these normalization rules:
   - Lowercase; collapse multiple spaces to one; trim ends.
   - Keep slashes "/", hyphens "-", accents, apostrophes.
   - Do NOT change lemma/tense or slash forms.
   - If there are typos, correct spelling to the intended Italian token WITHOUT changing it to a different word.

2) If the input is understood:
   - success=true
   - def_it: 1–2 sentences Italian definition at the given level; pick the most frequent general sense; <=20 words.
   - translations: exactly 2 objects, in the same order as user settings:
       - label must match exactly the provided label.
       - text: 1–2 common translations in the target language.
   - example_it: an everyday Italian sentence using the word/expression (Italian only; no translation).

3) Unknown/unclear/ambiguous input:
   - success=false
   - note_it: "Parola non chiara" OR "Parola non chiara; forse intendevi: X, Y, Z."
   - suggestions: list up to 3 candidates (strings), if you have them.
   - def_it/translations/example_it can be empty strings / empty list.

IMPORTANT:
- Do not add extra fields.
- The JSON must validate against the schema.
"""

IMPORT_PROMPT_TEMPLATE = """\
SYSTEM:
You are a strict parser for an Italian flashcard importer.

TASK:
Given the raw user message below, extract a CLEAN list of Italian words/expressions intended for import. The user is instructed to start with `/import` and then provide a list that can be newline-, comma-, bullet-, or number-separated.
Your job:
- Accept only plausible Italian words/expressions (common phrases/locutions are fine).
- Fix minor typos (orthography/accents/spaces).
- Remove duplicates, leading/trailing spaces, and numbering/bullets/emoji.
- Ignore everything before and including the first occurrence of "/import" (case-insensitive).
- If nothing valid remains, or content is clearly not Italian, return success=false.

OUTPUT FORMAT (STRICT JSON ONLY, NO PROSE):
Matches the schema:
{{
  "success": boolean,
  "import_list": [string, string, ...],
  "log": string (optional, explanation if success=false)
}}

NOTES:
- When success=true, "log" can be omitted or null.
- When success=false, "import_list" must be empty [], and "log" must include a brief explanation (≤160 chars) suitable to show users.
- Preserve natural casing; do minimal corrections only.
- Do not include translation or examples; just the expressions themselves.

RAW INPUT:
{raw_input}
"""

STORY_PROMPT_TEMPLATE = """\
You are an assistant for Italian language learners at level {level}.

Task:
- Given this list of words: [{words}]
- Write a short story in **Italian** ({length}), grouped into short paragraphs.
- Use as many words from the list as you can, adapting them slightly (plural/singular, verb tense, gender) if needed.
- The story should be engaging, natural, and easy to follow.

Output format:
Return JSON valid against the schema:
{{
  "paragraphs": [
    {{
      "italian_text": "Italian paragraph 1...",
      "translation": "Translation of paragraph 1..."
    }},
    ...
  ]
}}

Rules:
- Do NOT explain vocabulary, just use it in context.
- Keep the translations faithful and simple.
- Target language for translation is: {target_lang}.
"""
