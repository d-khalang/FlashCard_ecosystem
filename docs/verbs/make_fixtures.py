"""Builds the contract fixtures in docs/verbs/fixtures/ for the verb `andare`.

Also the reference for the stem/ending rule (contract.md, "Stem and ending"): the
conjugator implements the same rule and its tests should reproduce these fixtures.

Run from the repo root: python docs/verbs/make_fixtures.py
"""
import json
import unicodedata
from pathlib import Path

OUT = Path(__file__).parent / "fixtures"
PERSONS = ["1s", "2s", "3s", "1p", "2p", "3p"]
IMP_PERSONS = ["2s", "3s", "1p", "2p", "3p"]

# Mood order and tense ids, canonical order (contract.md, "Ids").
TENSES = [
    ("indicativo", "presente", False), ("indicativo", "imperfetto", False),
    ("indicativo", "passato_remoto", False), ("indicativo", "futuro_semplice", False),
    ("indicativo", "passato_prossimo", True), ("indicativo", "trapassato_prossimo", True),
    ("indicativo", "trapassato_remoto", True), ("indicativo", "futuro_anteriore", True),
    ("congiuntivo", "presente", False), ("congiuntivo", "imperfetto", False),
    ("congiuntivo", "passato", True), ("congiuntivo", "trapassato", True),
    ("condizionale", "presente", False), ("condizionale", "passato", True),
    ("imperativo", "presente", False),
]

# Regular -are endings (the class of andare).
REGULAR_ARE = {
    "indicativo-presente": ["o", "i", "a", "iamo", "ate", "ano"],
    "indicativo-imperfetto": ["avo", "avi", "ava", "avamo", "avate", "avano"],
    "indicativo-passato_remoto": ["ai", "asti", "ò", "ammo", "aste", "arono"],
    "indicativo-futuro_semplice": ["erò", "erai", "erà", "eremo", "erete", "eranno"],
    "congiuntivo-presente": ["i", "i", "i", "iamo", "iate", "ino"],
    "congiuntivo-imperfetto": ["assi", "assi", "asse", "assimo", "aste", "assero"],
    "condizionale-presente": ["erei", "eresti", "erebbe", "eremmo", "ereste", "erebbero"],
    "imperativo-presente": ["a", "i", "iamo", "ate", "ino"],
}

# Core endings across classes, per tense and person: used to split irregular forms.
CORE = {
    "indicativo-presente": [["o"], ["i"], ["a", "e"], ["iamo"], ["ate", "ete", "ite"], ["ano", "ono"]],
    "indicativo-futuro_semplice": [["ò"], ["ai"], ["à"], ["emo"], ["ete"], ["anno"]],
    "congiuntivo-presente": [["i", "a"], ["i", "a"], ["i", "a"], ["iamo"], ["iate"], ["ino", "ano"]],
    "condizionale-presente": [["ei"], ["esti"], ["ebbe"], ["emmo"], ["este"], ["ebbero"]],
    "imperativo-presente": [["a", "i", "e"], ["i", "a"], ["iamo"], ["ate", "ete", "ite"], ["ino", "ano"]],
}

SIMPLE = {
    "indicativo-presente": ["vado", "vai", "va", "andiamo", "andate", "vanno"],
    "indicativo-imperfetto": ["andavo", "andavi", "andava", "andavamo", "andavate", "andavano"],
    "indicativo-passato_remoto": ["andai", "andasti", "andò", "andammo", "andaste", "andarono"],
    "indicativo-futuro_semplice": ["andrò", "andrai", "andrà", "andremo", "andrete", "andranno"],
    "congiuntivo-presente": ["vada", "vada", "vada", "andiamo", "andiate", "vadano"],
    "congiuntivo-imperfetto": ["andassi", "andassi", "andasse", "andassimo", "andaste", "andassero"],
    "condizionale-presente": ["andrei", "andresti", "andrebbe", "andremmo", "andreste", "andrebbero"],
    "imperativo-presente": ["vai", "vada", "andiamo", "andate", "vadano"],
}
# Extra variants per slot: (tense_id, person) -> [(text, tags)]
EXTRA = {("imperativo-presente", "2s"): [("va'", [])]}

AUX_ESSERE = {
    "indicativo-passato_prossimo": ["sono", "sei", "è", "siamo", "siete", "sono"],
    "indicativo-trapassato_prossimo": ["ero", "eri", "era", "eravamo", "eravate", "erano"],
    "indicativo-trapassato_remoto": ["fui", "fosti", "fu", "fummo", "foste", "furono"],
    "indicativo-futuro_anteriore": ["sarò", "sarai", "sarà", "saremo", "sarete", "saranno"],
    "congiuntivo-passato": ["sia", "sia", "sia", "siamo", "siate", "siano"],
    "congiuntivo-trapassato": ["fossi", "fossi", "fosse", "fossimo", "foste", "fossero"],
    "condizionale-passato": ["sarei", "saresti", "sarebbe", "saremmo", "sareste", "sarebbero"],
}

STEM = "and"


def split(tense_id: str, index: int, form: str) -> dict:
    regular_ending = REGULAR_ARE[tense_id][index]
    candidates = {regular_ending, *CORE.get(tense_id, [[]] * 6)[index]}
    fits = [e for e in candidates if form.endswith(e) and len(form) > len(e)]
    ending = max(fits, key=len) if fits else ""
    stem = form[: len(form) - len(ending)]
    return {
        "kind": "simple", "clitic": None, "stem": stem, "ending": ending, "enclitic": None,
        "irregular_stem": stem != STEM, "irregular_ending": ending != regular_ending,
    }


def simple_form(text, tense_id, index, primary, tags):
    reg = STEM + REGULAR_ARE[tense_id][index]
    return {"text": text, "primary": primary, "tags": tags, "tts": text,
            "irregular": text != reg, "parts": split(tense_id, index, text)}


def compound_form(aux, participle, primary, tags):
    text = f"{aux} {participle}"
    return {"text": text, "primary": primary, "tags": tags, "tts": text, "irregular": False,
            "parts": {"kind": "compound", "clitic": None, "auxiliary_verb": "essere", "auxiliary": aux,
                      "participle": participle, "irregular_participle": False}}


def build_verb() -> dict:
    tenses = []
    for mood, tense, compound in TENSES:
        tid = f"{mood}-{tense}"
        persons = IMP_PERSONS if mood == "imperativo" else PERSONS
        slots = []
        for i, person in enumerate(persons):
            if compound:
                aux = AUX_ESSERE[tid][i]
                masc, fem = ("andato", "andata") if person.endswith("s") else ("andati", "andate")
                forms = [compound_form(aux, masc, True, []), compound_form(aux, fem, False, ["feminine"])]
            else:
                forms = [simple_form(SIMPLE[tid][i], tid, i, True, [])]
                for text, tags in EXTRA.get((tid, person), []):
                    forms.append(simple_form(text, tid, i, False, tags))
            slots.append({"person": person, "forms": forms})
        tenses.append({"id": tid, "mood": mood, "tense": tense, "compound": compound, "slots": slots})
    return {
        "infinitive": "andare",
        "pronominal": None,
        "auxiliaries": [{"verb": "essere", "primary": True, "note": None}],
        "principal_forms": {"gerund": "andando", "past_participle": "andato", "present_participle": "andante"},
        "irregular": True,
        "data_version": "2026-11-13",
        "tenses": tenses,
    }


def plain(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def drill(verb: dict, tense_id: str) -> dict:
    tense = next(t for t in verb["tenses"] if t["id"] == tense_id)
    items = []
    for slot in tense["slots"]:
        if not slot["forms"]:
            continue
        primary = next(f for f in slot["forms"] if f["primary"])
        accepted = [{"text": f["text"].lower(), "note": None if f["primary"] or not f["tags"] else
                     ("feminine" if "feminine" in f["tags"] else "variant")} for f in slot["forms"]]
        parts = primary["parts"]
        hint = None
        if parts["kind"] == "simple" and parts["irregular_stem"] and parts["ending"]:
            hint = {"kind": "irregular_stem", "stem": parts["stem"]}
        elif parts["kind"] == "simple" and primary["irregular"]:
            hint = {"kind": "irregular_form"}
        items.append({"person": slot["person"], "primary": primary["text"], "accepted": accepted,
                      "accepted_plain": sorted({plain(a["text"]) for a in accepted}), "hint": hint})
    return {"infinitive": verb["infinitive"], "tense_id": tense_id, "items": items,
            "strip_prefixes": ["che io", "che tu", "che lui", "che lei", "che noi", "che voi", "che loro",
                               "io", "tu", "lui", "lei", "noi", "voi", "loro", "che"]}


def write(name: str, data) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    verb = build_verb()
    match = {"query": "vado", "kind": "form", "slots": [{"tense_id": "indicativo-presente", "person": "1s"}],
             "candidates": ["andarsene"]}
    # Conjugator v2 (service to service)
    write("conjugator/conjugate-vado.json", {"match": match, "verb": verb})
    write("conjugator/conjugate-not-found.json",
          {"error": {"code": "verb_not_found", "message": "No verb for 'qwerty'"}, "suggestions": []})
    write("conjugator/conjugate-fuzzy.json", {
        "match": {"query": "andre", "kind": "fuzzy", "slots": [], "candidates": ["andare", "ardere"]},
        "verb": verb})
    write("conjugator/suggest-and.json", {"items": ["andare", "andarsene", "andicappare"]})
    write("conjugator/infinitives-request.json", {"words": ["prendere", "letto", "svegliarsi", "andare d'accordo"]})
    write("conjugator/infinitives-response.json",
          {"infinitives": {"prendere": "prendere", "letto": None, "svegliarsi": "svegliarsi", "andare d'accordo": None}})
    # Mini App API (client to app)
    core = ["indicativo-presente", "indicativo-passato_prossimo", "indicativo-imperfetto",
            "indicativo-futuro_semplice", "imperativo-presente", "condizionale-presente"]
    write("miniapp/lookup-vado.json", {"status": "found", "match": match, "verb": verb,
                                       "level_tenses": core, "meaning": "to go", "in_collection": True})
    write("miniapp/lookup-not-found.json", {"status": "not_found", "query": "qwerty", "suggestions": []})
    write("miniapp/lookup-invalid.json", {"status": "invalid", "query": "123"})
    write("miniapp/suggest-and.json", {"items": ["andare", "andarsene", "andicappare"]})
    write("miniapp/home.json", {"recent": ["essere", "fare", "potere", "uscire"], "collection": [
        {"infinitive": "prendere", "expression_id": "6735a1f0c2a4b1e0d9f00001", "meaning": "to take"},
        {"infinitive": "svegliarsi", "expression_id": "6735a1f0c2a4b1e0d9f00002", "meaning": "to wake up"}]})
    write("miniapp/drill-andare-futuro_semplice.json", drill(verb, "indicativo-futuro_semplice"))
    write("miniapp/drill-andare-passato_prossimo.json", drill(verb, "indicativo-passato_prossimo"))
    write("miniapp/practice-request.json", {"infinitive": "andare", "tense_id": "indicativo-futuro_semplice",
                                            "score": 4, "out_of": 6, "missed": ["1p", "2p"]})
    write("miniapp/examples-ready.json", {"status": "ready", "examples": [
        {"tense_id": "indicativo-presente", "person": "1s", "text": "Domani vado a Roma.",
         "translation": "Tomorrow I'm going to Rome."},
        {"tense_id": "indicativo-futuro_semplice", "person": "1p", "text": "Andremo insieme.",
         "translation": "We will go together."}]})
    write("miniapp/examples-pending.json", {"status": "pending", "retry_after": 2})
    write("miniapp/examples-unavailable.json", {"status": "unavailable"})


if __name__ == "__main__":
    main()
