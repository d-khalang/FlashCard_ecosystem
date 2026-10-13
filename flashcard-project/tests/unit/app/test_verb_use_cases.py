"""
Unit tests for VerbUseCases: verb validation, lookup and counting, independent of Telegram.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from flashcard.app.verb import Found, InvalidVerb, NotFound, NoVerb, VerbUseCases
from flashcard.schemas.conjugations import ConjugationResponse
from flashcard.services.verb import VerbService

DATA = ConjugationResponse(queried="parlare", url="https://example.com/parlare",
                           principal_forms={}, conjugations={})


def _use_cases(data=DATA):
    verbs = VerbService(cols=MagicMock())
    verbs.get_verb_data = AsyncMock(return_value=data)
    consumption = MagicMock()
    consumption.increment = AsyncMock()
    return VerbUseCases(verb_service=verbs, consumption_service=consumption), verbs, consumption


class TestParse:

    def test_valid_verb_is_returned_stripped(self):
        use_cases, _, _ = _use_cases()

        assert use_cases.parse(" parlare ") == "parlare"

    @pytest.mark.parametrize("text", [None, "", "   "])
    def test_no_verb(self, text):
        use_cases, _, _ = _use_cases()

        assert use_cases.parse(text) == NoVerb()

    @pytest.mark.parametrize("text", ["andare a casa", "parl4re", "<b>"])
    def test_invalid_verb(self, text):
        use_cases, _, _ = _use_cases()

        assert use_cases.parse(text) == InvalidVerb(verb=text)


class TestLookup:

    async def test_found_is_counted(self):
        use_cases, verbs, consumption = _use_cases()

        assert await use_cases.lookup(999, "parlare") == Found(data=DATA)
        verbs.get_verb_data.assert_awaited_once_with("parlare")
        consumption.increment.assert_awaited_once_with(999, "verb_lookups")

    @pytest.mark.parametrize("verb", ["", " parlare ", "andare a casa", "parl4re"])
    async def test_unparsed_input_is_rejected_without_lookup(self, verb):
        use_cases, verbs, _ = _use_cases()

        with pytest.raises(ValueError):
            await use_cases.lookup(999, verb)
        verbs.get_verb_data.assert_not_awaited()

    async def test_not_found_is_not_counted(self):
        use_cases, _, consumption = _use_cases(data=None)

        assert await use_cases.lookup(999, "parlare") == NotFound(verb="parlare")
        consumption.increment.assert_not_awaited()

    async def test_lookup_error_propagates_uncounted(self):
        use_cases, verbs, consumption = _use_cases()
        verbs.get_verb_data.side_effect = RuntimeError("scraper down")

        with pytest.raises(RuntimeError):
            await use_cases.lookup(999, "parlare")
        consumption.increment.assert_not_awaited()


class TestConjugation:

    async def test_found_is_not_counted(self):
        use_cases, _, consumption = _use_cases()

        assert await use_cases.conjugation("parlare") == Found(data=DATA)
        consumption.increment.assert_not_awaited()

    async def test_not_found(self):
        use_cases, _, _ = _use_cases(data=None)

        assert await use_cases.conjugation("parlare") == NotFound(verb="parlare")
