"""
Unit tests for the /verb messages built from the conjugator v2 verb object
(format_verb_message: the present overview; format_verb_conjugation: one mood and tense).
"""
from flashcard.schemas.verbs import Conjugation, Verb
from flashcard.telegram.ui.verb import (
    _cap, _format_header, format_verb_conjugation, format_verb_message, tense_label, web_table_url,
)
from tests.verb_fixtures import load


def _verb(**changes) -> Verb:
    data = load("conjugator/conjugate-vado.json")["verb"]
    data.update(changes)
    return Conjugation.model_validate({"match": load("conjugator/conjugate-vado.json")["match"], "verb": data}).verb


class TestLabels:

    def test_cap(self):
        assert (_cap("indicativo"), _cap(""), _cap(None)) == ("Indicativo", "", "")

    def test_labels_come_from_ids(self):
        assert tense_label("passato_prossimo") == "Passato prossimo"
        assert tense_label("condizionale") == "Condizionale"

    def test_web_table_url_quotes_the_verb(self):
        assert web_table_url("andare") == "https://www.wordreference.com/conj/itverbs.aspx?v=andare"
        assert web_table_url("farsi'è").endswith("v=farsi%27%C3%A8")


class TestFormatHeader:

    def test_query_infinitive_gerund_and_auxiliary(self):
        header = _format_header(_verb(), "vado")

        assert "Requested verb: <b>vado</b>" in header
        assert "<b>andare</b>" in header and "<b>andando</b>" in header and "<b>essere</b>" in header

    def test_two_auxiliaries_primary_first(self):
        verb = _verb(auxiliaries=[{"verb": "avere", "primary": False, "note": None},
                                  {"verb": "essere", "primary": True, "note": None}])
        assert "<b>essere / avere</b>" in _format_header(verb, "correre")

    def test_missing_gerund_and_auxiliary_show_a_dash(self):
        verb = _verb(auxiliaries=[], principal_forms={"gerund": None, "past_participle": None,
                                                      "present_participle": None})
        header = _format_header(verb, "x")
        assert "Gerund): <b>—</b>" in header and "Auxiliary): <b>—</b>" in header

    def test_query_is_escaped(self):
        assert "&lt;b&gt;" in _format_header(_verb(), "<b>")


class TestFormatVerbMessage:

    def test_present_with_primary_forms(self):
        msg = format_verb_message(_verb(), "andare")

        for line in ["io → <b>vado</b>", "tu → <b>vai</b>", "lui/lei → <b>va</b>", "noi → <b>andiamo</b>",
                     "voi → <b>andate</b>", "loro → <b>vanno</b>"]:
            assert line in msg
        assert "pulsanti" in msg

    def test_missing_present_uses_fallback(self):
        verb = _verb()
        verb.tenses = [t for t in verb.tenses if t.id != "indicativo-presente"]
        assert "io → <b>?</b>" in format_verb_message(verb, "andare")


class TestFormatVerbConjugation:

    def test_compound_tense_shows_primary_forms_only(self):
        msg = format_verb_conjugation(_verb(), "indicativo", "passato_prossimo")

        assert "📚 Indicativo - Passato prossimo" in msg
        assert "io → <b>sono andato</b>" in msg and "andata" not in msg

    def test_the_tense_name_from_the_conjugator_is_escaped(self):
        verb = _verb()
        verb.tense("indicativo-presente").tense = "<b>&"

        assert "📚 Indicativo - &lt;b&gt;&amp;" in format_verb_conjugation(verb, "indicativo", "presente")

    def test_imperativo_has_five_persons(self):
        msg = format_verb_conjugation(_verb(), "imperativo", "presente")

        assert "👉 tu → <b>vai</b>" in msg and "👉 Lei → <b>vada</b>" in msg and "👉 Loro → <b>vadano</b>" in msg
        assert " io → " not in msg

    def test_empty_slot_shows_a_dash(self):
        verb = _verb()
        verb.tense("indicativo-presente").slots[0].forms = []
        assert "io → <b>—</b>" in format_verb_conjugation(verb, "indicativo", "presente")

    def test_missing_tense_shows_not_found(self):
        msg = format_verb_conjugation(_verb(), "indicativo", "nonexistent")

        assert "Non trovato" in msg and "Indicativo → Nonexistent" in msg
