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
from .teams import N_TEAMS, resolve

HALF_LIFE_WEEKS = 4.0   # a spread this old counts half as much as last week's
RIDGE = 1.0             # base penalty, at a fully connected comparison graph
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


def sparsity_ridge(n_games: int, base: float = RIDGE) -> float:
    """Ridge scaled by how under-determined the system is.

    Week 1 gives 16 equations for 32 unknowns, and the comparison graph is 16
    disjoint pairs: minimum-norm hands each team roughly half its single
    game's spread with no opponent adjustment at all — yet this is one of five
    equal voices from day one. Shrinking an unidentified estimate toward league
    average is the principled response; a hard games-played gate would instead
    throw away real market information in the weeks it does exist.

    Measured, not asserted: with base=RIDGE on a week-1 shape (16 disjoint
    games, one 7-point favourite each), a favourite's recovered strength is
    1.750 against a minimum-norm value of 3.500 -- a 50% shrink. At base=1e-3
    the same shape recovers 3.497, a 0.09% effect: no shrinkage at all, despite
    what this docstring used to claim. The penalty relaxes automatically as
    the graph connects -- 32/16 = 2x base at week 1, down to ~0.22x base by
    week 10 (32/144 games) -- so the shrink that matters at week 1 is already
    negligible once every team has played everyone it is going to."""
    return float(base) * (N_TEAMS / max(1, int(n_games)))


def strength_from_spreads(games, current_week: int,
                          half_life: float = HALF_LIFE_WEEKS,
                          ridge: float | None = None) -> dict:
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

    lam = sparsity_ridge(len(games)) if ridge is None else float(ridge)
    W = np.diag(w)
    A = X.T @ W @ X + lam * np.eye(n)
    beta = np.linalg.solve(A, X.T @ W @ y)
    beta -= beta.mean()                       # strengths are relative
    return {t: float(beta[idx[t]]) for t in teams}
