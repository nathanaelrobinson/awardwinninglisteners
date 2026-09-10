"""Live scrapers for win-total and power-rating sources.

Split into pure parse functions (unit-tested against fixtures) and thin network
fetchers (requests; not unit-tested). Each fetcher returns {team_code: value}.

Add a source by writing a parse_* function + a fetch wrapper, then registering
it in registry.default_sources().
"""
import re

import numpy as np
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

EPA_SEASONS = (2026, 2025)     # (current, prior) — current is shrunk toward prior
EPA_POINTS_SCALE = 50.0        # net EPA/play -> rough points scale
EPA_SHRINK_K = 8000             # plays at which this season and last count equally
EPA_RIDGE = 1.0                 # regularises the near-singular early-season system


def shrink_weight(n_plays: int, k: int = EPA_SHRINK_K) -> float:
    """How much this season counts against last. Week 1 is a few hundred plays,
    so this season barely registers; by midseason it dominates. An unstable
    voice is worse than a lagging one when only four voices exist."""
    return float(n_plays) / (float(n_plays) + float(k))


def _prepare(pbp):
    """Filter to real scrimmage plays with a resolvable offence, defence, and
    EPA value — the rows that actually enter the regression. The single
    definition of "a play" that both `epa_adjusted` and `_usable_plays` use, so
    they can never disagree about what they're counting."""
    if "pass" in pbp.columns and "rush" in pbp.columns:
        pbp = pbp[(pbp["pass"] == 1) | (pbp["rush"] == 1)]
    p = pbp.dropna(subset=["epa", "posteam", "defteam"])
    if not len(p):
        return p, [], [], []
    off_codes = [resolve(str(t)) for t in p["posteam"]]
    def_codes = [resolve(str(t)) for t in p["defteam"]]
    keep = [i for i, (o, d) in enumerate(zip(off_codes, def_codes))
            if o is not None and d is not None]
    return p, off_codes, def_codes, keep


def _usable_plays(pbp) -> int:
    """Count of plays that survive `_prepare` — what `shrink_weight` must be
    fed. `EPA_SHRINK_K` is calibrated in these plays, not raw pbp rows."""
    return len(_prepare(pbp)[3])


def epa_adjusted(pbp, ridge: float = EPA_RIDGE) -> dict:
    """Opponent-adjusted net EPA per team, as a mean-centered points strength.

    A plain mean of offensive EPA minus defensive EPA allowed flatters a team
    that has faced weak opponents. Regressing play-level EPA on offence-team and
    defence-team indicators separates the two: the fitted coefficients are what
    a team did *given who it played*. This is what DVOA provides and we cannot
    buy."""
    p, off_codes, def_codes, keep = _prepare(pbp)
    if not keep:
        return {}
    y = p["epa"].to_numpy(dtype=float)[keep]
    teams = sorted({off_codes[i] for i in keep} | {def_codes[i] for i in keep})
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    # One column per team's offence, one per its defence.
    X = np.zeros((len(keep), 2 * n))
    for r, i in enumerate(keep):
        X[r, idx[off_codes[i]]] = 1.0
        X[r, n + idx[def_codes[i]]] = 1.0

    # Ridge: (X'X + λI)β = X'y. λ keeps the system solvable in September, when a
    # team has faced one or two opponents and the columns are near-collinear.
    A = X.T @ X + ridge * np.eye(2 * n)
    beta = np.linalg.solve(A, X.T @ y)
    net = {t: float(beta[idx[t]] - beta[n + idx[t]]) for t in teams}
    mean = sum(net.values()) / len(net)
    return {t: (v - mean) * EPA_POINTS_SCALE for t, v in net.items()}


def epa_ratings():
    """Opponent-adjusted efficiency from nflverse play-by-play (free), this
    season shrunk toward last so September is not driven by one game."""
    import nfl_data_py as nfl
    cur, prior = EPA_SEASONS

    def _load(year):
        try:
            df = nfl.import_pbp_data([year], downcast=True)
            return df if len(df) else None
        except Exception:
            return None

    cur_pbp, prior_pbp = _load(cur), _load(prior)
    cur_out = epa_adjusted(cur_pbp) if cur_pbp is not None else {}
    prior_out = epa_adjusted(prior_pbp) if prior_pbp is not None else {}
    if not cur_out:
        return prior_out
    if not prior_out:
        return cur_out
    w = shrink_weight(_usable_plays(cur_pbp))
    return {t: w * cur_out.get(t, 0.0) + (1 - w) * prior_out.get(t, 0.0)
            for t in set(cur_out) | set(prior_out)}
