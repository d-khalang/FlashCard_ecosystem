from __future__ import annotations
import logging
from google import genai
from google.genai import types
from typing import Dict

from flashcard.schemas.expression import ExpressionCard
from flashcard.services.llm.prompts import EXPRESSION_PROMPT_TEMPLATE
from flashcard.services.llm.llm_key import LLMKeyProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self) -> None:
        self.clients = self._create_client()

    def _create_client(self) -> Dict[str, genai.Client]:
        key_provider = LLMKeyProvider()
        model_dict = {
            "mey": genai.Client(api_key=key_provider.get_core_key('mey')),
        }
        logger.info("LLM clients created: %s", model_dict)
        return model_dict

    async def generate_expression_card(
        self,
        raw: str,
        *,
        level: str,
        lang1_code: str,
        lang2_code: str,
        lang1_label: str,
        lang2_label: str,
    ) -> ExpressionCard:
        prompt = EXPRESSION_PROMPT_TEMPLATE.format(
            raw=raw,
            level=level,
            lang1_code=lang1_code,
            lang2_code=lang2_code,
            lang1_label=lang1_label,
            lang2_label=lang2_label,
        )
        
        resp = self.clients["mey"].models.generate_content(
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