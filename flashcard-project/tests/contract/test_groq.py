"""Groq answers every LLM call the bot makes, in the shape the bot reads, with the production model."""
from __future__ import annotations

import asyncio
import os
import time

import pytest

from flashcard.app.cards import generate_card
from flashcard.schemas.expression import CardSettings
from flashcard.services.llm.llm import LLMConfig, LLMService
from flashcard.settings import Settings

# (learning language, a word to learn, the user's languages): the two production bots.
LANGUAGES = [
    ("Italian", "andare", CardSettings(level="A2", primary_language="en", secondary_language="fa")),
    ("English", "wander", CardSettings(level="B1", primary_language="fa", secondary_language=None)),
]

# Groq's free tier allows 8000 tokens a minute and one call uses about 1200, so calls are spaced out.
# A key on a paid tier can set a shorter gap.
GAP_SECONDS = float(os.environ.get("KARTINO_CONTRACT_LLM_GAP_SECONDS", "10"))
_last_call = 0.0


async def paced(call):
    """Await an LLM call no sooner than GAP_SECONDS after the previous one ended."""
    global _last_call
    wait = _last_call + GAP_SECONDS - time.monotonic()
    if wait > 0:
        await asyncio.sleep(wait)
    try:
        return await call
    finally:
        _last_call = time.monotonic()


def _llm(language: str, key_file: str) -> LLMService:
    defaults = Settings.model_fields  # the production model and limits, not this machine's settings
    config = LLMConfig(
        google_model=defaults["LLM_GOOGLE_MODEL"].default,
        groq_model=defaults["LLM_GROQ_MODEL"].default,
        groq_fallback_delay_seconds=defaults["LLM_GROQ_FALLBACK_DELAY_SECONDS"].default,
        max_attempts=defaults["LLM_MAX_ATTEMPTS"].default,
        # Longer than production: a slow answer is not a broken contract.
        request_timeout_seconds=60.0,
        key_file=key_file,
    )
    llm = LLMService(learning_language_name=language, config=config)
    assert set(llm.groq_providers) and not llm.google_providers
    return llm


@pytest.mark.parametrize("language, word, settings", LANGUAGES, ids=[l[0] for l in LANGUAGES])
async def test_a_card_and_each_of_its_sections(groq_key_file, language, word, settings):
    llm = _llm(language, groq_key_file)

    card = await paced(generate_card(llm, word, settings))

    assert card.success and card.norm and card.learning_definition and card.learning_example
    wanted = 1 + (settings.secondary_language is not None)
    assert len(card.translations) == wanted and all(line.text for line in card.translations)

    for section in ("definition", "translations", "example"):
        part = await paced(llm.generate_card_section(
            section, expression=card.norm, level=settings.level, definition=card.learning_definition,
            translations=card.translations, example=card.learning_example))
        if section == "translations":
            assert len(part.translations) == wanted and all(line.text for line in part.translations)
        else:
            assert getattr(part, section), f"no new {section}"


# What the bot (/import arguments, the command already stripped) and the Mini App send.
IMPORT_INPUTS = ["andare, la casa; mangiare\nil gatto", "andare\nmangiare\nla casa"]


@pytest.mark.parametrize("text", IMPORT_INPUTS, ids=["mixed", "lines"])
async def test_an_import_list_is_split_into_words(groq_key_file, text):
    llm = _llm("Italian", groq_key_file)

    parsed = await paced(llm.parse_import_list(text))

    assert parsed.success, parsed.log
    assert {"andare", "mangiare"} <= {value.strip().lower() for value in parsed.import_list}


async def test_a_story_uses_the_words(groq_key_file):
    llm = _llm("Italian", groq_key_file)

    story = await paced(llm.generate_story(["andare", "mare"], target_lang="en", target_level="A2"))

    assert story.paragraphs and all(paragraph.learning_text for paragraph in story.paragraphs)
