import numpy as np
import pandas as pd
from .teams import TEAM_INDEX, N_TEAMS

def load_schedule(path):
    df = pd.read_csv(path)
    df = df[df["game_type"].str.upper() == "REG"].reset_index(drop=True)
    return df[["home_team", "away_team"]]

def schedule_matchups(df):
    home = df["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    away = df["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    return home, away

def load_win_totals(path):
    df = pd.read_csv(path)
    totals = np.full(N_TEAMS, np.nan)
    for _, row in df.iterrows():
        totals[TEAM_INDEX[row["team"]]] = float(row["win_total"])
    # teams with no posted number default to the mean of those posted
    totals[np.isnan(totals)] = np.nanmean(totals)
    return totals

def load_power_ratings(path):
    """Return every numeric source column, indexed by team code.
    Any number of source columns is supported (fpi, sagarin, massey, elo_*, ...);
    the blend averages whatever is present."""
    df = pd.read_csv(path).set_index("team")
    return df.select_dtypes("number")
