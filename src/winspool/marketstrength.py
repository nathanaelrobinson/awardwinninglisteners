"""Team strength inverted from every closing spread we have recorded.

Per-game odds used to do one job — set this week's win probabilities — while
the odds log accumulated more of them every hour. But a spread is a direct
measurement of the difference between two teams, so a season of them
over-determines all 32 strengths. Opponent adjustment is automatic here: the
system is nothing but relative comparisons.
"""
import numpy as np

from .game import HFA
from .gameodds import GameOdds, to_prob
from .teams import resolve

HALF_LIFE_WEEKS = 4.0   # a spread this old counts half as much as last week's
RIDGE = 1e-3            # keeps September solvable, when games < teams
SOURCE_ORDER = ("book", "nflverse", "kalshi")


def _spread_from(o: GameOdds) -> float | None:
    """A spread for this source, home-favoured-negative. Kalshi quotes no
    spread, so its price is converted through the same normal the rest of the
    model uses."""
    if o.spread is not None:
        return float(o.spread)
    p = to_prob(o)
    if p is None or not 0.0 < p < 1.0:
        return None
    from scipy.stats import norm
    from .game import SCALE
    return float(-norm.ppf(p) * SCALE)


def closing_spreads(store, season: int, weeks) -> list:
    """(home, away, spread, week) per game, from the last read logged for it.

    For a finished week that is the true closing line, before kickoff — the
    odds log's retention pass preserves that read specifically because it must
    never be thinned away; this is the thing it was preserved for. For the
    week still in progress, "last read" instead means the most recent snapshot
    logged so far, which may be days ahead of that game's own kickoff and is
    not yet a settled closing line."""
    out = []
    for week in weeks:
        rows = store.odds_for_week(season, week)
        best: dict[tuple, dict] = {}          # (home, away) -> {source: GameOdds}
        for row in sorted(rows, key=lambda r: float(r.get("fetched_at") or 0.0)):
            if row["source"] == "model":
                continue
            for g in row.get("games") or []:
                home, away = resolve(g["home"]), resolve(g["away"])
                if not home or not away:
                    continue
                best.setdefault((home, away), {})[row["source"]] = GameOdds(
                    source=row["source"], home=home, away=away,
                    fetched_at=float(row.get("fetched_at") or 0.0),
                    spread=g.get("spread"), total=g.get("total"),
                    ml_home=g.get("ml_home"), ml_away=g.get("ml_away"),
                    yes_home=g.get("yes_home"), yes_away=g.get("yes_away"))
        for (home, away), by_source in best.items():
            for name in SOURCE_ORDER:
                if name in by_source:
                    s = _spread_from(by_source[name])
                    if s is not None:
                        out.append((home, away, s, week))
                        break
    return out


def strength_from_spreads(games, current_week: int,
                          half_life: float = HALF_LIFE_WEEKS,
                          ridge: float = RIDGE) -> dict:
    """Least squares over `spread = s_away - s_home - HFA`, weighted by recency.

    Strength drifts across a season, so a week-1 spread should not count as much
    as last week's. Returns {} when there is nothing to solve."""
    games = [g for g in games if g[2] is not None]
    if not games:
        return {}
    teams = sorted({t for h, a, _s, _w in games for t in (h, a)})
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    X = np.zeros((len(games), n))
    y = np.zeros(len(games))
    w = np.zeros(len(games))
    for r, (home, away, spread, week) in enumerate(games):
        X[r, idx[away]] = 1.0
        X[r, idx[home]] = -1.0
        y[r] = float(spread) + HFA
        w[r] = 0.5 ** (max(0, current_week - week) / half_life)

    W = np.diag(w)
    A = X.T @ W @ X + ridge * np.eye(n)
    beta = np.linalg.solve(A, X.T @ W @ y)
    beta -= beta.mean()                       # strengths are relative
    return {t: float(beta[idx[t]]) for t in teams}
