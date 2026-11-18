"""
/verb messages from the conjugator v2 verb object: primary forms only, labels built from ids.
Everything that comes from outside (the query, the forms) is HTML-escaped.
"""
from html import escape
from typing import Optional
from urllib.parse import quote

from flashcard.schemas.verbs import Tense, Verb

PERSON_EMOJIS = {
    "io": "👤",
    "tu": "👥",
    "lui/lei": "👩‍💼",
    "noi": "👫",
    "voi": "👥",
    "loro": "👨‍👩‍👧‍👦"
}

PERSON_LABELS = {"1s": "io", "2s": "tu", "3s": "lui/lei", "1p": "noi", "2p": "voi", "3p": "loro"}
# Imperativo: 3s is Lei and 3p is Loro (contract section 1).
IMPERATIVE_LABELS = {"2s": "tu", "3s": "Lei", "1p": "noi", "2p": "voi", "3p": "Loro"}

# The full table online (the old conjugator answered this link itself).
WEB_TABLE_URL = "https://www.wordreference.com/conj/itverbs.aspx?v={verb}"


def _cap(s: Optional[str]) -> str:
    return s.capitalize() if s else ''


def tense_label(tense_id_part: str) -> str:
    """A mood or tense id as a label: "passato_prossimo" -> "Passato prossimo"."""
    return _cap((tense_id_part or "").replace("_", " "))


def web_table_url(infinitive: str) -> str:
    return WEB_TABLE_URL.format(verb=quote(infinitive))


def _auxiliaries(verb: Verb) -> str:
    ordered = sorted(verb.auxiliaries, key=lambda a: not a.primary)
    return " / ".join(a.verb for a in ordered) or '—'


def _format_header(verb: Verb, query: str) -> str:
    gerund = verb.principal_forms.gerund or '—'
    return (
        f"🔤 Requested verb: <b>{escape(query)}</b>\n"
        "________________________\n"
        f"♾️ Infinito (Infinitive): <b>{escape(verb.infinitive)}</b>\n"
        f"🌀 Gerundio (Gerund): <b>{escape(gerund)}</b>\n"
        f"⚙️ Ausiliare (Auxiliary): <b>{escape(_auxiliaries(verb))}</b>"
    )


def _format_footer() -> str:
    return "<i>👉 Altri tempi e modi (Other tenses and moods): usa i pulsanti qui sotto (use the buttons below).</i>"


def _primary_forms(tense: Optional[Tense]) -> dict[str, str]:
    """person -> the primary form's text ("—" for a slot without forms)."""
    if tense is None:
        return {}
    forms: dict[str, str] = {}
    for slot in tense.slots:
        primary = slot.primary
        forms[slot.person] = primary.text if primary else '—'
    return forms


def _person_lines(tense: Tense) -> list[str]:
    forms = _primary_forms(tense)
    if tense.mood == "imperativo":
        return [f"👉 {label} → <b>{escape(forms.get(person, '—'))}</b>"
                for person, label in IMPERATIVE_LABELS.items()]
    return [f"{PERSON_EMOJIS[label]} {label} → <b>{escape(forms.get(person, '—'))}</b>"
            for person, label in PERSON_LABELS.items()]


def format_verb_message(verb: Verb, query: str) -> str:
    """The overview: header and the present indicative."""
    presente = verb.tense("indicativo-presente")
    if presente is None:
        lines = [f"{PERSON_EMOJIS[label]} {label} → <b>?</b>" for label in PERSON_LABELS.values()]
    else:
        lines = _person_lines(presente)
    body = "📚 Presente (Indicativo) — Present (Indicative)\n" + "\n".join(lines)
    return f"{_format_header(verb, query)}\n________________________\n\n{body}\n\n{_format_footer()}"


def format_verb_conjugation(verb: Verb, mood: str, tense: str) -> str:
    """One mood and tense (ids, e.g. "indicativo", "passato_prossimo")."""
    shown = verb.tense(f"{mood}-{tense}")
    if shown is None:
        return (
            f"<b>⚠️ Non trovato</b>\n"
            f"Richiesta: {escape(tense_label(mood))} → {escape(tense_label(tense))}\n\n"
            "Prova un altro tempo o modo."
        )
    html_parts = [
        _format_header(verb, verb.infinitive),
        "________________________",
        "",
        f"📚 {tense_label(shown.mood)} - {tense_label(shown.tense)}",
        *_person_lines(shown),
        "",
        _format_footer(),
    ]
    return "\n".join(html_parts)
