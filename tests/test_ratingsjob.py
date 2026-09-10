from winspool.ratingsjob import MAX_AGE_S, refresh_ratings, stale
from winspool.store import InMemoryStore


def test_a_failing_source_is_recorded_without_masking_the_last_good_one():
    store = InMemoryStore({})

    def ok(season, week):
        return {"KC": 5.0, "BUF": 2.0}

    def boom(season, week):
        raise RuntimeError("espn is down")

    out = refresh_ratings(store, season=2026, week=3,
                          sources={"espn_fpi": ("power", ok)}, now=100.0)
    assert out["written"] == {"espn_fpi": 2} and out["errors"] == {}

    out = refresh_ratings(store, season=2026, week=4,
                          sources={"espn_fpi": ("power", boom)}, now=200.0)
    assert "espn is down" in out["errors"]["espn_fpi"]
    assert out["written"] == {}

    # the good row still stands, and the failure is visible in history
    latest = store.latest_ratings()
    assert latest["espn_fpi"]["doc"]["KC"] == 5.0
    assert [r["ok"] for r in store.ratings_history("espn_fpi")] == [True, False]

    # ...and the source is now stale, because its last SUCCESS is old
    aged = stale(store, now=100.0 + MAX_AGE_S["espn_fpi"] + 1)
    assert "espn_fpi" in aged


def test_market_strength_is_available_in_week_one():
    """`_market` reads range(1, week + 1). It used to read range(1, max(1, week)),
    which is empty at week 1: the source failed on every week-1 run and the
    health endpoint 503'd from the day it deployed. A health check that is red
    for a known non-problem is a health check everyone learns to ignore, so
    guard the cold start explicitly -- week 1, week-1 odds, a real answer."""
    from winspool.gameodds import GameOdds
    from winspool.oddslog import snapshot
    from winspool.ratingsjob import default_sources

    store = InMemoryStore({})
    store.add_odds(snapshot("book", 2026, 1, [
        GameOdds(source="book", home="KC", away="BUF", fetched_at=10.0, spread=-3.0),
        GameOdds(source="book", home="DEN", away="SEA", fetched_at=10.0, spread=1.0),
    ], now=10.0))

    doc = default_sources(store)["market_strength"][1](2026, 1)
    assert set(doc) == {"KC", "BUF", "DEN", "SEA"}
    assert doc["KC"] > doc["BUF"], "the home favourite is the stronger team"
