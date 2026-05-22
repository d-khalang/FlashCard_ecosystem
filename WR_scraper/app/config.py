from __future__ import annotations


BASE = "https://www.wordreference.com/conj/itverbs.aspx"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
    "Connection": "keep-alive",
}


# Toggle to raise on missing sections (otherwise only warn to stderr)
STRICT_CHECKS = False


# Expected structure on WordReference Italian conjugations
EXPECTED = {
"indicativo": {"presente", "imperfetto", "passato remoto", "futuro semplice"},
"tempi composti": {"passato prossimo", "trapassato prossimo", "trapassato remoto", "futuro anteriore"},
"congiuntivo": {"presente", "imperfetto", "passato", "trapassato"},
"condizionale": {"presente", "passato"},
"imperativo": {"presente"},
}


# Stable orders for person labels
PERSON_ORDER_DEFAULT = [
"io", "tu", "lui, lei, Lei, egli", "noi", "voi", "loro, Loro, essi"
]
PERSON_ORDER_IMPERATIVE = [
"", "(tu)", "(Lei)", "(noi)", "(voi)", "(Loro)"
]