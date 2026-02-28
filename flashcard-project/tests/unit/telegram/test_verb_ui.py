"""
Unit tests for verb UI formatting.

Tests format_verb_message (Indicativo Presente overview)
and format_verb_conjugation (specific mood/tense view).
"""
from flashcard.schemas.conjugations import ConjugationResponse
from flashcard.telegram.ui.verb import (
    format_verb_message,
    format_verb_conjugation,
    _format_header,
    _cap,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_conjugation_response(**overrides) -> ConjugationResponse:
    """Create a minimal valid ConjugationResponse."""
    base = {
        "queried": "parlare",
        "url": "https://example.com/parlare",
        "principal_forms": {"infinito": "parlare", "gerundio": "parlando"},
        "auxiliary": "avere",
        "conjugations": {
            "indicativo": {
                "presente": {
                    "io": "parlo",
                    "tu": "parli",
                    "lui, lei, Lei, egli": "parla",
                    "noi": "parliamo",
                    "voi": "parlate",
                    "loro, Loro, essi": "parlano",
                },
                "imperfetto": {
                    "io": "parlavo",
                    "tu": "parlavi",
                    "lui, lei, Lei, egli": "parlava",
                    "noi": "parlavamo",
                    "voi": "parlavate",
                    "loro, Loro, essi": "parlavano",
                },
            },
            "imperativo": {
                "presente": {
                    "(tu)": "parla",
                    "(Lei)": "parli",
                    "(noi)": "parliamo",
                    "(voi)": "parlate",
                    "(Loro)": "parlino",
                },
            },
        },
    }
    base.update(overrides)
    return ConjugationResponse(**base)


# ===================================================================
# _cap helper
# ===================================================================
class TestCapHelper:

    def test_capitalizes_lowercase(self):
        assert _cap("indicativo") == "Indicativo"

    def test_empty_string_returns_empty(self):
        assert _cap("") == ""

    def test_none_returns_empty(self):
        assert _cap(None) == ""


# ===================================================================
# _format_header
# ===================================================================
class TestFormatHeader:

    def test_contains_verb_name(self):
        data = _make_conjugation_response()
        header = _format_header(data)
        assert "parlare" in header

    def test_contains_principal_forms(self):
        data = _make_conjugation_response()
        header = _format_header(data)
        assert "parlando" in header  # gerundio

    def test_contains_auxiliary(self):
        data = _make_conjugation_response()
        header = _format_header(data)
        assert "avere" in header

    def test_missing_auxiliary_shows_dash(self):
        data = _make_conjugation_response(auxiliary=None)
        header = _format_header(data)
        assert "—" in header


# ===================================================================
# format_verb_message (Presente overview)
# ===================================================================
class TestFormatVerbMessage:

    def test_contains_all_conjugations(self):
        data = _make_conjugation_response()
        msg = format_verb_message(data)

        assert "parlo" in msg
        assert "parli" in msg
        assert "parla" in msg
        assert "parliamo" in msg
        assert "parlate" in msg
        assert "parlano" in msg

    def test_contains_header_and_footer(self):
        data = _make_conjugation_response()
        msg = format_verb_message(data)

        assert "parlare" in msg  # header
        assert "pulsanti" in msg  # footer (Italian for buttons)

    def test_html_bold_tags_present(self):
        data = _make_conjugation_response()
        msg = format_verb_message(data)
        assert "<b>" in msg

    def test_missing_tense_uses_fallback(self):
        """If indicativo.presente is missing, should show '?' characters."""
        data = _make_conjugation_response(conjugations={"indicativo": {}})
        msg = format_verb_message(data)
        assert "?" in msg


# ===================================================================
# format_verb_conjugation (specific mood/tense)
# ===================================================================
class TestFormatVerbConjugation:

    def test_standard_mood_tense(self):
        data = _make_conjugation_response()
        msg = format_verb_conjugation(data, "indicativo", "imperfetto")

        assert "parlavo" in msg
        assert "Imperfetto" in msg

    def test_imperativo_format(self):
        """Imperativo has special person labels like (tu), (Lei)."""
        data = _make_conjugation_response()
        msg = format_verb_conjugation(data, "imperativo", "presente")

        assert "parla" in msg
        assert "tu" in msg
        assert "Lei" in msg

    def test_missing_mood_shows_error(self):
        data = _make_conjugation_response()
        msg = format_verb_conjugation(data, "nonexistent", "presente")

        assert "Non trovato" in msg

    def test_missing_tense_shows_error(self):
        data = _make_conjugation_response()
        msg = format_verb_conjugation(data, "indicativo", "nonexistent")

        assert "Non trovato" in msg
