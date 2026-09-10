"""The ensemble as data, for clients that want to roll their own seasons.

`live.compute_live` runs the Monte Carlo on the server and returns summary
statistics. The Simulations tab needs the opposite: not the answers but the
model that produces them, so the browser can roll a hundred thousand seasons,
keep each one, and let you open any single season it drew.

Assembling the ensemble is the expensive, server-only half — backing the market
out of the win totals, calibrating each team's season sigma against Kalshi.
Rolling dice against it is arithmetic. So this ships the strengths and the
schedule (a few KB) instead of pre-rolled outcomes (a megabyte per 20k seasons,
and incompressible, since coin flips carry no redundancy).
"""
import time

import numpy as np
import pandas as pd

from . import live
from .game import HFA, SCALE  # re-exported for tests
from .teams import TEAM_INDEX, TEAMS


def build_model(rosters: dict, sched_df: pd.DataFrame, *, totals_path=None, power_path=None,
                kalshi_dist_path=None, ratings_fetched_at=None, now=None, store=None) -> dict:
    """Everything a client needs to reproduce the live projection's mixture.

    `strength` is one row per rating source, all on a common scale; a season
    picks a row with probability `weights[i]`, adds Normal(0, sigma[t]) to each
    team, then plays every game in `games` with

        home wins  <=>  strength[home] - strength[away] + hfa > scale * Z

    which is exactly `game.win_prob` written as a draw instead of a probability.
    `banked` already holds the wins from games that have been played, and those
    games are absent from `games` — so a result, once real, is locked into every
    season the client rolls.
    """
    played, remaining = live.split_schedule(sched_df)
    week = live.week_of(sched_df)
    banked = live.banked_wins(played)

    reg = sched_df[sched_df["game_type"].str.upper() == "REG"]
    full_home = reg["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    full_away = reg["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)

    matrix, weights, names, sigma_full = live.source_matrix(
        totals_path, power_path, kalshi_dist_path, full_home, full_away, store=store)
    sigma = live.season_sigma(live.remaining_games_per_team(remaining),
                              base_sigma=sigma_full)

    games = [[int(r.week), r.home_team, r.away_team]
             for r in remaining.sort_values(["week"], kind="stable").itertuples(index=False)]

    # Finals are per game, not per week: one Thursday night result is banked and
    # gone from `games` while the rest of its week is still to be played. Ship
    # them so a client can show what is already settled alongside what is not.
    final = [[int(r.week), r.home_team, r.away_team,
              1 if r.home_score > r.away_score else (0 if r.away_score > r.home_score else -1),
              int(r.home_score), int(r.away_score)]
             for r in played.sort_values(["week"], kind="stable").itertuples(index=False)]

    # Round, then put the rounding residual back so a client can sample the
    # source with a plain cumulative comparison and never fall off the end.
    w = [round(float(x), 6) for x in weights]
    w[-1] = round(w[-1] + (1.0 - sum(w)), 6)

    return {
        "week": int(week),
        "computed_at": float(now if now is not None else time.time()),
        "ratings_fetched_at": ratings_fetched_at,
        "hfa": float(HFA), "scale": float(SCALE),
        "players": list(rosters), "rosters": {p: list(t) for p, t in rosters.items()},
        "teams": list(TEAMS),
        "sources": list(names),
        "weights": w,
        "strength": [[round(float(v), 4) for v in row] for row in matrix],
        "sigma": [round(float(v), 4) for v in np.asarray(sigma, dtype=float)],
        "banked": [float(banked[TEAM_INDEX[c]]) for c in TEAMS],
        "weeks": sorted({g[0] for g in games}),
        "played": final,
        "games": games,
    }


def refresh_model(store, sched_df: pd.DataFrame | None = None) -> dict:
    """Rebuild from the league's rosters and the current schedule + ratings, and
    store it. Pass `sched_df` when the caller already has the schedule in hand:
    loading it means pulling the season from nfl_data_py, which is the whole
    reason this is precomputed rather than built per request."""
    from . import league as _league
    rosters = _league.view(store.get())["rosters"]
    doc = build_model(
        rosters, live._load_schedule_cached() if sched_df is None else sched_df,
        store=store, ratings_fetched_at=live.ratings_fetched_at(store))
    store.put_sim_model(doc)
    return doc
