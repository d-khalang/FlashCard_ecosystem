"""
Verb use cases over the in-memory database and a fake conjugator v2 that answers from the shared
fixtures (docs/verbs/fixtures). Drill payloads must equal the Mini App fixtures exactly.
"""
from datetime import datetime, timezone

import pytest
from bson import ObjectId

from flashcard.app.verb import (
    CORE_TENSES, Conjugated, Drill, StemHint, Found, InvalidPractice, InvalidVerb, NoSuchVerb, NotFound, NoVerb, Recorded,
    VerbUseCases, level_tenses,
)
from flashcard.miniapp.schemas import drill_out
from flashcard.schemas.user import stored_user_id
from flashcard.schemas.verbs import TENSE_IDS
from flashcard.services.consumption import ConsumptionService
from flashcard.services.expression import ExpressionService
from flashcard.services.user import UserService
from flashcard.services.verb import ScraperConfig, VerbService
from flashcard.services.verb_practice import VerbPracticeService
from tests.helpers import TEST_LANGUAGE
from tests.integration.helpers import FakeHTTPClient, FakeHTTPResponse, make_cols
from tests.verb_fixtures import fake_conjugator, load

USER = 7
SCRAPER = ScraperConfig(url="http://conjugator", port=8080, api_key="k")


def _card(value: str, meaning: str | None = None, **extra) -> dict:
    doc = {"_id": ObjectId(), "user_id": stored_user_id(USER), "value": value, "status": "active",
           "created_at": datetime(2026, 11, 1, tzinfo=timezone.utc), **extra}
    if meaning is not None:
        doc["last_card"] = {"card": {"translations": [{"label": "🇬🇧 EN", "text": meaning}]},
                            "settings": {"level": "A2", "primary_language": "en"},
                            "generated_at": datetime(2026, 11, 1, tzinfo=timezone.utc)}
    return doc


def _setup(*, cards=(), level="A2", http=None):
    cols = make_cols(users=[{"user_id": stored_user_id(USER), "target_level": level}], expressions=list(cards))
    use_cases = VerbUseCases(
        verb_service=VerbService(http_client=http or fake_conjugator(), scraper=SCRAPER),
        consumption_service=ConsumptionService(users=cols["users"]),
        user_service=UserService(users=cols["users"], defaults=TEST_LANGUAGE.user_defaults),
        expression_service=ExpressionService(expressions=cols["expression"]),
        practice_service=VerbPracticeService(practice=cols["verb_practice"]),
    )
    return use_cases, cols


def _user(cols) -> dict:
    return cols["users"].docs[0]


class TestParse:

    @pytest.mark.parametrize("text, parsed", [("andare", "andare"), ("  Sono   andato ", "sono andato"),
                                              ("me ne vado", "me ne vado"), ("L’ho fatto", "l'ho fatto")])
    def test_queries_with_spaces_are_normalized(self, text, parsed):
        assert _setup()[0].parse(text) == parsed

    @pytest.mark.parametrize("text", [None, "", "   "])
    def test_nothing_is_no_verb(self, text):
        assert _setup()[0].parse(text) == NoVerb()

    @pytest.mark.parametrize("text", ["123", "a b c d e", "x" * 61, "<b>"])
    def test_invalid_keeps_what_was_typed(self, text):
        assert _setup()[0].parse(text) == InvalidVerb(verb=text.strip())


class TestLookup:

    async def test_found_carries_the_verb_level_tenses_and_the_users_card(self):
        use_cases, cols = _setup(cards=[_card("andare", "to go")])

        result = await use_cases.lookup(USER, "vado")

        assert isinstance(result, Found)
        expected = load("miniapp/lookup-vado.json")
        assert result.match.model_dump() == expected["match"]
        assert result.verb.model_dump(mode="json") == expected["verb"]
        assert set(result.level_tenses) == set(expected["level_tenses"])
        assert (result.meaning, result.in_collection) == ("to go", True)

    async def test_the_card_is_found_ignoring_case(self):
        use_cases, _ = _setup(cards=[_card("Andare")])

        result = await use_cases.lookup(USER, "andare")

        assert (result.meaning, result.in_collection) == (None, True)

    async def test_without_a_card(self):
        use_cases, _ = _setup()

        result = await use_cases.lookup(USER, "andare")

        assert (result.meaning, result.in_collection) == (None, False)

    async def test_found_is_recorded_and_counted(self):
        use_cases, cols = _setup()

        await use_cases.lookup(USER, "vado")

        assert _user(cols)["verbs_recent"] == ["andare"]
        assert _user(cols)["consumption"]["verb_lookups"] == 1

    async def test_recent_verbs_are_newest_first_once_each_at_most_10(self):
        use_cases, cols = _setup()
        _user(cols)["verbs_recent"] = [f"v{i}" for i in range(10)]
        _user(cols)["verbs_recent"][4] = "andare"

        await use_cases.lookup(USER, "andare")

        recent = _user(cols)["verbs_recent"]
        assert recent[0] == "andare" and recent.count("andare") == 1 and len(recent) == 10
        assert recent[1:] == ["v0", "v1", "v2", "v3", "v5", "v6", "v7", "v8", "v9"]

    async def test_eleven_verbs_keep_ten(self):
        use_cases, cols = _setup()
        _user(cols)["verbs_recent"] = [f"v{i}" for i in range(10)]

        await use_cases.lookup(USER, "andare")

        assert _user(cols)["verbs_recent"] == ["andare"] + [f"v{i}" for i in range(9)]

    async def test_not_found_has_suggestions_and_is_neither_recorded_nor_counted(self):
        use_cases, cols = _setup()

        result = await use_cases.lookup(USER, "qwerty")

        assert result == NotFound(query="qwerty", suggestions=[])
        assert "verbs_recent" not in _user(cols) and "consumption" not in _user(cols)

    async def test_an_unparsed_query_is_refused(self):
        with pytest.raises(ValueError):
            await _setup()[0].lookup(USER, "  vado")

    async def test_conjugation_for_navigation_is_not_counted(self):
        use_cases, cols = _setup()

        result = await use_cases.conjugation("andare")

        assert isinstance(result, Conjugated) and result.verb.infinitive == "andare"
        assert "consumption" not in _user(cols) and "verbs_recent" not in _user(cols)


class TestLevelTenses:

    @pytest.mark.parametrize("level", ["A1", "A2", "B1"])
    def test_up_to_b1_the_six_core_tenses(self, level):
        assert set(level_tenses(level)) == set(load("miniapp/lookup-vado.json")["level_tenses"])

    def test_b2_adds_the_subjunctive_and_compound_tenses(self):
        b2 = level_tenses("B2")
        assert set(CORE_TENSES) < set(b2)
        assert {"congiuntivo-presente", "congiuntivo-imperfetto", "condizionale-passato"} <= set(b2)
        assert "indicativo-passato_remoto" not in b2

    @pytest.mark.parametrize("level", ["C1", "C2"])
    def test_c1_and_c2_all_tenses(self, level):
        assert level_tenses(level) == list(TENSE_IDS)

    def test_every_id_is_canonical(self):
        for level in ("A1", "A2", "B1", "B2", "C1", "C2", "unknown"):
            assert set(level_tenses(level)) <= set(TENSE_IDS)


class TestHome:

    async def test_recent_and_collection_verbs_with_meanings(self):
        cards = [_card("prendere", "to take"), _card("letto", "bed"), _card("andare d'accordo", "to get along"),
                 _card("svegliarsi", "to wake up")]
        use_cases, cols = _setup(cards=cards)
        _user(cols)["verbs_recent"] = ["essere", "fare"]
        ids = {doc["value"]: str(doc["_id"]) for doc in cols["expression"].docs}

        home = await use_cases.home(USER)

        assert home.recent == ["essere", "fare"]
        assert {(v.infinitive, v.expression_id, v.meaning) for v in home.collection} == {
            ("prendere", ids["prendere"], "to take"), ("svegliarsi", ids["svegliarsi"], "to wake up")}

    async def test_a_conjugator_failure_leaves_the_collection_empty(self):
        use_cases, _ = _setup(cards=[_card("prendere")], http=fake_conjugator(broken=True))

        home = await use_cases.home(USER)

        assert home.collection == [] and home.recent == []

    async def test_only_one_word_cards_are_sent(self):
        http = fake_conjugator()
        use_cases, _ = _setup(cards=[_card("andare d'accordo"), _card("fare")], http=http)

        await use_cases.home(USER)

        assert http.calls[0]["json"] == {"words": ["fare"]}


class TestSuggest:

    async def test_suggest(self):
        http = fake_conjugator()
        items = await _setup(http=http)[0].suggest("And")  # the fixture shows the shape, not the list
        assert isinstance(items, list) and all(isinstance(i, str) for i in items)
        assert http.calls[0]["params"] == {"q": "and", "limit": 8}

    @pytest.mark.parametrize("prefix", ["", "a", "1x", "x" * 61])
    async def test_short_or_impossible_prefixes_ask_nothing(self, prefix):
        http = fake_conjugator()
        assert await _setup(http=http)[0].suggest(prefix) == []
        assert http.calls == []


class TestDrill:

    @pytest.mark.parametrize("tense_id, fixture", [
        ("indicativo-futuro_semplice", "miniapp/drill-andare-futuro_semplice.json"),
        ("indicativo-passato_prossimo", "miniapp/drill-andare-passato_prossimo.json"),
    ])
    async def test_drill_matches_the_fixture(self, tense_id, fixture):
        result = await _setup()[0].drill("andare", tense_id)

        assert isinstance(result, Drill)
        assert drill_out(result).model_dump(mode="json") == load(fixture)

    async def test_irregular_form_hint_and_variants(self):
        result = await _setup()[0].drill("andare", "imperativo-presente")

        items = {item.person: item for item in result.items}
        assert [i.person for i in result.items] == ["2s", "3s", "1p", "2p", "3p"]
        assert [(a.text, a.note) for a in items["2s"].accepted] == [("vai", None), ("va'", "variant")]
        assert items["3p"].hint == StemHint(stem="vad") and items["1p"].hint is None

    async def test_empty_slots_are_left_out(self):
        answer = load("conjugator/conjugate-vado.json")
        answer["verb"]["tenses"][0]["slots"][0]["forms"] = []
        answer["match"] = {"query": "andare", "kind": "infinitive", "slots": [], "candidates": []}
        http = FakeHTTPClient({"/v2/conjugate": FakeHTTPResponse(200, answer)})

        result = await _setup(http=http)[0].drill("andare", "indicativo-presente")

        assert [i.person for i in result.items] == ["2s", "3s", "1p", "2p", "3p"]

    @pytest.mark.parametrize("infinitive, tense_id", [
        ("andare", "indicativo-presentissimo"), ("qwerty", "indicativo-presente"),
        ("vado", "indicativo-presente"), ("andre", "indicativo-presente"), ("sono andato", "indicativo-presente"),
        ("Andare", "indicativo-presente"),
    ])
    async def test_unknown_verb_or_tense(self, infinitive, tense_id):
        assert await _setup()[0].drill(infinitive, tense_id) == NoSuchVerb()


class TestPractice:

    async def _record(self, use_cases, **overrides):
        body = {**load("miniapp/practice-request.json"), **overrides}
        return await use_cases.record_practice(USER, body["infinitive"], body["tense_id"], body["score"],
                                               body["out_of"], body["missed"])

    async def test_first_and_second_drill(self):
        use_cases, cols = _setup()

        assert await self._record(use_cases) == Recorded()
        assert await self._record(use_cases, score=2, missed=["1s", "2s", "3s", "1p"]) == Recorded()

        [doc] = cols["verb_practice"].docs
        tense = doc["tenses"]["indicativo-futuro_semplice"]
        assert (doc["user_id"], doc["infinitive"]) == (stored_user_id(USER), "andare")
        assert (tense["attempts"], tense["last_score"], tense["best_score"], tense["out_of"]) == (2, 2, 4, 6)
        assert tense["missed"] == ["1s", "2s", "3s", "1p"]
        assert tense["last_at"] == doc["updated_at"]

    async def test_missed_persons_are_stored_in_person_order(self):
        use_cases, cols = _setup()

        await self._record(use_cases, missed=["2p", "1p"])

        assert cols["verb_practice"].docs[0]["tenses"]["indicativo-futuro_semplice"]["missed"] == ["1p", "2p"]

    @pytest.mark.parametrize("overrides", [
        {"score": 7}, {"out_of": 0}, {"score": -1}, {"out_of": 7, "score": 7, "missed": []},
        {"missed": ["9x"]}, {"missed": ["1p", "1p"]}, {"missed": ["1s", "2s", "3s"]},
    ])
    async def test_invalid_results_are_refused(self, overrides):
        use_cases, cols = _setup()

        assert isinstance(await self._record(use_cases, **overrides), InvalidPractice)
        assert cols["verb_practice"].docs == []

    @pytest.mark.parametrize("overrides", [{"infinitive": "qwerty"}, {"tense_id": "indicativo-presentissimo"},
                                           {"infinitive": "vado"}])
    async def test_unknown_verb_or_tense_is_refused(self, overrides):
        use_cases, cols = _setup()

        assert await self._record(use_cases, **overrides) == NoSuchVerb()
        assert cols["verb_practice"].docs == []
