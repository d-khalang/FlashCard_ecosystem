# main.py
import sys, json, time, re
from urllib.parse import urlencode
from collections import OrderedDict
from curl_cffi import requests
from curl_cffi.requests.errors import RequestsError
from bs4 import BeautifulSoup

BASE = "https://www.wordreference.com/conj/itverbs.aspx"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
    "Connection": "keep-alive",
}

# Toggle to raise on missing sections (otherwise we just warn to stderr)
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


def _norm_spaces(s: str) -> str:
    """Turn all whitespace runs (incl. NBSP) into single spaces, then trim."""
    return re.sub(r'\s+', ' ', s.replace('\xa0', ' ')).strip()


def build_url(verb: str) -> str:
    verb = (verb or "").strip()
    if not verb:
        raise ValueError("Empty verb provided.")
    return f"{BASE}?{urlencode({'v': verb})}"


def fetch_html(url: str, timeout=20.0, tries=2) -> str:
    last_err = None
    for attempt in range(1, tries + 1):
        try:
            r = requests.get(
                url,
                headers=HEADERS,
                timeout=timeout,
                allow_redirects=True,
                impersonate="chrome"
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
    return [p for p in parts if p]  # drop empties


def parse_principal_forms(soup: BeautifulSoup) -> dict:
    """
    Extracts the top table (#conjtable) with:
    infinito, gerundio, participio presente, participio passato, forma pronominale
    Also tries to detect model verb (h3 above).
    """
    out = {
        "model": None,
        "forms": {}
    }

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
        # Clean the arrow if present in 'forma pronominale'
        if lbl == "forma pronominale":
            val = val.replace("⇒", "").strip()
        out["forms"][lbl] = val

    return out


def _ordered_tense_map(tense_map: dict, mood: str, tense: str) -> OrderedDict:
    """
    Return an OrderedDict with a stable, human-friendly person order.
    Any unexpected person labels are appended in their original order.
    """
    if mood == "imperativo":
        desired = PERSON_ORDER_IMPERATIVE
    else:
        desired = PERSON_ORDER_DEFAULT

    ordered = OrderedDict()
    # Insert desired keys in order if they exist
    for k in desired:
        if k in tense_map:
            ordered[k] = tense_map[k]

    # Append remaining keys in original order
    for k, v in tense_map.items():
        if k not in ordered:
            ordered[k] = v

    return ordered


def parse_conjugations(soup: BeautifulSoup) -> dict:
    """
    Each big section is inside <div class='aa'> with an <h4> mood title,
    followed by one or more <table class='neoConj'> each containing:
      - a header row with tense name in <th scope='col' colspan=2>
      - then rows with <th scope='row'>person</th> + <td>form</td>
    We build a nested dict: { mood: { tense: { person: form, ... } } }
    """
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
    """
    Heuristic: look at Indicativo → Tempi composti → Passato prossimo → io
    If it starts with 'sono/ero/sarò' → essere, if 'ho/avevo/avrò' → avere.
    Returns 'avere' | 'essere' | None
    """
    # Many pages group the simple/compound tenses under 'tempi composti'
    pp = conjugations.get("tempi composti", {}).get("passato prossimo", {})
    io_pp = pp.get("io", "")
    io_pp_l = io_pp.lower()
    if io_pp_l.startswith(("sono ", "ero ", "sarò ")):
        return "essere"
    if io_pp_l.startswith(("ho ", "avevo ", "avrò ")):
        return "avere"
    return None


def _check_expected(conjugations: dict):
    """Warn (or raise) if expected moods/tenses are missing."""
    missing_msgs = []
    for mood, tenses in EXPECTED.items():
        if mood not in conjugations:
            missing_msgs.append(f"Missing mood: {mood}")
            continue
        got = set(conjugations[mood].keys())
        diff = tenses - got
        if diff:
            missing_msgs.append(f"Missing tense(s) in {mood}: {', '.join(sorted(diff))}")

    if missing_msgs:
        msg = " | ".join(missing_msgs)
        if STRICT_CHECKS:
            raise AssertionError(msg)
        else:
            print(f"[WARN] {msg}", file=sys.stderr)


def scrape_conjugations(queried: str) -> dict:
    url = build_url(queried)
    html = fetch_html(url)
    soup = BeautifulSoup(html, "lxml")

    header = parse_principal_forms(soup)
    conjugations = parse_conjugations(soup)

    # Post-process: auxiliary detection
    auxiliary = _detect_auxiliary(conjugations)

    # Regression checks
    _check_expected(conjugations)

    out = {
        "queried": queried,
        "url": url,
        "model": header.get("model"),
        "principal_forms": header.get("forms", {}),
        "auxiliary": auxiliary,               # "avere" | "essere" | None
        "conjugations": conjugations
    }
    return out


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <italian_verb>")
        sys.exit(1)
    verb = sys.argv[1].strip()


    try:
        data = scrape_conjugations(verb)
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(2)

    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
