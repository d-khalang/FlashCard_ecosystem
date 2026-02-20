from __future__ import annotations
from google import genai
from google.genai import types
from typing import Dict
import itertools

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
        model_dict = {
            "mey": genai.Client(api_key=key_provider.get_core_key('mey')),
            "ako": genai.Client(api_key=key_provider.get_core_key('ako')),
        }
        logger.info("LLM clients created: %s", model_dict)
        return model_dict

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
        
        # logger.info("LLM Prompt: %s", prompt)

        client = self._get_client()
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ExpressionCard,
            )
        )

        # parsed is and ExpressionCard instance (validated)
        output = resp.parsed
        logger.info("LLM output: %s", output)
        return output

    async def parse_import_list(self, raw_text: str) -> ImportResponse:
        """
        Parses a raw text containing a list of items to import using the LLM.
        """
        prompt = IMPORT_PROMPT_TEMPLATE.format(raw_input=raw_text)
        
        client = self._get_client()
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ImportResponse,
            )
        )
        
        output = resp.parsed
        logger.info(f"LLM Import Output: {output}")
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
        
        client = self._get_client()
        resp = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=StoryResponse,
            )
        )
        
        output = resp.parsed
        logger.info("LLM Story Output generated")
        return output
