from __future__ import annotations

LANG_LABELS: dict[str, str] = {
    "en": "🇬🇧 EN",
    "fa": "🇮🇷 FA",
    "de": "🇩🇪 DE",
    "it": "🇮🇹 IT",
    "fr": "🇫🇷 FR",
    "es": "🇪🇸 ES",
    "pt": "🇵🇹 PT",
    "tr": "🇹🇷 TR",
    "ru": "🇷🇺 RU",
    # add as needed
}

def label_for(lang: str) -> str:
    lang = (lang or "").strip().lower()
    return LANG_LABELS.get(lang, f"🏳️ {lang.upper() if lang else '??'}")
