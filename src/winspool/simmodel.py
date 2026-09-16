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
                kalshi_dist_path=None, ratings_fetched_at=None, now=None, store=None,
                market=None) -> dict:
    """Everything a client needs to reproduce the live projection's mixture.

    `strength` is one row per rating source, all on a common scale; a season
    picks a row with probability `weights[i]`, adds Normal(0, sigma[t]) to each
    team, then plays every game in `games` with

        home wins  <=>  strength[home] - strength[away] + hfa > scale * Z

    except games whose fourth entry is a probability: those are this week's
    remaining games, priced the same way Standings prices them (market quote
    if we have one, else the blend), and flipped as an independent coin so a
    sampled rating-world does not also decide tonight.

    `banked` already holds the wins from games that have been played, and those
    games are absent from `games` — so a result, once real, is locked into every
    season the client rolls. Pool ties count for every player tied for first.
    """
    played, remaining = live.split_schedule(sched_df)
    week = live.week_of(sched_df)
    banked = live.banked_wins(played)

    reg = sched_df[sched_df["game_type"].str.upper() == "REG"]
    full_home = reg["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    full_away = reg["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    rem_home, rem_away = live.remaining_matchups(remaining)

    matrix, weights, names, sigma_full = live.source_matrix(
        totals_path, power_path, kalshi_dist_path, rem_home, rem_away, store=store,
        banked=banked, cal_home=full_home, cal_away=full_away)
    this_week = live.games_in_week(remaining, week)
    rest = remaining[remaining["week"] != week].reset_index(drop=True)
    sigma = live.season_sigma(live.remaining_games_per_team(rest),
                              base_sigma=sigma_full)
    wh, wa = live.remaining_matchups(this_week)
    p_week, _src = live.week_home_p(matrix, weights, wh, wa, market)
    priced = {(TEAMS[wh[g]], TEAMS[wa[g]]): round(float(p_week[g]), 4)
              for g in range(len(wh))}

    games = []
    for r in remaining.sort_values(["week"], kind="stable").itertuples(index=False):
        p = priced.get((r.home_team, r.away_team)) if int(r.week) == week else None
        games.append([int(r.week), r.home_team, r.away_team, p])

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


def refresh_model(store, sched_df: pd.DataFrame | None = None, market=None) -> dict:
    """Rebuild from the league's rosters and the current schedule + ratings, and
    store it. Pass `sched_df` when the caller already has the schedule in hand:
    loading it means pulling the season from nfl_data_py, which is the whole
    reason this is precomputed rather than built per request. `market` is the
    same this-week map `compute_live` uses; without one we read the odds log."""
    from . import league as _league
    rosters = _league.view(store.get())["rosters"]
    df = live._load_schedule_cached() if sched_df is None else sched_df
    if market is None:
        market = live.market_probs(store.latest_odds(live.SEASON, live.week_of(df)))
    doc = build_model(
        rosters, df, store=store, ratings_fetched_at=live.ratings_fetched_at(store),
        market=market)
    store.put_sim_model(doc)
    return doc


def has_this_week_prices(doc: dict) -> bool:
    """True when every remaining game is a 4-tuple [week, home, away, p|null].

    Empty `games` is current-shape (season over). A missing `games` key, or any
    entry without the price field, is the pre-#39 model and must not be served.
    """
    games = doc.get("games")
    if games is None:
        return False
    return all(len(g) >= 4 for g in games)


def ensure_model(store, sched_df: pd.DataFrame | None = None, market=None) -> dict:
    """Serve the stored sim-model, or rebuild it when the stored shape is stale.

    The Simulations tab rejects 3-tuples. A stored model from before this-week
    prices shipped would brick the tab after deploy if we served it as-is.
    Refresh raises; this does not fall back to the old document.
    """
    doc = store.get_sim_model()
    if doc is not None and has_this_week_prices(doc):
        return doc
    built = refresh_model(store, sched_df=sched_df, market=market)
    if not has_this_week_prices(built):
        raise RuntimeError("refresh_model built a sim-model without this-week prices")
    return built
