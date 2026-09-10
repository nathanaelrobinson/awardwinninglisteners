"""Live scrapers for win-total and power-rating sources.

Split into pure parse functions (unit-tested against fixtures) and thin network
fetchers (requests; not unit-tested). Each fetcher returns {team_code: value}.

Add a source by writing a parse_* function + a fetch wrapper, then registering
it in registry.default_sources().
"""
import os
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


def season() -> int:
    """The season every source is asked about. Read at call time, not import
    time, so a test (or next September) can move it with WINSPOOL_SEASON and
    have the whole pipeline follow — a hardcoded year freezes silently."""
    return int(os.environ.get("WINSPOOL_SEASON", "2026"))


def espn_fpi_url(year: int | None = None) -> str:
    return ("https://site.web.api.espn.com/apis/fitt/v3/sports/football/nfl/"
            f"powerindex?region=us&lang=en&season={year or season()}&limit=1000")


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
    return parse_espn_fpi(_get(espn_fpi_url()).json())


# --- EPA efficiency rating (our own, from nflverse play-by-play) ----------

EPA_POINTS_SCALE = 50.0        # net EPA/play -> rough points scale
EPA_SHRINK_K = 8000             # plays at which this season and last count equally
EPA_RIDGE = 1.0                 # regularises the near-singular early-season system

# Only the columns the regression actually reads. import_pbp_data otherwise
# pulls ~380 columns per season and this job holds two seasons live at once on
# a Raspberry Pi; participation is a second download of a file nflverse stopped
# publishing after 2023.
EPA_PBP_COLUMNS = ["pass", "rush", "epa", "posteam", "defteam", "season"]

# Past this week, an empty current-season frame is a FAILURE, not a cold start.
# Falling back to last season is correct in week 1 — that is what the shrinkage
# is for — but in week 6 it means handing back a full 32-team dict of LAST
# year's ratings, which would be stored ok=True with today's timestamp and
# would never look wrong anywhere.
EPA_FALLBACK_MAX_WEEK = 2


def epa_seasons() -> tuple[int, int]:
    """(current, prior) — current is shrunk toward prior."""
    cur = season()
    return cur, cur - 1


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


def epa_ratings(week: int):
    """Opponent-adjusted efficiency from nflverse play-by-play (free), this
    season shrunk toward last so September is not driven by one game.

    `week` is not cosmetic. `nfl_data_py.import_pbp_data` swallows a per-year
    failure internally and returns an EMPTY frame, so "nflverse is down" and
    "the season has not started" arrive looking identical. Before
    `EPA_FALLBACK_MAX_WEEK` we treat that as the cold start it probably is and
    lean on last season; after it we raise, so `refresh_ratings` records
    ok=False with a reason and the health endpoint 503s. The alternative is a
    year-old rating stored with today's timestamp — a failure nobody would ever
    see.

    The returned dict carries a `__meta__` entry (n_plays, w) alongside the 32
    team ratings so the Admin panel can tell a rating that is 2% this season
    from one that is 90% this season. Consumers key by team code, so the extra
    entry is inert to them."""
    import nfl_data_py as nfl
    cur, prior = epa_seasons()

    def _load(year):
        """(frame or None, reason). Never raises: the caller decides whether an
        absent season is fatal, and that depends on the week."""
        try:
            df = nfl.import_pbp_data([year], columns=EPA_PBP_COLUMNS,
                                     downcast=True, include_participation=False)
        except Exception as e:                # noqa: BLE001 - reported upward
            return None, f"{type(e).__name__}: {e}"
        return (df, "") if len(df) else (None, "empty frame")

    cur_pbp, cur_why = _load(cur)
    cur_out = epa_adjusted(cur_pbp) if cur_pbp is not None else {}
    n_plays = _usable_plays(cur_pbp) if cur_pbp is not None else 0
    cur_pbp = None                            # two seasons of pbp will not both fit
    if not cur_out and int(week) > EPA_FALLBACK_MAX_WEEK:
        raise RuntimeError(
            f"no usable {cur} play-by-play at week {week} "
            f"({cur_why or 'no plays survived filtering'}); refusing to store "
            f"{prior} ratings as current")

    prior_pbp, prior_why = _load(prior)
    prior_out = epa_adjusted(prior_pbp) if prior_pbp is not None else {}
    if not cur_out and not prior_out:
        why_c = cur_why or "no usable plays"
        why_p = prior_why or "no usable plays"
        raise RuntimeError(f"no play-by-play for {cur} ({why_c}) or {prior} ({why_p})")

    w = shrink_weight(n_plays) if cur_out else 0.0
    if not prior_out:
        w = 1.0
    out = {t: w * cur_out.get(t, 0.0) + (1 - w) * prior_out.get(t, 0.0)
           for t in set(cur_out) | set(prior_out)}
    out["__meta__"] = {"n_plays": int(n_plays), "w": round(float(w), 4),
                       "season": int(cur), "prior_season": int(prior)}
    return out
