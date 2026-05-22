from __future__ import annotations
import sys, time, re, random
from urllib.parse import urlencode
from collections import OrderedDict
from typing import Dict, Any
from curl_cffi import requests
from curl_cffi.requests.errors import RequestsError
from bs4 import BeautifulSoup


from .config import BASE, HOMEPAGE_URL, HEADERS, STRICT_CHECKS, EXPECTED, PERSON_ORDER_DEFAULT, PERSON_ORDER_IMPERATIVE


# ------------------------
# Session management
# ------------------------

# Persistent session: impersonates Chrome TLS fingerprint and carries cookies
_session: requests.Session | None = None
_session_warmed: bool = False


def _get_session() -> requests.Session:
    """Return (and lazily create) a persistent Chrome-impersonating session."""
    global _session
    if _session is None:
        _session = requests.Session(impersonate="chrome")
    return _session


def _warm_session(session: requests.Session, timeout: float = 15.0) -> None:
    """Visit the WR homepage once to acquire session cookies."""
    global _session_warmed
    if _session_warmed:
        return
    try:
        session.get(HOMEPAGE_URL, headers=HEADERS, timeout=timeout)
        _session_warmed = True
        # Small random delay to look like a human clicking through
        time.sleep(0.5 + random.random())
    except RequestsError:
        # Non-fatal: proceed without warm-up cookies
        pass


# ------------------------
# Utilities
# ------------------------


def _norm_spaces(s: str) -> str:
    """Turn all whitespace runs (incl. NBSP) into single spaces, then trim."""
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def build_url(verb: str) -> str:
    verb = (verb or "").strip()
    if not verb:
        raise ValueError("Empty verb provided.")
    return f"{BASE}?{urlencode({'v': verb})}"


def fetch_html(url: str, timeout: float = 20.0, tries: int = 2) -> str:
    session = _get_session()
    _warm_session(session, timeout=timeout)

    last_err = None
    for attempt in range(1, tries + 1):
        try:
            r = session.get(
                url,
                headers=HEADERS,
                timeout=timeout,
                allow_redirects=True,
            )
            r.raise_for_status()
            return r.text
        except RequestsError as e:
            last_err = e
            if attempt < tries:
                time.sleep(1.0 * attempt)
    raise last_err


def lines_from_td_br_only(td) -> list[str]:
    """
    Split TD into lines ONLY at <br>, preserving normal spaces
    (so 'ho ' + <b>mess</b><b>o</b> => 'ho messo').
    """
    TOKEN = "<<<BR>>>"
    for br in td.find_all("br"):
        br.replace_with(TOKEN)
    raw = td.get_text("", strip=False)
    parts = [_norm_spaces(p) for p in raw.split(TOKEN)]
    return [p for p in parts if p]


def parse_principal_forms(soup: BeautifulSoup) -> dict:
    out = {"model": None, "forms": {}}

    h3 = soup.find("h3")
    if h3:
        out["model"] = h3.get_text(strip=True)

    table = soup.find("table", id="conjtable")
    if not table:
        return out

    first_tr = table.find("tr")
    if not first_tr:
        return out

    tds = first_tr.find_all("td")
    if not tds:
        return out

    label_td = tds[0]
    labels = lines_from_td_br_only(label_td)
    labels = [lbl.lower().rstrip(":") for lbl in labels]

    values_td = tds[1] if len(tds) > 1 else None
    values = lines_from_td_br_only(values_td) if values_td else []

    for i, lbl in enumerate(labels):
        val = values[i] if i < len(values) else ""
        if lbl == "forma pronominale":
            val = val.replace("⇒", "").strip()
        out["forms"][lbl] = val

    return out


def _ordered_tense_map(tense_map: dict, mood: str, tense: str) -> OrderedDict:
    if mood == "imperativo":
        desired = PERSON_ORDER_IMPERATIVE
    else:
        desired = PERSON_ORDER_DEFAULT

    ordered = OrderedDict()
    for k in desired:
        if k in tense_map:
            ordered[k] = tense_map[k]
    for k, v in tense_map.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


def parse_conjugations(soup: BeautifulSoup) -> dict:
    result: dict[str, dict] = {}
    for section in soup.find_all("div", class_="aa"):
        mood_h4 = section.find("h4")
        if not mood_h4:
            continue
        mood = mood_h4.get_text(strip=True).lower()
        if mood not in result:
            result[mood] = {}

        for table in section.find_all("table", class_="neoConj"):
            header_tr = table.find("tr")
            tense = None
            if header_tr:
                th_col = header_tr.find("th", attrs={"scope": "col"})
                if th_col:
                    for span in th_col.find_all("span", class_="arrow"):
                        span.extract()
                    tense = th_col.get_text(strip=True).lower()
            if not tense:
                tense = "?"

            tense_map = {}
            for tr in table.find_all("tr")[1:]:
                th = tr.find("th", attrs={"scope": "row"})
                td = tr.find("td")
                if not th or not td:
                    continue
                person = th.get_text(strip=True)
                raw_form = td.get_text("", strip=False)
                form = _norm_spaces(raw_form)
                tense_map[person] = form

            result[mood][tense] = _ordered_tense_map(tense_map, mood, tense)

    return result


def _detect_auxiliary(conjugations: dict) -> str | None:
    pp = conjugations.get("tempi composti", {}).get("passato prossimo", {})
    io_pp = pp.get("io", "").lower()
    if io_pp.startswith(("sono ", "ero ", "sarò ")):
        return "essere"
    if io_pp.startswith(("ho ", "avevo ", "avrò ")):
        return "avere"
    return None


def _check_expected(conjugations: dict):
    missing = []
    for mood, tenses in EXPECTED.items():
        if mood not in conjugations:
            missing.append(f"Missing mood: {mood}")
            continue
        got = set(conjugations[mood].keys())
        diff = tenses - got
        if diff:
            missing.append(f"Missing tense(s) in {mood}: {', '.join(sorted(diff))}")
    if missing:
        msg = " | ".join(missing)
        if STRICT_CHECKS:
            raise AssertionError(msg)
        else:
            print(f"[WARN] {msg}", file=sys.stderr)


def scrape_conjugations(verb: str) -> dict:
    url = build_url(verb)
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    header = parse_principal_forms(soup)
    conjugations = parse_conjugations(soup)

    auxiliary = _detect_auxiliary(conjugations)
    _check_expected(conjugations)

    return {
        "queried": verb,
        "url": url,
        "model": header.get("model"),
        "principal_forms": header.get("forms", {}),
        "auxiliary": auxiliary,
        "conjugations": conjugations,
    }