"""Per-game home-win probabilities for every remaining game, now or as of a past time.

The strategy feed (tradebot) consumes these over the token-guarded
`/internal/game-probs*` routes. `p_home` is the live model's own number for a
game: the Kalman posterior mean over the BMA-weighted voices, pushed through the
same probit `compute_live` uses for `p_model`. It is never the market override
(`p_used`) — a consumer that trades against the market needs the model's view,
not the market quoted back to it. The market consensus is reported beside it as
`p_market`.

History works because the `ratings` and `odds` tables are append-only with
`fetched_at`: an `AsOfStore` hides every row fetched after `as_of`, and the
schedule hides every result that was not yet known (results carry no timestamp,
so a result counts as known at kickoff + RESULT_LAG_S).
"""
import math
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import live as _live
from .game import win_prob
from .ratings import to_common_scale
from .teams import TEAM_NAMES, TEAMS, resolve
from .week import _kickoff

RESULT_LAG_S = 4 * 3600          # a result is "known" kickoff + 4 h
_REPO_ROOT = Path(__file__).resolve().parents[2]


class NoRatings(RuntimeError):
    """No rating rows (as of the requested time) to build the model from."""


def _now() -> float:
    return time.time()


def iso_utc(ts: float | datetime | None) -> str | None:
    if ts is None:
        return None
    dt = ts if isinstance(ts, datetime) else datetime.fromtimestamp(float(ts), tz=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_as_of(text: str) -> float:
    """ISO-8601 -> epoch seconds. A trailing Z is UTC; no offset is UTC."""
    s = text.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


class AsOfStore:
    """Read-only view of a store as it stood at `as_of`: rating and odds rows
    fetched later are invisible. Only the reads the model makes are provided."""

    def __init__(self, store, as_of: float):
        self._store = store
        self.as_of = float(as_of)

    def latest_ratings(self) -> dict[str, dict]:
        # all_ratings is ordered (fetched_at, insertion), so the last row seen
        # per source is the one latest_ratings would have picked at the time.
        best: dict[str, dict] = {}
        for r in self._store.all_ratings():
            if r["ok"] and float(r["fetched_at"]) <= self.as_of:
                best[r["source"]] = r
        return best

    def odds_for_week(self, season: int, week: int) -> list[dict]:
        return [r for r in self._store.odds_for_week(season, week)
                if float(r.get("fetched_at") or 0.0) <= self.as_of]

    def latest_odds(self, season: int, week: int) -> list[dict]:
        best: dict[str, dict] = {}
        for r in self.odds_for_week(season, week):
            best[r["source"]] = r
        return list(best.values())


def kickoff_utc(row) -> datetime | None:
    """Kickoff as an aware UTC datetime, or None when the schedule has no clock."""
    s = _kickoff(row)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:          # date only: no usable kickoff time
        return None
    return dt.astimezone(timezone.utc)


def schedule_as_of(sched_df: pd.DataFrame, as_of: float) -> pd.DataFrame:
    """The schedule with every result not yet known at `as_of` blanked out.

    A result is known from kickoff + RESULT_LAG_S. A scored game with no
    kickoff time cannot be placed in time, so it is kept as played."""
    df = sched_df.copy()
    cutoff = datetime.fromtimestamp(float(as_of), tz=timezone.utc)
    hide = []
    for i, row in zip(df.index, df.itertuples(index=False)):
        ko = kickoff_utc(row)
        if ko is not None and ko + timedelta(seconds=RESULT_LAG_S) > cutoff:
            hide.append(i)
    if hide:
        df["home_score"] = df["home_score"].astype(float)
        df["away_score"] = df["away_score"].astype(float)
        df.loc[hide, ["home_score", "away_score"]] = np.nan
    return df


def game_id(season: int, week: int, home: str, away: str) -> str:
    return f"{int(season)}-{int(week)}-{away}@{home}"


_MODEL_CACHE: dict = {}
_MODEL_CACHE_MAX = 64


def _model(store, played: pd.DataFrame, remaining: pd.DataFrame):
    """(names, matrix, weights, posterior mean, ratings stamp) — the same
    construction `live.compute_live` scores remaining games with, minus the
    Kalshi sigma calibration (it only feeds the season sim, not a game's p)."""
    from .recommend import _assemble_sources
    latest = store.latest_ratings()
    if not latest:
        raise NoRatings("no ratings rows")
    stamp = max(float(r["fetched_at"]) for r in latest.values())
    banked = _live.banked_wins(played)
    ph, pa, pw = _live.played_outcomes(played)
    rh, ra = _live.remaining_matchups(remaining)
    key = (tuple(sorted((s, str(r.get("id"))) for s, r in latest.items())),
           tuple(int(x) for x in rh), tuple(int(x) for x in ra),
           tuple(int(x) for x in ph), tuple(int(x) for x in pa),
           tuple(bool(x) for x in pw), tuple(float(x) for x in banked))
    hit = _MODEL_CACHE.get(key)
    if hit is not None:
        return hit
    sources, _ = _assemble_sources(None, None, rh, ra, None, store=store, banked=banked)
    if not sources:
        raise NoRatings("no usable rating sources")
    names = list(sources)
    matrix = to_common_scale(sources)
    weights = _live.bma_weights(matrix, _live.prior_weights(names), ph, pa, pw)
    post_mean, _sd = _live.posterior_strength(matrix, weights, ph, pa, pw)
    out = (names, matrix, weights, post_mean, stamp)
    if len(_MODEL_CACHE) >= _MODEL_CACHE_MAX:
        _MODEL_CACHE.pop(next(iter(_MODEL_CACHE)))
    _MODEL_CACHE[key] = out
    return out


_GIT_SHA: list = []


def git_sha() -> str | None:
    """Short sha of the running checkout (WINSPOOL_GIT_SHA overrides), cached."""
    if not _GIT_SHA:
        sha = os.environ.get("WINSPOOL_GIT_SHA")
        if not sha:
            try:
                sha = subprocess.run(
                    ["git", "-C", str(_REPO_ROOT), "rev-parse", "--short", "HEAD"],
                    capture_output=True, text=True, timeout=5, check=True).stdout.strip()
            except Exception:          # noqa: BLE001 - no checkout: version from ratings only
                sha = None
        _GIT_SHA.append(sha or None)
    return _GIT_SHA[0]


def model_version(stamp: float | None) -> str:
    """`<git short sha>@<ratings stamp, epoch s>`; either half alone when the
    other is unknown. Changes when the code or the ratings the model read do."""
    sha = git_sha()
    r = None if stamp is None else str(int(stamp))
    if sha and r:
        return f"{sha}@{r}"
    return sha or (f"ratings@{r}" if r else "unknown")


def teams_list() -> list[dict]:
    return [{"code": c, "name": TEAM_NAMES[c]} for c in TEAMS]


def _market_by_game(store, season: int, weeks) -> dict:
    out = {}
    for w in sorted(set(int(x) for x in weeks)):
        try:
            out.update(_live.market_probs(store.latest_odds(season, w)))
        except Exception:              # noqa: BLE001 - the market is optional here
            continue
    return out


def game_probs(store, sched_df: pd.DataFrame, *, season: int, as_of: float | None = None) -> dict:
    """The /internal/game-probs document.

    `as_of=None` is the live view (every stored row, every result in the
    schedule). With `as_of`, only rows fetched at or before it and results
    known by then are used, so the same `as_of` always gives the same answer."""
    if as_of is None:
        stamp_at = _now()
        view, sched = store, sched_df
    else:
        stamp_at = float(as_of)
        view, sched = AsOfStore(store, stamp_at), schedule_as_of(sched_df, stamp_at)
    played, remaining = _live.split_schedule(sched)
    base = {"as_of": iso_utc(stamp_at), "season": int(season), "teams": teams_list()}
    if remaining.empty:
        latest = view.latest_ratings()
        stamp = max((float(r["fetched_at"]) for r in latest.values()), default=None)
        return {**base, "model_version": model_version(stamp),
                "ratings_fetched_at": iso_utc(stamp), "weights": {}, "games": []}
    names, matrix, weights, post_mean, stamp = _model(view, played, remaining)
    rh, ra = _live.remaining_matchups(remaining)
    p_model = np.asarray(win_prob(post_mean[rh], post_mean[ra]), dtype=float)
    p_voice = [np.asarray(win_prob(matrix[j, rh], matrix[j, ra]), dtype=float)
               for j in range(len(names))]
    market = _market_by_game(view, season, remaining["week"])

    games = []
    for g, row in enumerate(remaining.itertuples(index=False)):
        home, away = resolve(row.home_team), resolve(row.away_team)
        ko = kickoff_utc(row)
        mp = market.get((home, away))
        games.append({
            "game_id": game_id(season, row.week, home, away),
            "week": int(row.week),
            "kickoff_utc": iso_utc(ko),
            "home": home, "away": away,
            "p_home": round(float(p_model[g]), 4),
            "sources": {n: round(float(p_voice[j][g]), 4) for j, n in enumerate(names)},
            "p_market": None if mp is None else round(float(mp), 4),
        })
    games.sort(key=lambda x: (x["week"], x["kickoff_utc"] or "", x["game_id"]))
    return {**base, "model_version": model_version(stamp),
            "ratings_fetched_at": iso_utc(stamp),
            "weights": {n: round(float(w), 6) for n, w in zip(names, weights)},
            "games": games}


def _score(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else int(f)


def games(sched_df: pd.DataFrame, *, season: int) -> dict:
    """Every regular-season game with its result, from the schedule frame (the
    same frame `standings.wins_from_schedule` counts wins from)."""
    reg = _live._reg(sched_df)
    out = []
    for row in reg.itertuples(index=False):
        home, away = resolve(row.home_team), resolve(row.away_team)
        hs, as_ = _score(row.home_score), _score(row.away_score)
        out.append({
            "game_id": game_id(season, row.week, home, away),
            "week": int(row.week),
            "kickoff_utc": iso_utc(kickoff_utc(row)),
            "home": home, "away": away,
            "home_score": hs, "away_score": as_,
            "played": hs is not None and as_ is not None,
        })
    out.sort(key=lambda x: (x["week"], x["kickoff_utc"] or "", x["game_id"]))
    return {"season": int(season), "games": out}

