import pytest

from winspool.store import InMemoryStore, SqliteStore


def _snap(source, fetched_at, season=2026, week=1, spread=-2.5):
    return {"season": season, "week": week, "source": source,
            "fetched_at": fetched_at,
            "games": [{"home": "KC", "away": "DEN", "spread": spread,
                       "total": 43.5, "ml_home": -148, "ml_away": 124,
                       "yes_home": None, "yes_away": None, "p_home": None}]}


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryStore({})
    return SqliteStore(tmp_path / "t.db")


def test_add_and_read_back_a_week(store):
    rid = store.add_odds(_snap("book", 100.0))
    store.add_odds(_snap("kalshi", 101.0))
    rows = store.odds_for_week(2026, 1)
    assert [r["source"] for r in rows] == ["book", "kalshi"]
    assert rows[0]["games"][0]["ml_home"] == -148
    # add_odds hands back the id it stamped on the row
    assert rows[0]["id"] == rid


def test_rows_come_back_oldest_first(store):
    for ts in (300.0, 100.0, 200.0):
        store.add_odds(_snap("book", ts))
    assert [r["fetched_at"] for r in store.odds_for_week(2026, 1)] == [100.0, 200.0, 300.0]


def test_other_weeks_and_seasons_are_not_returned(store):
    store.add_odds(_snap("book", 100.0, week=1))
    store.add_odds(_snap("book", 100.0, week=2))
    store.add_odds(_snap("book", 100.0, season=2025, week=1))
    assert len(store.odds_for_week(2026, 1)) == 1


def test_latest_odds_is_the_newest_row_per_source(store):
    first = store.add_odds(_snap("book", 100.0, spread=-2.5))
    store.add_odds(_snap("book", 200.0, spread=-3.5))
    store.add_odds(_snap("kalshi", 150.0))
    latest = {r["source"]: r for r in store.latest_odds(2026, 1)}
    assert set(latest) == {"book", "kalshi"}
    assert latest["book"]["games"][0]["spread"] == -3.5

    # the superseded read is still there, untouched: the log only ever appends
    rows = store.odds_for_week(2026, 1)
    assert len(rows) == 3
    assert next(r for r in rows if r["id"] == first)["games"][0]["spread"] == -2.5


def test_put_odds_preserves_the_id_for_import(store):
    store.put_odds({**_snap("book", 100.0), "id": "fixed-id"})
    assert store.odds_for_week(2026, 1)[0]["id"] == "fixed-id"


def test_all_odds_spans_every_week(store):
    store.add_odds(_snap("book", 100.0, week=1))
    store.add_odds(_snap("book", 200.0, week=2))
    assert len(store.all_odds()) == 2
