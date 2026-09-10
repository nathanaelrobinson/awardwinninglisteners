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

def sources_from_store(store):
    """({name: strength}, target_sd) from the newest good row per source.

    The file path and this path must produce identical strengths — see
    tests/test_ratings_equivalence.py, which is what makes the migration safe.
    Totals and distributions come back as a ("__totals__", arr) marker because
    backing them out to strengths needs the schedule, which only the caller has.
    """
    latest = store.latest_ratings()
    sources, target_sd = {}, np.full(N_TEAMS, np.nan)
    for name, row in latest.items():
        doc, kind = row["doc"], row["kind"]
        if kind == "power":
            arr = np.zeros(N_TEAMS)
            for code, val in doc.items():
                if code in TEAM_INDEX:
                    arr[TEAM_INDEX[code]] = float(val)
            sources[name] = arr
        elif kind == "totals":
            totals = np.full(N_TEAMS, np.nan)
            for code, val in doc.items():
                if code in TEAM_INDEX:
                    totals[TEAM_INDEX[code]] = float(val)
            # teams with no posted number default to the mean of those posted,
            # exactly as load_win_totals does
            totals[np.isnan(totals)] = np.nanmean(totals)
            sources[name] = ("__totals__", totals)
        elif kind == "distribution":
            from .fetch.kalshi import pmf_line, pmf_sd
            line = np.full(N_TEAMS, np.nan)
            for code, pmf in doc.items():
                if code in TEAM_INDEX:
                    row_pmf = np.asarray(pmf, dtype=float)
                    line[TEAM_INDEX[code]] = pmf_line(row_pmf)
                    target_sd[TEAM_INDEX[code]] = pmf_sd(row_pmf)
            line[np.isnan(line)] = np.nanmean(line)
            sources[name] = ("__totals__", line)
    return sources, target_sd
