"""Live scrapers for win-total and power-rating sources.

Split into pure parse functions (unit-tested against fixtures) and thin network
fetchers (requests; not unit-tested). Each fetcher returns {team_code: value}.

Add a source by writing a parse_* function + a fetch wrapper, then registering
it in registry.default_sources().
"""
import re

import requests
from bs4 import BeautifulSoup

from ..teams import resolve

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
HEADERS = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
TIMEOUT = 25

COVERS_URL = "https://www.covers.com/nfl/nfl-odds-win-totals"
BETMGM_URL = ("https://sports.betmgm.com/en/blog/nfl/"
              "nfl-odds-predictions-season-win-totals-bm16/")
ESPN_FPI_URL = ("https://site.web.api.espn.com/apis/fitt/v3/sports/football/nfl/"
                "powerindex?region=us&lang=en&season=2026&limit=1000")


def _num(text):
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(m.group()) if m else None


# --- pure parsers (unit-tested) -------------------------------------------

def parse_win_total_table(html):
    """Parse a Covers/BetMGM-style HTML table: first column is the team, and one
    column header contains 'total'. Returns {code: win_total}."""
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        tot_idx = next((i for i, h in enumerate(header) if "total" in h), None)
        if tot_idx is None:
            continue
        out = {}
        for tr in rows[1:]:
            cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) <= tot_idx or not cells:
                continue
            code = resolve(cells[0])
            val = _num(cells[tot_idx])
            if code and val is not None:
                out[code] = val
        if len(out) >= 20:  # a real 32-team table, not some unrelated table
            return out
    return {}


def parse_espn_fpi(data):
    """ESPN powerindex JSON -> {code: FPI rating (points vs avg)}.
    Each team's 'fpi' category's first value is the overall FPI rating."""
    out = {}
    for item in data.get("teams", []):
        code = resolve(item.get("team", {}).get("displayName", ""))
        if not code:
            continue
        for cat in item.get("categories", []):
            if cat.get("name") == "fpi":
                vals = cat.get("values") or []
                if vals:
                    out[code] = float(vals[0])
    return out


# --- network fetchers (not unit-tested; live smoke test only) -------------

def _get(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def covers_totals():
    return parse_win_total_table(_get(COVERS_URL).text)


def betmgm_totals():
    return parse_win_total_table(_get(BETMGM_URL).text)


def espn_fpi():
    return parse_espn_fpi(_get(ESPN_FPI_URL).json())


# --- nfelo (JS-rendered; needs a headless browser) ------------------------

NFELO_URL = "https://www.nfeloapp.com/nfl-power-ratings/"
ELO_PER_POINT = 25.0  # ~25 Elo points per point of point-spread (538 convention)


def _render(url, wait_ms=2500):
    """Return fully-rendered HTML via headless Chromium (playwright)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(wait_ms)
        html = page.content()
        browser.close()
    return html


def parse_nfelo(html):
    """Rendered nfelo table -> {code: raw Elo rating}. The team cell looks like
    'SeahawksSEA17-3' (nickname + abbrev + record); we resolve the nickname."""
    soup = BeautifulSoup(html, "lxml")
    out = {}
    for tr in soup.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
        if len(cells) < 3:
            continue
        m = re.match(r"^(.*?)[A-Z]{2,3}\d+-\d+(?:-\d+)?$", cells[1])
        if not m:
            continue
        code = resolve(m.group(1))
        rating = _num(cells[2])
        if code and rating is not None:
            out[code] = rating
    return out


def nfelo_power():
    """nfelo Elo ratings, converted to a mean-centered points strength."""
    elos = parse_nfelo(_render(NFELO_URL))
    if not elos:
        return {}
    mean = sum(elos.values()) / len(elos)
    return {code: (elo - mean) / ELO_PER_POINT for code, elo in elos.items()}


# --- Mike Clay projections (ESPN PDF) -------------------------------------

CLAY_URL = ("https://g.espncdn.com/s/ffldraftkit/26/"
            "NFLDK2026_CS_ClayProjections2026.pdf")


def parse_clay_page(text):
    """One team page of Clay's PDF -> (code, projected_wins) or None.
    Title looks like '2026 Arizona Cardinals Projections'; the box reads
    'PROJECTED WINS: 3.6 (NFL RANK: 31)'."""
    if not text:
        return None
    m_team = re.search(r"20\d\d\s+(.+?)\s+Projections", text)
    m_win = re.search(r"PROJECTED WINS:\s*([\d.]+)", text)
    if not (m_team and m_win):
        return None
    code = resolve(m_team.group(1))
    if code is None:
        return None
    return code, float(m_win.group(1))


def clay_projections():
    """Clay's projected wins per team, converted to a mean-centered points
    strength. Downloads the PDF and reads the per-team pages."""
    import io
    import pdfplumber
    from ..ratings import WINS_PER_POINT
    raw = _get(CLAY_URL).content
    wins = {}
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages[1:33]:            # team pages (2–33)
            parsed = parse_clay_page(page.extract_text() or "")
            if parsed:
                wins[parsed[0]] = parsed[1]
    if not wins:
        return {}
    mean = sum(wins.values()) / len(wins)
    return {code: (w - mean) / WINS_PER_POINT for code, w in wins.items()}
