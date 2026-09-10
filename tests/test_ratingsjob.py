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
