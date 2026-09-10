import sys

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

def _valid_pmf(pmf):
    """A usable win PMF, or None. A malformed row otherwise surfaces late and
    namelessly, inside `rng.choice` during a refresh."""
    from .fetch.kalshi import MAX_WINS
    try:
        arr = np.asarray(pmf, dtype=float)
    except (TypeError, ValueError):
        return None
    if arr.ndim != 1 or arr.size != MAX_WINS + 1:
        return None
    if not np.all(np.isfinite(arr)) or float(arr.sum()) <= 0.0:
        return None
    return arr


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
        # `__meta__` and friends are bookkeeping a source attached to its doc
        # (epa_adj records n_plays and its shrink weight); only team keys are data.
        doc = {k: v for k, v in row["doc"].items() if not str(k).startswith("__")}
        kind = row["kind"]
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
            bad = []
            for code, pmf in doc.items():
                if code not in TEAM_INDEX:
                    continue
                row_pmf = _valid_pmf(pmf)
                if row_pmf is None:
                    # Per TEAM, not per source: one ragged ladder drops that
                    # team (its line falls back to the mean below, its
                    # target_sd stays NaN) rather than silencing a live market
                    # voice for all 32. Losing the voice is the worse outcome.
                    bad.append(code)
                    continue
                line[TEAM_INDEX[code]] = pmf_line(row_pmf)
                target_sd[TEAM_INDEX[code]] = pmf_sd(row_pmf)
            if bad:
                print(f"  WARNING: {name}: skipping malformed win distribution "
                      f"for {', '.join(sorted(bad))}", file=sys.stderr)
            line[np.isnan(line)] = np.nanmean(line)
            sources[name] = ("__totals__", line)
    return sources, target_sd
