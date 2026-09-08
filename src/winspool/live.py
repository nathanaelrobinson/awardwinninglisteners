"""In-season live projection: banked wins plus a remaining-season Monte Carlo.

Pure functions over the nfl_data_py schedule frame (columns week, game_type,
home_team, away_team, home_score, away_score) and the data/cache ratings files.
No store or network access except in refresh_live()."""
import os

import numpy as np
import pandas as pd

from .data import load_power_ratings, load_win_totals
from .game import HFA, SCALE
from .ratings import backout_market, to_common_scale
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
