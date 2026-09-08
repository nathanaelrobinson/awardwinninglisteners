"""In-season live projection: banked wins plus a remaining-season Monte Carlo.

Pure functions over the nfl_data_py schedule frame (columns week, game_type,
home_team, away_team, home_score, away_score) and the data/cache ratings files.
No store or network access except in refresh_live()."""
import json
import os
import time

import numpy as np
import pandas as pd

from .data import load_power_ratings, load_win_totals
from .game import HFA, SCALE, win_prob
from .market import load_distributions, sample_independent
from .ratings import backout_market, to_common_scale
from .sim import simulate_mixture
from .teams import N_TEAMS, TEAM_INDEX, TEAMS

REG_COLS = ["week", "game_type", "home_team", "away_team", "home_score", "away_score"]
FINAL_WEEK = 18


def _reg(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["game_type"].str.upper() == "REG"].reset_index(drop=True)


def split_schedule(df: pd.DataFrame):
    """(played, remaining) regular-season frames. A game is played when both
    scores are present."""
    reg = _reg(df)
    final = reg["home_score"].notna() & reg["away_score"].notna()
    return reg[final].reset_index(drop=True), reg[~final].reset_index(drop=True)


def banked_wins(played: pd.DataFrame) -> np.ndarray:
    """Real wins so far per team index; a tie is 0.5 to each side."""
    b = np.zeros(N_TEAMS)
    for r in played.itertuples(index=False):
        h, a = TEAM_INDEX[r.home_team], TEAM_INDEX[r.away_team]
        if r.home_score > r.away_score:
            b[h] += 1
        elif r.away_score > r.home_score:
            b[a] += 1
        else:
            b[h] += 0.5
            b[a] += 0.5
    return b


def week_of(df: pd.DataFrame) -> int:
    """Smallest regular-season week with an unplayed game; FINAL_WEEK + 1 if none."""
    _, remaining = split_schedule(df)
    if remaining.empty:
        return FINAL_WEEK + 1
    return int(remaining["week"].min())


def remaining_matchups(remaining: pd.DataFrame):
    home = remaining["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    away = remaining["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    return home, away


def games_in_week(remaining: pd.DataFrame, week: int) -> pd.DataFrame:
    return remaining[remaining["week"] == week].reset_index(drop=True)


def remaining_games_per_team(remaining: pd.DataFrame) -> np.ndarray:
    home, away = remaining_matchups(remaining)
    per = np.zeros(N_TEAMS, dtype=int)
    np.add.at(per, home, 1)
    np.add.at(per, away, 1)
    return per


VEGAS_FADE_WEEK = 9


def vegas_weight(week: int) -> float:
    """Pre-season Vegas totals stop updating in-season: fade them out linearly
    so they carry no weight from week 9 on."""
    return max(0.0, 1.0 - week / VEGAS_FADE_WEEK)


def source_matrix_for_week(totals_path, power_path, full_home, full_away, week):
    """(matrix, weights, names). Vegas (backed out of full-season O/U) first when
    the totals file exists, then every power column. Weights: Vegas gets
    vegas_weight(week); power columns share the rest equally."""
    sources = {}
    if totals_path and os.path.exists(totals_path):
        totals = load_win_totals(totals_path)
        sources["vegas"] = backout_market(totals, full_home, full_away, hfa=HFA, scale=SCALE)
    pdf = load_power_ratings(power_path)
    for col in pdf.columns:
        arr = np.zeros(N_TEAMS)
        for code, val in pdf[col].items():
            if code in TEAM_INDEX:
                arr[TEAM_INDEX[code]] = float(val)
        sources[col] = arr
    names = list(sources)
    matrix = to_common_scale(sources)
    n_power = len(names) - (1 if "vegas" in sources else 0)
    if "vegas" in sources and n_power > 0:
        wv = vegas_weight(week)
        weights = np.array([wv] + [(1.0 - wv) / n_power] * n_power)
    else:
        weights = np.full(len(names), 1.0 / len(names))
    return matrix, weights, names


def season_sigma(remaining_per_team, base_sigma=4.5) -> np.ndarray:
    """Season noise shrinks with games left: fewer games, less room for a team
    to be 'different from its rating' this year."""
    per = np.asarray(remaining_per_team, dtype=float)
    return base_sigma * np.sqrt(per / 17.0)


def consensus(matrix, weights) -> np.ndarray:
    return np.asarray(weights, dtype=float) @ np.asarray(matrix, dtype=float)


def pool_pwin(totals: dict) -> dict:
    """P(win pool) per player with ties counting for everyone tied (>= rule)."""
    names = list(totals)
    stack = np.stack([np.asarray(totals[n], dtype=float) for n in names], axis=1)
    rowmax = stack.max(axis=1)
    return {n: float((stack[:, i] >= rowmax).mean()) for i, n in enumerate(names)}


def _player_totals(rosters: dict, team_wins: np.ndarray) -> dict:
    """{player: (N,) array} from a (N, 32) per-team wins matrix."""
    out = {}
    for p, codes in rosters.items():
        idx = [TEAM_INDEX[c] for c in codes]
        out[p] = team_wins[:, idx].sum(axis=1) if idx else np.zeros(team_wins.shape[0])
    return out


def _dist(col, lo, n_bins):
    """Histogram of totals over the integer grid starting at lo. Half-integer
    totals (a team with a tie) round up, so distinct totals stay distinct."""
    idx = np.floor(np.asarray(col, dtype=float) - lo + 0.5).astype(int)
    counts = np.bincount(np.clip(idx, 0, n_bins - 1), minlength=n_bins)
    return (counts / max(counts.sum(), 1)).round(5).tolist()


def market_pwin(rosters: dict, kalshi_dist_path, n_sims: int, rng):
    """Kalshi-implied P(win pool): draw each team's season total from its market
    PMF independently (as `winspool market` does) and apply the >= rule.
    None when the distributions file is missing."""
    if not kalshi_dist_path or not os.path.exists(kalshi_dist_path):
        return None
    codes, mat = load_distributions(kalshi_dist_path)
    draws = sample_independent(mat, n_sims, rng)              # (N, n_codes)
    col = {c: i for i, c in enumerate(codes)}
    totals = {}
    for p, teams in rosters.items():
        idx = [col[t] for t in teams if t in col]
        totals[p] = draws[:, idx].sum(axis=1) if idx else np.zeros(n_sims)
    return {p: round(v, 3) for p, v in pool_pwin(totals).items()}


def compute_live(rosters: dict, sched_df: pd.DataFrame, *, totals_path, power_path,
                 kalshi_dist_path, ratings_fetched_at, n_seasons=5000, seed=0,
                 now=None) -> dict:
    """The live projection document. See the spec for the field list."""
    rng = np.random.default_rng(seed)
    played, remaining = split_schedule(sched_df)
    week = week_of(sched_df)
    banked = banked_wins(played)
    reg = _reg(sched_df)
    full_home = reg["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    full_away = reg["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    matrix, weights, _names = source_matrix_for_week(totals_path, power_path,
                                                     full_home, full_away, week)
    strength = consensus(matrix, weights)

    # This week's games are drawn explicitly so a single game can be forced
    # (leverage); the rest of the season goes through the mixture sim.
    this_week = games_in_week(remaining, week)
    rest = remaining[remaining["week"] != week].reset_index(drop=True)
    sigma = season_sigma(remaining_games_per_team(rest))
    if len(rest):
        rh, ra = remaining_matchups(rest)
        future_rest = simulate_mixture(matrix, rh, ra, n_seasons, base_sigma=sigma,
                                       tie_base=0.003, weights=weights, rng=rng).astype(float)
    else:
        future_rest = np.zeros((n_seasons, N_TEAMS))

    wh, wa = remaining_matchups(this_week)
    p_home = win_prob(strength[wh], strength[wa]) if len(wh) else np.zeros(0)
    week_outcomes = rng.random((n_seasons, len(wh))) < p_home[None, :]   # True = home wins

    def week_wins(outcomes):
        w = np.zeros((n_seasons, N_TEAMS))
        for g in range(outcomes.shape[1]):
            w[:, wh[g]] += outcomes[:, g]
            w[:, wa[g]] += ~outcomes[:, g]
        return w

    def totals_for(outcomes):
        return banked[None, :] + future_rest + week_wins(outcomes)

    team_totals = totals_for(week_outcomes)
    totals = _player_totals(rosters, team_totals)
    pwin = pool_pwin(totals)
    stack = np.stack(list(totals.values()), axis=1)
    lo, hi = int(np.floor(stack.min())), int(np.ceil(stack.max()))
    xs = list(range(lo, hi + 1))
    mkt = market_pwin(rosters, kalshi_dist_path, n_seasons, rng)

    rows = []
    for p, col in totals.items():
        teams = [{"code": c, "banked": float(banked[TEAM_INDEX[c]]),
                  "exp_wins": round(float(team_totals[:, TEAM_INDEX[c]].mean()), 1)}
                 for c in rosters[p]]
        teams.sort(key=lambda t: t["exp_wins"], reverse=True)
        rows.append({
            "player": p, "teams": teams,
            "banked": float(sum(t["banked"] for t in teams)),
            "exp_wins": round(float(col.mean()), 1),
            "pwin": round(pwin[p], 3),
            "market_pwin": None if mkt is None else mkt.get(p),
            "p10": int(round(float(np.percentile(col, 10)))),
            "p90": int(round(float(np.percentile(col, 90)))),
            "dist": _dist(col, lo, len(xs)),
        })
    rows.sort(key=lambda r: (r["pwin"], r["exp_wins"]), reverse=True)

    # Leverage: for each of my games this week, |pwin if we win - pwin if we lose|.
    tw_rows = []
    for p, codes in rosters.items():
        mine = set(codes)
        games, lev = [], 0.0
        for g in range(len(wh)):
            hcode, acode = TEAMS[wh[g]], TEAMS[wa[g]]
            for team, opp, home, p_win in ((hcode, acode, True, float(p_home[g])),
                                           (acode, hcode, False, float(1 - p_home[g]))):
                if team not in mine:
                    continue
                games.append({"team": team, "opp": opp, "home": home, "p": round(p_win, 3)})
                forced = week_outcomes.copy()
                forced[:, g] = home            # my team wins
                win_tot = _player_totals(rosters, totals_for(forced))
                forced[:, g] = not home        # my team loses
                loss_tot = _player_totals(rosters, totals_for(forced))
                lev += abs(pool_pwin(win_tot)[p] - pool_pwin(loss_tot)[p])
        tw_rows.append({"player": p, "leverage": round(lev, 3), "games": games})
    tw_rows.sort(key=lambda r: r["leverage"], reverse=True)

    return {"week": week, "computed_at": float(now if now is not None else time.time()),
            "ratings_fetched_at": ratings_fetched_at,
            "rows": rows, "x": xs, "n_sims": int(n_seasons), "this_week": tw_rows}


_LAST_SCHEDULE: pd.DataFrame | None = None


def _load_schedule_cached() -> pd.DataFrame:
    """Live schedule from nfl_data_py; on failure, the last frame that worked.
    Raises if there has never been a good fetch in this process."""
    global _LAST_SCHEDULE
    from . import standings
    try:
        df = standings._load_schedule()
        _LAST_SCHEDULE = df
        return df
    except Exception:
        if _LAST_SCHEDULE is None:
            raise
        return _LAST_SCHEDULE


def ratings_fetched_at(cache_dir) -> str | None:
    """Newest fetched_at among ok sources in sources_meta.json, or None."""
    path = os.path.join(cache_dir, "sources_meta.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        meta = json.load(f)
    stamps = [m["fetched_at"] for m in meta if m.get("ok") and m.get("fetched_at")]
    return max(stamps) if stamps else None


def refresh_live(store, cache_dir, *, n_seasons=5000) -> dict:
    """Recompute the live doc from the league's final rosters and the current
    schedule + ratings cache; store it; snapshot the week if not yet snapshotted."""
    from . import league as _league
    rosters = _league.view(store.get())["rosters"]
    df = _load_schedule_cached()
    doc = compute_live(
        rosters, df,
        totals_path=os.path.join(cache_dir, "win_totals.csv"),
        power_path=os.path.join(cache_dir, "power_ratings.csv"),
        kalshi_dist_path=os.path.join(cache_dir, "kalshi_distributions.csv"),
        ratings_fetched_at=ratings_fetched_at(cache_dir),
        n_seasons=n_seasons)
    store.put_live(doc)
    if not any(w["week"] == doc["week"] for w in store.list_weeks()):
        store.put_week(doc["week"], doc)
    return doc
