"""
VerbService: the conjugator v2 client (docs/verbs/contract.md section 3), over the shared fixtures.
"""
import pytest

from flashcard.schemas.verbs import (
    TENSE_IDS, Conjugation, Infinitives, InfinitivesRequest, InvalidQuery, Suggestions, VerbNotFound,
)
from flashcard.services.verb import ConjugatorError, ScraperConfig, VerbService
from tests.integration.helpers import FakeHTTPClient, FakeHTTPResponse
from tests.verb_fixtures import REFUSED_QUERY, fake_conjugator, fixture_names, load

SCRAPER = ScraperConfig(url="http://conjugator", port=8080, api_key="test-key")
MODELS = {
    "conjugate-vado.json": Conjugation, "conjugate-fuzzy.json": Conjugation,
    "conjugate-not-found.json": VerbNotFound, "suggest-and.json": Suggestions,
    "infinitives-request.json": InfinitivesRequest, "infinitives-response.json": Infinitives,
}


def _service(http=None) -> VerbService:
    return VerbService(http_client=http or fake_conjugator(), scraper=SCRAPER)


class TestFixtures:

    def test_every_conjugator_fixture_has_a_model(self):
        assert {name.split("/")[1] for name in fixture_names("conjugator")} == set(MODELS)

    @pytest.mark.parametrize("name", fixture_names("conjugator"))
    def test_each_fixture_reads_and_writes_back_unchanged(self, name):
        data = load(name)
        model = MODELS[name.split("/")[1]]

        assert model.model_validate(data).model_dump(mode="json") == data

    def test_the_fixture_verb_has_the_canonical_tenses_in_order(self):
        verb = Conjugation.model_validate(load("conjugator/conjugate-vado.json")).verb

        assert [t.id for t in verb.tenses] == list(TENSE_IDS)
        assert all(sum(f.primary for f in slot.forms) == 1 for t in verb.tenses for slot in t.slots if slot.forms)


class TestQueryFormat:

    @pytest.mark.parametrize("query", ["andare", "vado", "sono andato", "mi alzo", "me ne vado", "l'ho fatto",
                                       "perché", "a b c d", "x" * 60])
    def test_valid(self, query):
        assert _service().is_valid_verb(query)

    @pytest.mark.parametrize("query", ["", "a b c d e", "x" * 61, "sono  andato", " vado", "vado ", "parl4re",
                                       "<b>", "andare-ci", "ñ", "señor", "möchte", "ça", "andare2", "a\tb", None])
    def test_invalid(self, query):
        assert not _service().is_valid_verb(query)

    def test_normalize_collapses_spaces_lowercases_and_uses_the_plain_apostrophe(self):
        assert VerbService.normalize("  Me   NE\tvado ") == "me ne vado"
        assert VerbService.normalize("L’ho fatto") == "l'ho fatto"
        assert VerbService.normalize("‘sto") == "'sto"
        assert VerbService.normalize("perche" + chr(0x301)) == "perché"  # NFC


class TestConjugate:

    async def test_a_form_finds_its_verb(self):
        http = fake_conjugator()
        answer = await _service(http).conjugate("vado")

        assert isinstance(answer, Conjugation)
        assert answer.verb.infinitive == "andare" and answer.match.kind == "form"
        assert http.calls == [{"url": "http://conjugator:8080/v2/conjugate", "params": {"q": "vado"},
                               "headers": {"X-API-Key": "test-key"}}]

    async def test_not_found_is_an_answer_not_an_error(self):
        answer = await _service().conjugate("qwerty")

        assert isinstance(answer, VerbNotFound) and answer.error.code == "verb_not_found"

    async def test_a_400_is_an_invalid_query_not_an_error(self):
        answer = await _service().conjugate(REFUSED_QUERY)

        assert isinstance(answer, InvalidQuery) and answer.error.code == "invalid_query"

    async def test_a_server_error_raises(self):
        with pytest.raises(ConjugatorError):
            await _service(fake_conjugator(broken=True)).conjugate("vado")

    async def test_an_answer_outside_the_contract_raises(self):
        http = FakeHTTPClient(FakeHTTPResponse(200, {"success": True, "data": {}}))  # the v1 shape
        with pytest.raises(ConjugatorError):
            await _service(http).conjugate("vado")

    async def test_a_network_error_raises(self):
        class Down:
            async def get(self, *args, **kwargs):
                raise OSError("connection refused")

        with pytest.raises(ConjugatorError):
            await _service(Down()).conjugate("vado")

    async def test_missing_settings_fail_loudly(self):
        with pytest.raises(RuntimeError):
            await VerbService(http_client=fake_conjugator()).conjugate("vado")


class TestSuggestAndInfinitives:

    async def test_suggest(self):
        http = fake_conjugator()

        items = await _service(http).suggest("and")  # the fixture shows the shape, not the list
        assert all(isinstance(i, str) for i in items)
        assert http.calls[0]["params"] == {"q": "and", "limit": 8}

    async def test_infinitives_are_asked_in_batches_of_500(self):
        http = fake_conjugator()
        words = ["andare", "letto"] + [f"w{i}" for i in range(999)]

        found = await _service(http).infinitives(words)

        assert len(http.calls) == 3 and [len(c["json"]["words"]) for c in http.calls] == [500, 500, 1]
        assert found["andare"] == "andare" and found["letto"] is None and len(found) == len(words)

    async def test_infinitives_error_raises(self):
        with pytest.raises(ConjugatorError):
            await _service(fake_conjugator(broken=True)).infinitives(["andare"])
