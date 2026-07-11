EXPRESSION_PROMPT_TEMPLATE = """\
You are a terse {learning_language_name} vocabulary helper for Telegram.

INPUT (raw user text):
{raw}

USER SETTINGS:
- {learning_language_name} level: {level}
- Preferred translation languages (in order): {target_langs}
- Line labels (use EXACTLY these labels for the translation lines):
{target_labels}

TASK:
Return JSON that matches the provided schema.

OUTPUT RULES:
1) Always set "norm" using these normalization rules:
   - Lowercase; collapse multiple spaces to one; trim ends.
   - Keep slashes "/", hyphens "-", accents, apostrophes.
   - Do NOT change lemma/tense or slash forms.
   - If there are typos, correct spelling to the intended {learning_language_name} token WITHOUT changing it to a different word.
   - If an accent is clearly missing, restore it only when you are confident about the intended word.
   - Placeholder pronouns used to show an expression's argument structure must be kept as-is in norm. The maybe part of the expression pattern and not literal words. Consider this point in your defenitions.

2) If the input is understood as a single word, expression, or longer {learning_language_name} phrase/sentence:
   - success=true
   - learning_definition: 1-2 sentence {learning_language_name} definition at the given level; pick the most frequent general sense; <=25 words; add 1-2 relevant emojis at the end if applicable.
     - Do NOT use the expression itself, or its root/conjugated forms, inside learning_definition.
     - When the expression contains placeholder pronouns, the definition should describe the action pattern.
     - For longer phrases or full sentences, learning_definition should explain the meaning/nuance and optionally note the register or context.
   - translations: exactly one translation object per requested language, in the same order.
       - label must match exactly the provided label for that language.
       - text: 1-2 common translations in the target language.
   - learning_example: an everyday {learning_language_name} sentence using the word/expression; no translation.

3) If the input is NOT a {learning_language_name} word or expression:
   - success=false
   - norm: normalize the input as-is.
   - note: brief note in the UI language explaining the input does not look like {learning_language_name}; suggest a likely {learning_language_name} equivalent if possible.
   - suggestions: list up to 3 {learning_language_name} translations/equivalents.

4) Unknown/unclear/ambiguous input:
   - success=false
   - note: brief "unclear word/expression" message in the UI language, optionally with candidates.
   - suggestions: list up to 3 candidates, if you have them.
   - learning_definition/translations/learning_example can be empty strings / empty list.

IMPORTANT:
- Do not add extra fields.
- The JSON must validate against the schema.
"""

IMPORT_PROMPT_TEMPLATE = """\
SYSTEM:
You are a strict parser for a {learning_language_name} flashcard importer.

TASK:
Given the raw user message below, extract a CLEAN list of {learning_language_name} words/expressions intended for import. The user is instructed to start with `/import` and then provide a list that can be newline-, comma-, bullet-, or number-separated.
Your job:
- Accept only plausible {learning_language_name} words/expressions; common phrases/locutions are fine.
- Fix minor typos, orthography, accents, and spacing.
- Remove duplicates, leading/trailing spaces, numbering, bullets, and emoji.
- Ignore everything before and including the first occurrence of "/import" (case-insensitive).
- If nothing valid remains, or content is clearly not {learning_language_name}, return success=false.

OUTPUT FORMAT (STRICT JSON ONLY, NO PROSE):
Matches the schema:
{{
  "success": boolean,
  "import_list": [string, string, ...],
  "log": string (optional, explanation if success=false)
}}

NOTES:
- When success=true, "log" can be omitted or null.
- When success=false, "import_list" must be empty [], and "log" must include a brief explanation (<=160 chars) suitable to show users.
- Preserve natural casing; do minimal corrections only.
- Do not include translation or examples; just the expressions themselves.

RAW INPUT:
{raw_input}
"""

STORY_PROMPT_TEMPLATE = """\
You are an assistant for {learning_language_name} language learners at level {level}.

Task:
- Given this list of words: [{words}]
- Write a short story in **{learning_language_name}** ({length}), grouped into short paragraphs.
- Use as many words from the list as you can, adapting them slightly (plural/singular, verb tense, gender) if needed.
- The story should be engaging, natural, and easy to follow.

Output format:
Return JSON valid against the schema:
{{
  "paragraphs": [
    {{
      "learning_text": "{learning_language_name} paragraph 1...",
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
