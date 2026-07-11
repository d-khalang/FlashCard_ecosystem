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
from flashcard.settings import settings
from flashcard.services.llm.llm_key import LLMKeyProvider
from flashcard.services.llm.prompts import (
    EXPRESSION_PROMPT_TEMPLATE,
    IMPORT_PROMPT_TEMPLATE,
    STORY_PROMPT_TEMPLATE,
)
from flashcard.utils.logger import get_logger
from flashcard.utils.tracing import annotate_current_span, observe

logger = get_logger(__name__)

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)
FallbackNotifier = Callable[[], Awaitable[None]]

TRANSIENT_ERROR_MARKERS = (
    "503",
    "429",
    "UNAVAILABLE",
    "RESOURCE_EXHAUSTED",
    "Internal Server Error",
    "rate_limit",
    "timeout",
)
GROQ_TIMEOUT_SECONDS = settings.LLM_GROQ_FALLBACK_DELAY_SECONDS


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


@dataclass(frozen=True)
class LLMGenerationResult(Generic[ResponseModel]):
    value: ResponseModel
    provider: str
    provider_key: str
    model: str
    fallback_triggered: bool


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
        self.google_model = settings.LLM_GOOGLE_MODEL
        self.groq_model = settings.LLM_GROQ_MODEL
        self.groq_fallback_delay_seconds = max(
            0.0,
            settings.LLM_GROQ_FALLBACK_DELAY_SECONDS,
        )
        self.max_attempts = max(1, settings.LLM_MAX_ATTEMPTS)
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
        fallback_triggered: bool = False,
    ) -> LLMGenerationResult[ResponseModel]:
        model = getattr(self, "google_model", settings.LLM_GOOGLE_MODEL)
        return await self._generate_with_retry(
            provider_name="google",
            model=model,
            contents=contents,
            response_schema=response_schema,
            fallback_triggered=fallback_triggered,
        )

    async def _generate_groq(
        self,
        *,
        contents: str,
        response_schema: type[ResponseModel],
    ) -> LLMGenerationResult[ResponseModel]:
        model = getattr(self, "groq_model", settings.LLM_GROQ_MODEL)
        return await self._generate_with_retry(
            provider_name="groq",
            model=model,
            contents=contents,
            response_schema=response_schema,
            fallback_triggered=False,
        )

    async def _generate_with_retry(
        self,
        *,
        provider_name: str,
        model: str,
        contents: str,
        response_schema: type[ResponseModel],
        fallback_triggered: bool,
    ) -> LLMGenerationResult[ResponseModel]:
        last_error: Exception | None = None

        max_attempts = getattr(self, "max_attempts", settings.LLM_MAX_ATTEMPTS)
        max_attempts = max(1, max_attempts)

        for attempt in range(max_attempts):
            provider = self._get_provider(provider_name)
            if provider is None:
                raise RuntimeError(f"No {provider_name} LLM provider configured")

            try:
                value = await provider.generate(
                    model=model,
                    contents=contents,
                    response_schema=response_schema,
                )
                return LLMGenerationResult(
                    value=value,
                    provider=provider_name,
                    provider_key=f"{provider.provider}:{provider.name}",
                    model=model,
                    fallback_triggered=fallback_triggered,
                )
            except Exception as exc:
                last_error = exc
                error_str = str(exc)
                retryable = any(
                    marker in error_str for marker in TRANSIENT_ERROR_MARKERS
                )
                if attempt < max_attempts - 1 and retryable:
                    wait_time = 2**attempt
                    logger.warning(
                        "Transient %s LLM error (%s), retrying in %ss... "
                        "(Attempt %s/%s)",
                        provider_name,
                        error_str,
                        wait_time,
                        attempt + 1,
                        max_attempts,
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
    ) -> LLMGenerationResult[ResponseModel]:
        if not self.groq_providers:
            return await self._generate_google(
                contents=contents,
                response_schema=response_schema,
            )

        groq_task = asyncio.create_task(
            self._generate_groq(contents=contents, response_schema=response_schema),
            name="llm-groq",
        )
        done, _ = await asyncio.wait(
            {groq_task},
            timeout=getattr(
                self,
                "groq_fallback_delay_seconds",
                GROQ_TIMEOUT_SECONDS,
            ),
            return_when=asyncio.FIRST_COMPLETED,
        )

        if groq_task in done:
            try:
                return await groq_task
            except Exception as exc:
                logger.warning("Groq LLM failed before fallback delay: %s", exc)
                if on_fallback is not None:
                    await on_fallback()
                return await self._generate_google(
                    contents=contents,
                    response_schema=response_schema,
                    fallback_triggered=True,
                )

        logger.warning(
            "Groq LLM did not finish within %ss; starting Google fallback",
            getattr(self, "groq_fallback_delay_seconds", GROQ_TIMEOUT_SECONDS),
        )
        if on_fallback is not None:
            await on_fallback()

        google_task = asyncio.create_task(
            self._generate_google(
                contents=contents,
                response_schema=response_schema,
                fallback_triggered=True,
            ),
            name="llm-google",
        )

        return await self._first_successful([groq_task, google_task])

    async def _first_successful(
        self,
        tasks: list[asyncio.Task[LLMGenerationResult[ResponseModel]]],
    ) -> LLMGenerationResult[ResponseModel]:
        errors: list[BaseException] = []
        pending = set(tasks)

        while pending:
            done, pending = await asyncio.wait(
                pending,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in done:
                try:
                    result = task.result()
                except Exception as exc:
                    errors.append(exc)
                    logger.warning("LLM provider task failed while racing: %s", exc)
                    continue

                await self._cancel_pending_tasks(list(pending), winner=task)
                return LLMGenerationResult(
                    value=result.value,
                    provider=result.provider,
                    provider_key=result.provider_key,
                    model=result.model,
                    fallback_triggered=True,
                )

        if errors:
            raise errors[-1]
        raise RuntimeError("All LLM provider tasks failed")

    async def _cancel_pending_tasks(
        self,
        tasks: list[asyncio.Task[LLMGenerationResult[ResponseModel]]],
        *,
        winner: asyncio.Task[LLMGenerationResult[ResponseModel]],
    ) -> None:
        pending = [task for task in tasks if task is not winner and not task.done()]
        for task in pending:
            task.cancel()

        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

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
            learning_language_name=settings.LEARNING_LANGUAGE_NAME,
            target_langs=", ".join(langs),
            target_labels="\n".join(labels),
        )

        output = await self._generate_with_fallback(
            contents=prompt,
            response_schema=ExpressionCard,
            on_fallback=on_fallback,
        )
        self._annotate_generation(output)
        logger.info(
            "LLM final response provider=%s model=%s fallback_triggered=%s",
            output.provider_key,
            output.model,
            output.fallback_triggered,
        )
        logger.debug("LLM Expression Output: %s", output.value)
        return output.value

    async def parse_import_list(self, raw_text: str) -> ImportResponse:
        """
        Parses a raw text containing a list of items to import using the LLM.
        """
        prompt = IMPORT_PROMPT_TEMPLATE.format(
            raw_input=raw_text,
            learning_language_name=settings.LEARNING_LANGUAGE_NAME,
        )

        output = await self._generate_with_fallback(
            contents=prompt,
            response_schema=ImportResponse,
        )
        self._annotate_generation(output)
        logger.info(
            "LLM final response provider=%s model=%s fallback_triggered=%s",
            output.provider_key,
            output.model,
            output.fallback_triggered,
        )
        logger.debug("LLM Import Output: %s", output.value)
        return output.value

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
            learning_language_name=settings.LEARNING_LANGUAGE_NAME,
        )

        output = await self._generate_with_fallback(
            contents=prompt,
            response_schema=StoryResponse,
        )
        self._annotate_generation(output)
        logger.info(
            "LLM final response provider=%s model=%s fallback_triggered=%s",
            output.provider_key,
            output.model,
            output.fallback_triggered,
        )
        logger.debug("LLM Story Output: %s", output.value)
        return output.value

    def _annotate_generation(self, output: LLMGenerationResult[ResponseModel]) -> None:
        annotate_current_span(
            {
                "llm_provider": output.provider,
                "llm_provider_key": output.provider_key,
                "llm_model": output.model,
                "llm_fallback_triggered": output.fallback_triggered,
            }
        )
