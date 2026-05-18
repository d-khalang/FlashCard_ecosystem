from __future__ import annotations

import asyncio
import copy
import itertools
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Generic, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from flashcard.schemas.expression import ExpressionCard
from flashcard.schemas.import_model import ImportResponse
from flashcard.schemas.story import StoryResponse
from flashcard.services.llm.llm_key import LLMKeyProvider
from flashcard.services.llm.prompts import (
    EXPRESSION_PROMPT_TEMPLATE,
    IMPORT_PROMPT_TEMPLATE,
    STORY_PROMPT_TEMPLATE,
)
from flashcard.utils.logger import get_logger
from flashcard.utils.tracing import observe

logger = get_logger(__name__)

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
FallbackNotifier = Callable[[], Awaitable[None]]

GOOGLE_MODEL = "gemini-2.5-flash-lite"
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_TIMEOUT_SECONDS = 3.0
MAX_ATTEMPTS = 2
TRANSIENT_ERROR_MARKERS = (
    "503",
    "429",
    "UNAVAILABLE",
    "RESOURCE_EXHAUSTED",
    "Internal Server Error",
    "rate_limit",
    "timeout",
)


@dataclass(frozen=True)
class LLMProviderStrategy(Generic[ResponseModel]):
    name: str
    provider: str
    client: Any

    async def generate(
        self,
        *,
        model: str,
        contents: str,
        response_schema: type[ResponseModel],
    ) -> ResponseModel:
        raise NotImplementedError


class GoogleGenAIProvider(LLMProviderStrategy[ResponseModel]):
    async def generate(
        self,
        *,
        model: str,
        contents: str,
        response_schema: type[ResponseModel],
    ) -> ResponseModel:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
        )

        def call() -> ResponseModel:
            resp = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            return resp.parsed

        return await asyncio.to_thread(call)


class GroqProvider(LLMProviderStrategy[ResponseModel]):
    async def generate(
        self,
        *,
        model: str,
        contents: str,
        response_schema: type[ResponseModel],
    ) -> ResponseModel:
        schema = strict_json_schema(response_schema)

        def call() -> ResponseModel:
            resp = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": contents}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_schema.__name__,
                        "schema": schema,
                        "strict": True,
                    },
                },
            )
            content = resp.choices[0].message.content
            return response_schema.model_validate_json(content)

        return await asyncio.to_thread(call)


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """
    Groq strict JSON schema requires every object property to be listed in
    required, including nullable fields that are optional in Python.
    """
    schema = copy.deepcopy(model.model_json_schema())
    _require_all_properties(schema)
    return schema


def _require_all_properties(node: Any) -> None:
    if isinstance(node, dict):
        node.pop("default", None)

        if node.get("type") == "object" and isinstance(node.get("properties"), dict):
            node["required"] = list(node["properties"].keys())
            node["additionalProperties"] = False

        for value in node.values():
            _require_all_properties(value)
    elif isinstance(node, list):
        for item in node:
            _require_all_properties(item)


class LLMService:
    def __init__(self) -> None:
        self.providers = self._create_providers()
        self.google_providers = self._providers_by_name("google")
        self.groq_providers = self._providers_by_name("groq")
        self.google_cycle = itertools.cycle(self.google_providers.items())
        self.groq_cycle = itertools.cycle(self.groq_providers.items())

        # Backward-compatible aliases used by older tests and debugging code.
        self.clients = {
            name: provider.client for name, provider in self.google_providers.items()
        }
        self.client_cycle = itertools.cycle(self.clients.items())

    def _providers_by_name(self, provider: str) -> Dict[str, LLMProviderStrategy]:
        return {
            name: strategy
            for name, strategy in self.providers.items()
            if strategy.provider == provider
        }

    def _get_client(self) -> genai.Client:
        client = next(self.client_cycle)
        logger.info("Using client: %s", client[0])
        return client[1]

    def _get_provider(self, provider: str) -> LLMProviderStrategy | None:
        providers = self.groq_providers if provider == "groq" else self.google_providers
        if not providers:
            return None

        cycle = self.groq_cycle if provider == "groq" else self.google_cycle
        name, strategy = next(cycle)
        logger.info("Using %s LLM provider: %s", provider, name)
        return strategy

    def _create_providers(self) -> Dict[str, LLMProviderStrategy]:
        key_provider = LLMKeyProvider()
        providers: Dict[str, LLMProviderStrategy] = {}

        for entry in key_provider.get_core_entries():
            provider_key = f"{entry.provider}:{entry.name}"
            if entry.provider == "google":
                providers[provider_key] = GoogleGenAIProvider(
                    name=entry.name,
                    provider="google",
                    client=genai.Client(api_key=entry.api_key),
                )
            elif entry.provider == "groq":
                try:
                    from groq import Groq
                except ImportError:
                    logger.exception("Groq key configured but groq package is missing")
                    continue

                providers[provider_key] = GroqProvider(
                    name=entry.name,
                    provider="groq",
                    client=Groq(api_key=entry.api_key),
                )
            else:
                logger.warning(
                    "Skipping unsupported LLM provider '%s' for key '%s'",
                    entry.provider,
                    entry.name,
                )

        logger.info("LLM providers created for: %s", list(providers.keys()))
        return providers

    async def _generate_google(
        self,
        *,
        contents: str,
        response_schema: type[ResponseModel],
    ) -> ResponseModel:
        return await self._generate_with_retry(
            provider_name="google",
            model=GOOGLE_MODEL,
            contents=contents,
            response_schema=response_schema,
        )

    async def _generate_groq(
        self,
        *,
        contents: str,
        response_schema: type[ResponseModel],
    ) -> ResponseModel:
        return await self._generate_with_retry(
            provider_name="groq",
            model=GROQ_MODEL,
            contents=contents,
            response_schema=response_schema,
        )

    async def _generate_with_retry(
        self,
        *,
        provider_name: str,
        model: str,
        contents: str,
        response_schema: type[ResponseModel],
    ) -> ResponseModel:
        last_error: Exception | None = None

        for attempt in range(MAX_ATTEMPTS):
            provider = self._get_provider(provider_name)
            if provider is None:
                raise RuntimeError(f"No {provider_name} LLM provider configured")

            try:
                return await provider.generate(
                    model=model,
                    contents=contents,
                    response_schema=response_schema,
                )
            except Exception as exc:
                last_error = exc
                error_str = str(exc)
                retryable = any(
                    marker in error_str for marker in TRANSIENT_ERROR_MARKERS
                )
                if attempt < MAX_ATTEMPTS - 1 and retryable:
                    wait_time = 2**attempt
                    logger.warning(
                        "Transient %s LLM error (%s), retrying in %ss... "
                        "(Attempt %s/%s)",
                        provider_name,
                        error_str,
                        wait_time,
                        attempt + 1,
                        MAX_ATTEMPTS,
                    )
                    await asyncio.sleep(wait_time)
                    continue

                logger.error(
                    "%s LLM generation failed after %s attempts: %s",
                    provider_name,
                    attempt + 1,
                    exc,
                )
                raise

        raise RuntimeError(f"{provider_name} LLM generation failed") from last_error

    async def _generate_with_fallback(
        self,
        *,
        contents: str,
        response_schema: type[ResponseModel],
        on_fallback: FallbackNotifier | None = None,
    ) -> ResponseModel:
        if not self.groq_providers:
            return await self._generate_google(
                contents=contents,
                response_schema=response_schema,
            )

        try:
            return await asyncio.wait_for(
                self._generate_groq(contents=contents, response_schema=response_schema),
                timeout=GROQ_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            if isinstance(exc, asyncio.TimeoutError):
                logger.warning("Groq LLM timed out after %ss", GROQ_TIMEOUT_SECONDS)
            else:
                logger.warning("Groq LLM failed; falling back to Google: %s", exc)

            if on_fallback is not None:
                await on_fallback()

            return await self._generate_google(
                contents=contents,
                response_schema=response_schema,
            )

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
        on_fallback: FallbackNotifier | None = None,
    ) -> ExpressionCard:
        langs = [lang1_code]
        if lang2_code:
            langs.append(lang2_code)

        labels = [f"- {lang1_label}"]
        if lang2_code and lang2_label:
            labels.append(f"- {lang2_label}")

        prompt = EXPRESSION_PROMPT_TEMPLATE.format(
            raw=raw,
            level=level,
            target_langs=", ".join(langs),
            target_labels="\n".join(labels),
        )

        output = await self._generate_with_fallback(
            contents=prompt,
            response_schema=ExpressionCard,
            on_fallback=on_fallback,
        )
        logger.debug("LLM Expression Output: %s", output)
        return output

    async def parse_import_list(self, raw_text: str) -> ImportResponse:
        """
        Parses a raw text containing a list of items to import using the LLM.
        """
        prompt = IMPORT_PROMPT_TEMPLATE.format(raw_input=raw_text)

        output = await self._generate_with_fallback(
            contents=prompt,
            response_schema=ImportResponse,
        )
        logger.debug("LLM Import Output: %s", output)
        return output

    @observe(name="LLMService.generate_story")
    async def generate_story(
        self,
        words: list[str],
        target_lang: str = "en",
        target_level: str = "B1",
        story_length: str = "6-10 sentences",
    ) -> StoryResponse:
        """
        Generates a short story using the provided words.
        """
        prompt = STORY_PROMPT_TEMPLATE.format(
            words=", ".join(words),
            level=target_level,
            length=story_length,
            target_lang=target_lang,
        )

        output = await self._generate_with_fallback(
            contents=prompt,
            response_schema=StoryResponse,
        )
        logger.debug("LLM Story Output: %s", output)
        return output
