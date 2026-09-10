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


def espn_fpi():
    return parse_espn_fpi(_get(ESPN_FPI_URL).json())


# --- EPA efficiency rating (our own, from nflverse play-by-play) ----------

EPA_SEASONS = (2025, 2024)     # try most recent complete season first
EPA_POINTS_SCALE = 50.0        # net EPA/play -> rough points scale


def epa_from_pbp(pbp):
    """Team net EPA/play (offense EPA − defense EPA allowed) from a play-by-play
    frame, as a mean-centered points strength. A DVOA-family efficiency signal:
    backward-looking, so it diverges from the forward projections."""
    if "pass" in pbp.columns and "rush" in pbp.columns:
        p = pbp[(pbp["pass"] == 1) | (pbp["rush"] == 1)]
    else:
        p = pbp
    p = p.dropna(subset=["epa", "posteam", "defteam"])
    off = p.groupby("posteam")["epa"].mean()
    deff = p.groupby("defteam")["epa"].mean()          # lower = better defense
    net = off.sub(deff, fill_value=0.0)
    out = {}
    for team, val in net.items():
        code = resolve(str(team))
        if code is not None:
            out[code] = float(val)
    if not out:
        return {}
    mean = sum(out.values()) / len(out)
    return {c: (v - mean) * EPA_POINTS_SCALE for c, v in out.items()}


def epa_ratings():
    """Compute our own efficiency rating from nflverse play-by-play (free)."""
    import nfl_data_py as nfl
    for yr in EPA_SEASONS:
        try:
            pbp = nfl.import_pbp_data([yr], downcast=True)
        except Exception:
            continue
        if len(pbp):
            out = epa_from_pbp(pbp)
            if out:
                return out
    return {}
