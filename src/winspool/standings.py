"""Regular-season wins per team from nfl_data_py, cached one hour."""
import time

import pandas as pd

from .teams import TEAMS

TTL = 3600
_CACHE: dict = {}   # {"wins": dict, "ts": float}


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


def fetch_wins(refresh: bool = False) -> tuple[dict[str, int], bool]:
    now = time.time()
    if not refresh and _CACHE and now - _CACHE["ts"] < TTL:
        return _CACHE["wins"], False
    try:
        wins = wins_from_schedule(_load_schedule())
    except Exception:
        if _CACHE:
            return _CACHE["wins"], True
        return {t: 0 for t in TEAMS}, True
    _CACHE.update(wins=wins, ts=now)
    return wins, False


def apply_overrides(wins: dict[str, int], overrides: dict[str, int]) -> dict[str, int]:
    out = dict(wins)
    for team, w in (overrides or {}).items():
        out[team] = int(w)
    return out
