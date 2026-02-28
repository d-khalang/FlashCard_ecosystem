"""
Unit tests for flashcard.services.verb.VerbService

Tests validation, extraction, and the DB→API fallback orchestration.
Pure methods (is_valid_verb, extract_verb) need no mocking.
get_verb_data orchestration uses mocked DB + HTTP.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from flashcard.services.verb import VerbService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_service():
    """Create a VerbService with mocked dependencies."""
    mock_cols = {"conjugation": MagicMock()}
    mock_cols["conjugation"].find_one = AsyncMock(return_value=None)
    mock_cols["conjugation"].replace_one = AsyncMock()
    mock_http = MagicMock()
    mock_http.get = AsyncMock()
    return VerbService(mock_cols, http_client=mock_http), mock_cols, mock_http


# ===================================================================
# is_valid_verb — pure function
# ===================================================================
class TestIsValidVerb:

    def test_simple_verb(self):
        service, _, _ = _make_service()
        assert service.is_valid_verb("parlare") is True

    def test_accented_characters(self):
        service, _, _ = _make_service()
        assert service.is_valid_verb("être") is True

    def test_with_verb_command_prefix(self):
        service, _, _ = _make_service()
        assert service.is_valid_verb("/verb parlare") is True

    def test_with_verb_command_prefix_without_space(self):
        service, _, _ = _make_service()
        assert service.is_valid_verb("/verbparlare") is True

    def test_numbers_rejected(self):
        service, _, _ = _make_service()
        assert service.is_valid_verb("abc123") is False

    def test_empty_string_rejected(self):
        service, _, _ = _make_service()
        assert service.is_valid_verb("") is False

    def test_just_command_rejected(self):
        service, _, _ = _make_service()
        assert service.is_valid_verb("/verb") is False

    def test_special_characters_rejected(self):
        service, _, _ = _make_service()
        assert service.is_valid_verb("hello!") is False

    def test_spaces_rejected(self):
        """Multiple words should fail the single-word regex."""
        service, _, _ = _make_service()
        assert service.is_valid_verb("fare bene") is False

    def test_none_input_rejected(self):
        service, _, _ = _make_service()
        assert service.is_valid_verb(None) is False


# ===================================================================
# extract_verb — pure function
# ===================================================================
class TestExtractVerb:

    def test_normal_extraction(self):
        service, _, _ = _make_service()
        assert service.extract_verb("/verb parlare") == "parlare"

    def test_just_command_returns_none(self):
        service, _, _ = _make_service()
        assert service.extract_verb("/verb") is None

    def test_just_command_with_space_returns_none(self):
        service, _, _ = _make_service()
        assert service.extract_verb("/verb ") is None

    def test_empty_string_returns_none(self):
        service, _, _ = _make_service()
        assert service.extract_verb("") is None

    def test_none_returns_none(self):
        service, _, _ = _make_service()
        assert service.extract_verb(None) is None

    def test_preserves_original_case(self):
        service, _, _ = _make_service()
        assert service.extract_verb("/verb Parlare") == "Parlare"

    def test_with_verb_command_prefix_without_space(self):
        service, _, _ = _make_service()
        assert service.extract_verb("/verbparlare") == "parlare"


# ===================================================================
# get_verb_data — orchestration (DB → API fallback)
# ===================================================================
class TestGetVerbData:

    async def test_returns_from_db_when_found(self):
        """DB has the verb → returns it, no API call."""
        service, cols, http = _make_service()

        # Simulate a valid DB document matching ConjugationDBResponse schema
        db_doc = {
            "verb": "parlare",
            "data": {
                "queried": "parlare",
                "url": "https://example.com/parlare",
                "principal_forms": {"infinito": "parlare"},
                "conjugations": {"indicativo": {"presente": {"io": "parlo", "tu": "parli"}}},
            },
        }
        cols["conjugation"].find_one = AsyncMock(return_value=db_doc)

        result = await service.get_verb_data("parlare")

        assert result is not None
        assert result.queried == "parlare"
        http.get.assert_not_called()  # No API call needed

    async def test_fallback_to_api_when_db_empty(self):
        """DB miss → calls API → saves to DB → returns data."""
        service, cols, http = _make_service()
        cols["conjugation"].find_one = AsyncMock(return_value=None)

        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "queried": "parlare",
                "url": "https://example.com/parlare",
                "principal_forms": {"infinito": "parlare"},
                "conjugations": {"indicativo": {"presente": {"io": "parlo"}}},
            },
        }
        http.get = AsyncMock(return_value=mock_response)

        result = await service.get_verb_data("parlare")

        assert result is not None
        assert result.queried == "parlare"
        http.get.assert_called_once()
        cols["conjugation"].replace_one.assert_called_once()  # Saved to DB

    async def test_api_response_returns_conjugation_response_type(self):
        """Return type should be ConjugationResponse, not raw dict."""
        from flashcard.schemas.conjugations import ConjugationResponse

        service, cols, http = _make_service()
        cols["conjugation"].find_one = AsyncMock(return_value=None)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "queried": "parlare",
                "url": "https://example.com/parlare",
                "principal_forms": {"infinito": "parlare"},
                "conjugations": {"indicativo": {"presente": {"io": "parlo"}}},
            },
        }
        http.get = AsyncMock(return_value=mock_response)

        result = await service.get_verb_data("parlare")
        assert isinstance(result, ConjugationResponse)

    async def test_api_failure_returns_none(self):
        """API returns error → returns None."""
        service, cols, http = _make_service()
        cols["conjugation"].find_one = AsyncMock(return_value=None)

        mock_response = MagicMock()
        mock_response.status_code = 500
        http.get = AsyncMock(return_value=mock_response)

        result = await service.get_verb_data("parlare")
        assert result is None

    async def test_api_exception_raises(self):
        """API throws exception → propagates up."""
        service, cols, http = _make_service()
        cols["conjugation"].find_one = AsyncMock(return_value=None)
        http.get = AsyncMock(side_effect=Exception("Connection timeout"))

        with pytest.raises(Exception, match="Connection timeout"):
            await service.get_verb_data("parlare")

    async def test_corrupted_db_falls_back_to_api(self):
        """DB data fails validation → falls through to API."""
        service, cols, http = _make_service()

        # Invalid DB document (missing required fields)
        cols["conjugation"].find_one = AsyncMock(
            return_value={"verb": "parlare", "data": "not_valid_data"}
        )

        # Valid API response as fallback
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "queried": "parlare",
                "url": "https://example.com/parlare",
                "principal_forms": {"infinito": "parlare"},
                "conjugations": {"indicativo": {"presente": {"io": "parlo"}}},
            },
        }
        http.get = AsyncMock(return_value=mock_response)

        result = await service.get_verb_data("parlare")

        assert result is not None
        http.get.assert_called_once()  # Fell through to API
