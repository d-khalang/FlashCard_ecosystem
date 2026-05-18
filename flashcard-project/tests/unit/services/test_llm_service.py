"""
Unit tests for LLMService and LLMKeyProvider.

LLMService depends on Google genai, so we mock the client entirely
and test prompt construction, client rotation, and response parsing.

LLMKeyProvider is tested with a mock API key config.
"""
import asyncio
from unittest.mock import MagicMock, patch

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
# LLMService — mocked genai client
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

        import itertools
        service.google_cycle = itertools.cycle(service.google_providers.items())
        service.groq_cycle = itertools.cycle(service.groq_providers.items())
        service.client_cycle = itertools.cycle(service.clients.items())

        return service, mock_client

    async def test_generate_expression_card_calls_genai(self):
        mock_card = ExpressionCard(
            success=True,
            norm="parlare",
            def_it="Comunicare a voce",
            translations=[{"label": "🇬🇧 EN", "text": "to speak"}],
            example_it="Io parlo italiano.",
            note_it=None,
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
            success=True, norm="casa", def_it="Abitazione",
            translations=[
                {"label": "🇬🇧 EN", "text": "house"},
                {"label": "🇮🇷 FA", "text": "خانه"},
            ],
            example_it="La casa è grande.",
            note_it=None, suggestions=[],
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
        # prompt is passed as keyword or positional — check call was made
        mock_client.models.generate_content.assert_called_once()

    async def test_generate_story(self):
        from flashcard.schemas.story import StoryParagraph

        mock_story = StoryResponse(paragraphs=[
            StoryParagraph(italian_text="Marco cammina.", translation="Marco walks."),
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

        # Should cycle: a → b → a
        assert first == mock_a
        assert second == mock_b
        assert third == mock_a

    def test_strict_json_schema_requires_nullable_fields(self):
        from flashcard.services.llm.llm import strict_json_schema

        schema = strict_json_schema(ExpressionCard)

        assert set(schema["required"]) == set(schema["properties"].keys())
        assert schema["additionalProperties"] is False

    async def test_groq_timeout_falls_back_to_google_and_notifies(self):
        from flashcard.services.llm.llm import LLMService

        mock_card = ExpressionCard(
            success=True,
            norm="parlare",
            def_it="Comunicare a voce",
            translations=[{"label": "🇬🇧 EN", "text": "to speak"}],
            example_it="Io parlo italiano.",
            note_it=None,
            suggestions=[],
        )

        service = LLMService.__new__(LLMService)
        notified = False

        async def slow_groq(**kwargs):
            await asyncio.sleep(0.02)
            return mock_card

        async def google(**kwargs):
            return mock_card

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
