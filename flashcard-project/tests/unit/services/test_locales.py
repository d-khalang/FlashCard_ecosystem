"""
Locale file consistency: every locale matches en.json, and every key the code uses exists.

A missing key is not a soft failure: i18n.get returns the raw key when it is
missing from the configured UI locale, so users would see e.g. "commands.import.success".
"""
import json
import re
import string
from importlib.resources import files
from pathlib import Path

import pytest

LOCALES_DIR = Path(str(files("flashcard").joinpath("resources/locales")))
SOURCE_DIR = Path(str(files("flashcard")))
REFERENCE = "en"

# Double-encoded UTF-8, e.g. "giÃ " for "già" or "ðŸ" for an emoji.
MOJIBAKE = re.compile("[ÃÂâð][\u0080-ÿŒ-™]")
KEY_LITERAL = re.compile(r"""["']((?:commands|callbacks|messages)(?:\.[a-z0-9_]+)+)["']""")


def _flatten(node, prefix=""):
    out = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, path))
        else:
            out[path] = value
    return out


def _load(code):
    return _flatten(json.loads((LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8")))


def _placeholders(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


LOCALES = sorted(p.stem for p in LOCALES_DIR.glob("*.json"))
OTHER_LOCALES = [code for code in LOCALES if code != REFERENCE]


def test_reference_and_other_locales_exist():
    assert REFERENCE in LOCALES
    assert OTHER_LOCALES


@pytest.mark.parametrize("code", OTHER_LOCALES)
def test_locale_has_exactly_the_reference_keys(code):
    reference, locale = _load(REFERENCE), _load(code)

    assert sorted(set(reference) - set(locale)) == [], f"missing in {code}.json"
    assert sorted(set(locale) - set(reference)) == [], f"only in {code}.json"


@pytest.mark.parametrize("code", OTHER_LOCALES)
def test_locale_uses_the_reference_placeholders(code):
    reference, locale = _load(REFERENCE), _load(code)

    mismatched = {key: (sorted(_placeholders(reference[key])), sorted(_placeholders(locale[key])))
                  for key in reference.keys() & locale.keys()
                  if _placeholders(reference[key]) != _placeholders(locale[key])}
    assert mismatched == {}


@pytest.mark.parametrize("code", LOCALES)
def test_locale_values_are_non_empty_strings_without_mojibake(code):
    locale = _load(code)

    assert [k for k, v in locale.items() if not isinstance(v, str) or not v.strip()] == []
    assert [k for k, v in locale.items() if MOJIBAKE.search(v)] == []


def test_every_key_used_in_code_exists():
    reference = _load(REFERENCE)
    used = {}
    for path in SOURCE_DIR.rglob("*.py"):
        for key in KEY_LITERAL.findall(path.read_text(encoding="utf-8")):
            used.setdefault(key, path.relative_to(SOURCE_DIR).as_posix())

    assert {k: f for k, f in used.items() if k not in reference} == {}
