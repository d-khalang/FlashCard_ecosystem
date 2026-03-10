from __future__ import annotations
from google import genai
from google.genai import types
from typing import Dict
import itertools
import asyncio

from flashcard.schemas.expression import ExpressionCard
from flashcard.schemas.import_model import ImportResponse
from flashcard.schemas.story import StoryResponse
from flashcard.services.llm.prompts import (
    EXPRESSION_PROMPT_TEMPLATE,
    IMPORT_PROMPT_TEMPLATE,
    STORY_PROMPT_TEMPLATE,
)
from flashcard.services.llm.llm_key import LLMKeyProvider
from flashcard.utils.logger import get_logger
from flashcard.utils.tracing import observe

logger = get_logger(__name__)

class LLMService:
    def __init__(self) -> None:
        self.clients = self._create_client()
        self.client_cycle = itertools.cycle(self.clients.items())

    def _get_client(self) -> genai.Client:
        client = next(self.client_cycle)
        # Optional: log used client for debugging if we had client identifiers attached
        logger.info("Using client: %s", client[0])
        return client[1]

    def _create_client(self) -> Dict[str, genai.Client]:
        key_provider = LLMKeyProvider()
        core_keys = key_provider.get_all_core_keys()
        model_dict = {
            name: genai.Client(api_key=key)
            for name, key in core_keys.items()
        }
        logger.info("LLM clients created for: %s", list(model_dict.keys()))
        return model_dict

    async def _generate_with_retry(self, model: str, contents: str, config: types.GenerateContentConfig) -> any:
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                client = self._get_client()
                resp = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config
                )
                return resp.parsed
                
            except Exception as e:
                error_str = str(e)
                if attempt < max_attempts - 1 and any(code in error_str for code in ["503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "Internal Server Error"]):
                    wait_time = 2 ** attempt
                    logger.warning(f"Transient LLM Error ({error_str}), retrying in {wait_time}s... (Attempt {attempt + 1}/{max_attempts})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"LLM generation failed permanently after {attempt + 1} attempts: {e}")
                    raise

    @observe(name="LLMService.generate_expression_card")
    async def generate_expression_card(
        self,
        raw: str,
        *,
        level: str,
        lang1_code: str,
        lang2_code: str | None = None,
        lang1_label: str,
        lang2_label: str | None = None,
    ) -> ExpressionCard:
        # Construct dynamic language lists
        langs = [lang1_code]
        if lang2_code:
            langs.append(lang2_code)
            
        labels = [f"- {lang1_label}"]
        if lang2_code and lang2_label:
            labels.append(f"- {lang2_label}")
            
        target_langs_str = ", ".join(langs)
        target_labels_str = "\n".join(labels)

        prompt = EXPRESSION_PROMPT_TEMPLATE.format(
            raw=raw,
            level=level,
            target_langs=target_langs_str,
            target_labels=target_labels_str,
        )

        output = await self._generate_with_retry(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ExpressionCard,
            )
        )
        logger.debug(f"LLM Expression Output: {output}")
        return output

    async def parse_import_list(self, raw_text: str) -> ImportResponse:
        """
        Parses a raw text containing a list of items to import using the LLM.
        """
        prompt = IMPORT_PROMPT_TEMPLATE.format(raw_input=raw_text)
        
        output = await self._generate_with_retry(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ImportResponse,
            )
        )
        logger.debug(f"LLM Import Output: {output}")
        return output

    @observe(name="LLMService.generate_story")
    async def generate_story(
        self,
        words: list[str],
        target_lang: str = "en",
        target_level: str = "B1",
        story_length: str = "6-10 sentences"
    ) -> StoryResponse:
        """
        Generates a short story using the provided words.
        """
        prompt = STORY_PROMPT_TEMPLATE.format(
            words=", ".join(words),
            level=target_level,
            length=story_length,
            target_lang=target_lang
        )
        
        output = await self._generate_with_retry(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=StoryResponse,
            )
        )
        logger.debug(f"LLM Story Output: {output}")
        return output
