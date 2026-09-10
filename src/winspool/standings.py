"""Regular-season wins per team from nfl_data_py, refreshed via a store
cache document (see store.get_standings/put_standings) rather than an
in-process TTL — a scheduler calls refresh_standings() once and every reader
reads the stored result."""
import time

import pandas as pd

from .teams import TEAMS


def _load_schedule() -> pd.DataFrame:
    import nfl_data_py as nfl
    return nfl.import_schedules([2026])


def wins_from_schedule(df: pd.DataFrame) -> dict[str, int]:
    wins = {t: 0 for t in TEAMS}
    reg = df[(df["game_type"] == "REG") & df["home_score"].notna() & df["away_score"].notna()]
    for r in reg.itertuples(index=False):
        if r.home_score > r.away_score:
            wins[r.home_team] = wins.get(r.home_team, 0) + 1
        elif r.away_score > r.home_score:
            wins[r.away_team] = wins.get(r.away_team, 0) + 1
    return wins


def refresh_standings(store) -> dict:
    """Fetch the live schedule and write a fresh standings doc to the store.

    On success: {wins, fetched_at=now, ok=True, error=None}.
    On failure: keeps the previous wins/fetched_at (if any) but flips
    ok=False and records the error; with no previous doc, writes zeros.
    """
    prev = store.get_standings()
    try:
        wins = wins_from_schedule(_load_schedule())
        doc = {"wins": wins, "fetched_at": time.time(), "ok": True, "error": None}
    except Exception as e:
        if prev is not None:
            doc = {**prev, "ok": False, "error": str(e)[:200]}
        else:
            doc = {"wins": {t: 0 for t in TEAMS}, "fetched_at": time.time(),
                   "ok": False, "error": str(e)[:200]}
    store.put_standings(doc)
    return doc


def apply_overrides(wins: dict[str, int], overrides: dict[str, int]) -> dict[str, int]:
    out = dict(wins)
    for team, w in (overrides or {}).items():
        out[team] = int(w)
    return out
