"""The odds snapshot log: what every source said, hourly, before kickoff.

None of these sources are archived anywhere. Nobody publishes what DraftKings
hung in week 3 once week 4 is up, and the same is true of Kalshi's book. A read
not taken before kickoff is gone. That is the whole reason this module exists
before anything consumes it.
"""
import time

from .fetch.odds import fetch_espn, fetch_kalshi, from_schedule, week_pairs
from .gameodds import GameOdds
from .live import week_of


def snapshot(source: str, season: int, week: int, odds: list[GameOdds],
             now: float | None = None) -> dict:
    """One source's full read of one week. Raw values only."""
    stamp = now if now is not None else (odds[0].fetched_at if odds else time.time())
    return {"season": int(season), "week": int(week), "source": source,
            "fetched_at": float(stamp),
            "games": [o.as_dict() for o in odds]}


def default_sources() -> dict:
    """Live sources, keyed by the name they are logged under. Each takes
    (season, week, pairs) so a caller can stub one out in a test."""
    return {
        "book": lambda season, week, pairs: fetch_espn(season, week),
        "kalshi": lambda season, week, pairs: fetch_kalshi(pairs),
    }


def refresh_odds(store, sched_df, season: int, *, sources=None,
                 now: float | None = None) -> dict:
    """Fetch every source for the current week and append one snapshot each.

    A source that fails is recorded and skipped; the others still write. One
    source being down must never cost us the other two — which is most of the
    argument for having three."""
    week = week_of(sched_df)
    pairs = week_pairs(sched_df, week)
    stamp = now if now is not None else time.time()
    written, errors = {}, {}

    baseline = from_schedule(sched_df, week, stamp)
    store.add_odds(snapshot("nflverse", season, week, baseline, now=stamp))
    written["nflverse"] = len(baseline)

    for name, fn in (default_sources() if sources is None else sources).items():
        try:
            odds = fn(season, week, pairs)
        except Exception as e:                    # noqa: BLE001 - logged, not raised
            errors[name] = str(e)[:200]
            continue
        store.add_odds(snapshot(name, season, week, odds, now=stamp))
        written[name] = len(odds)

    return {"season": int(season), "week": int(week), "written": written,
            "errors": errors}
