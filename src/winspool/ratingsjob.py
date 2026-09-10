"""Fetch every live rating source and append what it said.

A source that fails leaves its last good row in place rather than dropping out
of the ensemble — the old CSV pipeline wrote one column per source that
succeeded, so a dead scraper silently changed what the model was. Per-source
rows remove that class of bug. Staleness is surfaced instead, and makes the
health check fail rather than the model quietly age.
"""
import time

DAY = 86400.0

# A source past this age has not merely blipped — something is wrong and the
# ensemble is drifting on stale information. These make the endpoint 503.
MAX_AGE_S = {
    "espn_fpi": 10 * DAY,        # weekly
    "kalshi": 2 * DAY,           # daily
    "covers": 2 * DAY,           # daily
    "epa_adj": 10 * DAY,         # weekly
    "market_strength": 10 * DAY,  # weekly
}

KIND = {"espn_fpi": "power", "kalshi": "distribution", "covers": "totals",
        "epa_adj": "power", "market_strength": "power"}


def default_sources(store) -> dict:
    """{name: (kind, fn(season, week) -> {team: value})}. Kept as a function so
    a caller — or a test — can substitute one without touching the others."""
    from .fetch.scrapers import covers_totals, epa_ratings, espn_fpi
    from .fetch.kalshi import kalshi_distributions
    from .marketstrength import closing_spreads, strength_from_spreads

    def _market(season, week):
        games = closing_spreads(store, season, range(1, max(1, week)))
        return strength_from_spreads(games, current_week=week)

    return {
        "espn_fpi": ("power", lambda s, w: espn_fpi()),
        "covers": ("totals", lambda s, w: covers_totals()),
        "kalshi": ("distribution", lambda s, w: kalshi_distributions()),
        "epa_adj": ("power", lambda s, w: epa_ratings()),
        "market_strength": ("power", _market),
    }


def refresh_ratings(store, *, season: int, week: int, sources=None,
                    now: float | None = None) -> dict:
    stamp = now if now is not None else time.time()
    src = default_sources(store) if sources is None else sources
    written, errors = {}, {}
    for name, (kind, fn) in src.items():
        try:
            doc = fn(season, week)
        except Exception as e:                    # noqa: BLE001 - recorded, not raised
            errors[name] = f"{type(e).__name__}: {e}"[:200]
            store.add_rating({"source": name, "kind": kind, "fetched_at": stamp,
                              "ok": False, "doc": {"error": errors[name]}})
            continue
        if not doc:
            errors[name] = "empty result"
            store.add_rating({"source": name, "kind": kind, "fetched_at": stamp,
                              "ok": False, "doc": {"error": "empty result"}})
            continue
        store.add_rating({"source": name, "kind": kind, "fetched_at": stamp,
                          "ok": True, "doc": doc})
        written[name] = len(doc)
    return {"season": int(season), "week": int(week),
            "written": written, "errors": errors}


def stale(store, now: float | None = None) -> dict:
    """{source: age_seconds} for every source whose last SUCCESS is past its
    limit. A source that has never succeeded counts as infinitely stale."""
    stamp = now if now is not None else time.time()
    latest = store.latest_ratings()
    out = {}
    for name, limit in MAX_AGE_S.items():
        row = latest.get(name)
        age = float("inf") if row is None else stamp - float(row["fetched_at"])
        if age > limit:
            out[name] = age
    return out
