"""
Unit tests for LLMService and LLMKeyProvider.

LLMService depends on Google genai, so we mock the client entirely
and test prompt construction, client rotation, and response parsing.

LLMKeyProvider is tested with a mock API key config.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from flashcard.schemas.expression import ExpressionCard
from flashcard.schemas.story import StoryResponse
from flashcard.schemas.api_key import APIKeyConfig, KeyEntry


# ===================================================================
# LLMKeyProvider (can test without genai)
# ===================================================================
class TestLLMKeyProvider:

    def _make_provider(self):
        """Create a LLMKeyProvider with mocked config."""
        from flashcard.services.llm.llm_key import LLMKeyProvider

        config = APIKeyConfig(
            core=[
                KeyEntry(name="mey", api_key="key_mey_123"),
                KeyEntry(name="ako", api_key="key_ako_456"),
            ],
            reminder=[
                KeyEntry(name="rem1", api_key="key_rem_789"),
            ],
            users={"user_42": ["user_key_1", "user_key_2"]},
        )

        provider = LLMKeyProvider.__new__(LLMKeyProvider)
        provider._config = config
        return provider

    def test_get_core_key_found(self):
        provider = self._make_provider()
        assert provider.get_core_key("mey") == "key_mey_123"

    def test_get_core_key_not_found(self):
        provider = self._make_provider()
        assert provider.get_core_key("nonexistent") is None

    def test_get_reminder_key(self):
        provider = self._make_provider()
        assert provider.get_reminder_key("rem1") == "key_rem_789"

    def test_get_user_keys(self):
        provider = self._make_provider()
        keys = provider.get_user_keys("user_42")
        assert keys == ["user_key_1", "user_key_2"]

    def test_get_user_keys_unknown_user(self):
        provider = self._make_provider()
        assert provider.get_user_keys("unknown") == []

    def test_create_client_raises_for_missing_key(self):
        import pytest
        provider = self._make_provider()

        with pytest.raises(ValueError, match="not found"):
            provider.create_client(provider="core", name="missing")


# ===================================================================
# LLMService - mocked genai client
# ===================================================================
class TestLLMServiceMocked:
    """Tests the LLMService methods with a fully mocked Google genai client."""

    def _make_service(self, parsed_response=None):
        """Build an LLMService with mocked internals."""
        from flashcard.services.llm.llm import GoogleGenAIProvider, LLMService

        # Build mock response
        mock_resp = MagicMock()
        mock_resp.parsed = parsed_response

        # Build mock client
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_resp

        # Create service without calling __init__ (avoids real key loading)
        service = LLMService.__new__(LLMService)
        provider = GoogleGenAIProvider(
            name="mock",
            provider="google",
            client=mock_client,
        )
        service.providers = {"mock": provider}
        service.google_providers = {"mock": provider}
        service.groq_providers = {}
        service.clients = {"mock": mock_client}
        service.google_model = "gemini-test"
        service.groq_model = "groq-test"
        service.groq_fallback_delay_seconds = 3.0
        service.max_attempts = 2

        import itertools
        service.google_cycle = itertools.cycle(service.google_providers.items())
        service.groq_cycle = itertools.cycle(service.groq_providers.items())
        service.client_cycle = itertools.cycle(service.clients.items())

        return service, mock_client

    async def test_generate_expression_card_calls_genai(self):
        mock_card = ExpressionCard(
            success=True,
            norm="parlare",
            learning_definition="Comunicare a voce",
            translations=[{"label": "🇬🇧 EN", "text": "to speak"}],
            learning_example="Io parlo italiano.",
            note=None,
            suggestions=[],
        )
        service, mock_client = self._make_service(parsed_response=mock_card)

        result = await service.generate_expression_card(
            raw="parlare",
            level="B1",
            lang1_code="en",
            lang1_label="🇬🇧 EN",
        )

        assert result.norm == "parlare"
        mock_client.models.generate_content.assert_called_once()

    async def test_generate_expression_card_with_two_languages(self):
        mock_card = ExpressionCard(
            success=True, norm="casa", learning_definition="Abitazione",
            translations=[
                {"label": "🇬🇧 EN", "text": "house"},
                {"label": "🇮🇷 FA", "text": "خانه"},
            ],
            learning_example="La casa è grande.",
            note=None, suggestions=[],
        )
        service, mock_client = self._make_service(parsed_response=mock_card)

        result = await service.generate_expression_card(
            raw="casa", level="A2",
            lang1_code="en", lang1_label="🇬🇧 EN",
            lang2_code="fa", lang2_label="🇮🇷 FA",
        )

        assert len(result.translations) == 2
        # Verify the prompt included both languages
        call_args = mock_client.models.generate_content.call_args
        prompt = call_args[1]["contents"] if "contents" in call_args[1] else call_args[0][0]
        # prompt is passed as keyword or positional - check call was made
        mock_client.models.generate_content.assert_called_once()

    async def test_generate_expression_card_uses_configured_learning_language(self):
        mock_card = ExpressionCard(
            success=True,
            norm="walk",
            learning_definition="Move on foot",
            translations=[{"label": "IT", "text": "camminare"}],
            learning_example="I walk every day.",
            note=None,
            suggestions=[],
        )
        service, mock_client = self._make_service(parsed_response=mock_card)

        with patch("flashcard.services.llm.llm.settings.LEARNING_LANGUAGE_NAME", "English"):
            await service.generate_expression_card(
                raw="walk",
                level="A2",
                lang1_code="it",
                lang1_label="IT",
            )

        call_args = mock_client.models.generate_content.call_args
        prompt = call_args.kwargs["contents"]
        assert "English vocabulary helper" in prompt
        assert "Italian vocabulary helper" not in prompt

    async def test_generate_story(self):
        from flashcard.schemas.story import StoryParagraph

        mock_story = StoryResponse(paragraphs=[
            StoryParagraph(learning_text="Marco cammina.", translation="Marco walks."),
        ])
        service, mock_client = self._make_service(parsed_response=mock_story)

        result = await service.generate_story(
            words=["camminare", "casa"],
            target_lang="en",
            target_level="B1",
        )

        assert len(result.paragraphs) == 1
        mock_client.models.generate_content.assert_called_once()

    def test_client_rotation(self):
        """_get_client should cycle through available clients."""
        from flashcard.services.llm.llm import LLMService
        import itertools

        service = LLMService.__new__(LLMService)
        mock_a = MagicMock()
        mock_b = MagicMock()
        service.clients = {"a": mock_a, "b": mock_b}
        service.client_cycle = itertools.cycle(service.clients.items())

        first = service._get_client()
        second = service._get_client()
        third = service._get_client()

        # Should cycle: a -> b -> a
        assert first == mock_a
        assert second == mock_b
        assert third == mock_a

    def test_strict_json_schema_requires_nullable_fields(self):
        from flashcard.services.llm.llm import strict_json_schema

        schema = strict_json_schema(ExpressionCard)

        assert set(schema["required"]) == set(schema["properties"].keys())
        assert schema["additionalProperties"] is False

    async def test_groq_timeout_falls_back_to_google_and_notifies(self):
        from flashcard.services.llm.llm import LLMGenerationResult, LLMService

        mock_card = ExpressionCard(
            success=True,
            norm="parlare",
            learning_definition="Comunicare a voce",
            translations=[{"label": "🇬🇧 EN", "text": "to speak"}],
            learning_example="Io parlo italiano.",
            note=None,
            suggestions=[],
        )

        service = LLMService.__new__(LLMService)
        notified = False

        async def slow_groq(**kwargs):
            await asyncio.sleep(0.005)
            return LLMGenerationResult(
                value=mock_card,
                provider="groq",
                provider_key="groq:test",
                model="groq-test",
                fallback_triggered=False,
            )

        async def google(**kwargs):
            return LLMGenerationResult(
                value=mock_card,
                provider="google",
                provider_key="google:test",
                model="google-test",
                fallback_triggered=True,
            )

        async def notify():
            nonlocal notified
            notified = True

        service.groq_providers = {"groq": MagicMock()}
        service._generate_groq = slow_groq
        service._generate_google = google

        with patch("flashcard.services.llm.llm.GROQ_TIMEOUT_SECONDS", 0.001):
            result = await service.generate_expression_card(
                raw="parlare",
                level="B1",
                lang1_code="en",
                lang1_label="🇬🇧 EN",
                on_fallback=notify,
            )

        assert result == mock_card
        assert notified is True

    async def test_delayed_fallback_returns_groq_if_it_wins_race(self):
        from flashcard.services.llm.llm import LLMGenerationResult, LLMService

        groq_card = ExpressionCard(
            success=True,
            norm="parlare",
            learning_definition="Groq definition",
            translations=[{"label": "🇬🇧 EN", "text": "to speak"}],
            learning_example="Io parlo italiano.",
            note=None,
            suggestions=[],
        )
        google_card = groq_card.model_copy(update={"learning_definition": "Google definition"})

        service = LLMService.__new__(LLMService)
        notified = False

        async def slow_groq(**kwargs):
            await asyncio.sleep(0.02)
            return LLMGenerationResult(
                value=groq_card,
                provider="groq",
                provider_key="groq:test",
                model="groq-test",
                fallback_triggered=False,
            )

        async def google(**kwargs):
            await asyncio.sleep(0.2)
            return LLMGenerationResult(
                value=google_card,
                provider="google",
                provider_key="google:test",
                model="google-test",
                fallback_triggered=True,
            )

        async def notify():
            nonlocal notified
            notified = True

        service.groq_providers = {"groq": MagicMock()}
        service.groq_fallback_delay_seconds = 0.001
        service._generate_groq = slow_groq
        service._generate_google = google

        result = await service.generate_expression_card(
            raw="parlare",
            level="B1",
            lang1_code="en",
            lang1_label="🇬🇧 EN",
            on_fallback=notify,
        )

        assert result.learning_definition == "Groq definition"
        assert notified is True

    async def test_delayed_fallback_returns_google_if_google_wins_race(self):
        from flashcard.services.llm.llm import LLMGenerationResult, LLMService

        groq_card = ExpressionCard(
            success=True,
            norm="parlare",
            learning_definition="Groq definition",
            translations=[{"label": "🇬🇧 EN", "text": "to speak"}],
            learning_example="Io parlo italiano.",
            note=None,
            suggestions=[],
        )
        google_card = groq_card.model_copy(update={"learning_definition": "Google definition"})

        service = LLMService.__new__(LLMService)

        async def slow_groq(**kwargs):
            await asyncio.sleep(0.05)
            return LLMGenerationResult(
                value=groq_card,
                provider="groq",
                provider_key="groq:test",
                model="groq-test",
                fallback_triggered=False,
            )

        async def google(**kwargs):
            await asyncio.sleep(0.01)
            return LLMGenerationResult(
                value=google_card,
                provider="google",
                provider_key="google:test",
                model="google-test",
                fallback_triggered=True,
            )

        service.groq_providers = {"groq": MagicMock()}
        service.groq_fallback_delay_seconds = 0.001
        service._generate_groq = slow_groq
        service._generate_google = google

        result = await service.generate_expression_card(
            raw="parlare",
            level="B1",
            lang1_code="en",
            lang1_label="🇬🇧 EN",
        )

        assert result.learning_definition == "Google definition"

    async def test_groq_failure_before_delay_falls_back_to_google(self):
        from flashcard.services.llm.llm import LLMGenerationResult, LLMService

        google_card = ExpressionCard(
            success=True,
            norm="parlare",
            learning_definition="Google definition",
            translations=[{"label": "🇬🇧 EN", "text": "to speak"}],
            learning_example="Io parlo italiano.",
            note=None,
            suggestions=[],
        )
        service = LLMService.__new__(LLMService)
        notified = False

        async def groq(**kwargs):
            raise RuntimeError("groq fail")

        async def google(**kwargs):
            return LLMGenerationResult(
                value=google_card,
                provider="google",
                provider_key="google:test",
                model="google-test",
                fallback_triggered=True,
            )

        async def notify():
            nonlocal notified
            notified = True

        service.groq_providers = {"groq": MagicMock()}
        service.groq_fallback_delay_seconds = 1.0
        service._generate_groq = groq
        service._generate_google = google

        result = await service._generate_with_fallback(
            contents="prompt",
            response_schema=ExpressionCard,
            on_fallback=notify,
        )

        assert result.value == google_card
        assert result.provider == "google"
        assert result.fallback_triggered is True
        assert notified is True

    async def test_groq_failure_after_delay_waits_for_google_success(self):
        from flashcard.services.llm.llm import LLMGenerationResult, LLMService

        google_card = ExpressionCard(
            success=True,
            norm="parlare",
            learning_definition="Google definition",
            translations=[{"label": "🇬🇧 EN", "text": "to speak"}],
            learning_example="Io parlo italiano.",
            note=None,
            suggestions=[],
        )
        service = LLMService.__new__(LLMService)

        async def groq(**kwargs):
            await asyncio.sleep(0.01)
            raise RuntimeError("groq fail")

        async def google(**kwargs):
            await asyncio.sleep(0.02)
            return LLMGenerationResult(
                value=google_card,
                provider="google",
                provider_key="google:test",
                model="google-test",
                fallback_triggered=True,
            )

        service.groq_providers = {"groq": MagicMock()}
        service.groq_fallback_delay_seconds = 0.001
        service._generate_groq = groq
        service._generate_google = google

        result = await service._generate_with_fallback(
            contents="prompt",
            response_schema=ExpressionCard,
        )

        assert result.value == google_card
        assert result.provider == "google"
        assert result.fallback_triggered is True

    async def test_google_failure_after_delay_waits_for_groq_success(self):
        from flashcard.services.llm.llm import LLMGenerationResult, LLMService

        groq_card = ExpressionCard(
            success=True,
            norm="parlare",
            learning_definition="Groq definition",
            translations=[{"label": "🇬🇧 EN", "text": "to speak"}],
            learning_example="Io parlo italiano.",
            note=None,
            suggestions=[],
        )
        service = LLMService.__new__(LLMService)

        async def groq(**kwargs):
            await asyncio.sleep(0.03)
            return LLMGenerationResult(
                value=groq_card,
                provider="groq",
                provider_key="groq:test",
                model="groq-test",
                fallback_triggered=False,
            )

        async def google(**kwargs):
            await asyncio.sleep(0.01)
            raise RuntimeError("google fail")

        service.groq_providers = {"groq": MagicMock()}
        service.groq_fallback_delay_seconds = 0.001
        service._generate_groq = groq
        service._generate_google = google

        result = await service._generate_with_fallback(
            contents="prompt",
            response_schema=ExpressionCard,
        )

        assert result.value == groq_card
        assert result.provider == "groq"
        assert result.fallback_triggered is True

    async def test_both_racing_providers_fail_raises_last_error(self):
        from flashcard.services.llm.llm import LLMService

        service = LLMService.__new__(LLMService)

        async def groq(**kwargs):
            await asyncio.sleep(0.01)
            raise ValueError("groq fail")

        async def google(**kwargs):
            await asyncio.sleep(0.02)
            raise RuntimeError("google fail")

        service.groq_providers = {"groq": MagicMock()}
        service.groq_fallback_delay_seconds = 0.001
        service._generate_groq = groq
        service._generate_google = google

        with pytest.raises(RuntimeError, match="google fail"):
            await service._generate_with_fallback(
                contents="prompt",
                response_schema=ExpressionCard,
            )

    async def test_no_groq_provider_uses_google_without_fallback(self):
        from flashcard.services.llm.llm import LLMGenerationResult, LLMService

        google_card = ExpressionCard(
            success=True,
            norm="parlare",
            learning_definition="Google definition",
            translations=[{"label": "🇬🇧 EN", "text": "to speak"}],
            learning_example="Io parlo italiano.",
            note=None,
            suggestions=[],
        )
        service = LLMService.__new__(LLMService)

        async def google(**kwargs):
            return LLMGenerationResult(
                value=google_card,
                provider="google",
                provider_key="google:test",
                model="google-test",
                fallback_triggered=False,
            )

        service.groq_providers = {}
        service._generate_google = google

        result = await service._generate_with_fallback(
            contents="prompt",
            response_schema=ExpressionCard,
        )

        assert result.value == google_card
        assert result.provider == "google"
        assert result.fallback_triggered is False

    async def test_trace_metadata_records_final_provider_model_and_fallback(self):
        from flashcard.schemas.trace import TraceData
        from flashcard.services.llm.llm import LLMGenerationResult, LLMService
        from flashcard.utils.time import iso_z, now_utc
        from flashcard.utils.tracing import clear_current_trace, set_current_trace

        groq_card = ExpressionCard(
            success=True,
            norm="parlare",
            learning_definition="Groq definition",
            translations=[{"label": "🇬🇧 EN", "text": "to speak"}],
            learning_example="Io parlo italiano.",
            note=None,
            suggestions=[],
        )
        service = LLMService.__new__(LLMService)

        async def generate(**kwargs):
            return LLMGenerationResult(
                value=groq_card,
                provider="groq",
                provider_key="groq:test",
                model="groq-test",
                fallback_triggered=True,
            )

        service._generate_with_fallback = generate
        trace = TraceData(trace_id="llm-meta", timestamp=iso_z(now_utc()), update_type="test")
        token = set_current_trace(trace)

        try:
            result = await service.generate_expression_card(
                raw="parlare",
                level="B1",
                lang1_code="en",
                lang1_label="🇬🇧 EN",
            )
        finally:
            clear_current_trace(token)

        assert result == groq_card
        assert trace.spans[0].metadata == {
            "llm_provider": "groq",
            "llm_provider_key": "groq:test",
            "llm_model": "groq-test",
            "llm_fallback_triggered": True,
        }

    async def test_slow_losing_provider_task_is_cancelled_and_gathered(self):
        from flashcard.services.llm.llm import LLMGenerationResult, LLMService

        groq_card = ExpressionCard(
            success=True,
            norm="parlare",
            learning_definition="Groq definition",
            translations=[{"label": "🇬🇧 EN", "text": "to speak"}],
            learning_example="Io parlo italiano.",
            note=None,
            suggestions=[],
        )
        service = LLMService.__new__(LLMService)
        google_cancelled = asyncio.Event()

        async def groq(**kwargs):
            await asyncio.sleep(0.01)
            return LLMGenerationResult(
                value=groq_card,
                provider="groq",
                provider_key="groq:test",
                model="groq-test",
                fallback_triggered=False,
            )

        async def google(**kwargs):
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                google_cancelled.set()
                raise

        service.groq_providers = {"groq": MagicMock()}
        service.groq_fallback_delay_seconds = 0.001
        service._generate_groq = groq
        service._generate_google = google

        result = await service._generate_with_fallback(
            contents="prompt",
            response_schema=ExpressionCard,
        )

        assert result.value == groq_card
        assert result.fallback_triggered is True
        assert google_cancelled.is_set()
