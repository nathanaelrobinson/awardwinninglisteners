import pandas as pd
import pytest

from winspool.gameodds import GameOdds
from winspool.oddslog import refresh_odds, snapshot
from winspool.store import InMemoryStore

SCHED = pd.DataFrame([
    {"week": 1, "game_type": "REG", "home_team": "KC", "away_team": "DEN",
     "spread_line": 2.5, "total_line": 43.5, "home_score": None, "away_score": None},
    {"week": 1, "game_type": "REG", "home_team": "LA", "away_team": "SF",
     "spread_line": 3.5, "total_line": 48.5, "home_score": None, "away_score": None},
])


def _book(**kw):
    return [GameOdds(source="book", home="KC", away="DEN", fetched_at=5.0,
                     ml_home=-148, ml_away=124, **kw)]


def test_snapshot_is_raw_and_carries_its_coordinates():
    doc = snapshot("book", 2026, 1, _book())
    assert doc["season"] == 2026 and doc["week"] == 1 and doc["source"] == "book"
    assert doc["fetched_at"] == 5.0
    assert doc["games"] == [{"home": "KC", "away": "DEN", "spread": None,
                             "total": None, "ml_home": -148, "ml_away": 124,
                             "yes_home": None, "yes_away": None, "p_home": None}]


def test_snapshot_of_nothing_still_records_the_attempt():
    doc = snapshot("book", 2026, 1, [], now=9.0)
    assert doc["games"] == [] and doc["fetched_at"] == 9.0


def test_refresh_writes_one_snapshot_per_source():
    store = InMemoryStore({})
    out = refresh_odds(store, SCHED, 2026, sources={
        "book": lambda season, week, pairs: _book(),
        "kalshi": lambda season, week, pairs: [],
    }, now=5.0)
    assert out["week"] == 1
    assert out["written"] == {"book": 1, "kalshi": 0, "nflverse": 2}
    assert {r["source"] for r in store.odds_for_week(2026, 1)} == {
        "book", "kalshi", "nflverse"}


def test_one_source_failing_does_not_cost_us_the_others():
    def boom(season, week, pairs):
        raise RuntimeError("espn is down")

    store = InMemoryStore({})
    out = refresh_odds(store, SCHED, 2026,
                       sources={"book": boom,
                                "kalshi": lambda s, w, p: []}, now=5.0)
    assert "espn is down" in out["errors"]["book"]
    assert "kalshi" in out["written"] and "nflverse" in out["written"]
    assert "book" not in out["written"]


def test_refresh_targets_the_first_week_with_an_unplayed_game():
    played = SCHED.copy()
    played.loc[:, "home_score"] = [24, None]
    played.loc[:, "away_score"] = [17, None]
    store = InMemoryStore({})
    out = refresh_odds(store, played, 2026, sources={}, now=5.0)
    assert out["week"] == 1


def test_every_refresh_appends_rather_than_replacing():
    store = InMemoryStore({})
    for ts in (5.0, 6.0):
        refresh_odds(store, SCHED, 2026,
                     sources={"book": lambda s, w, p: _book()}, now=ts)
    rows = [r for r in store.odds_for_week(2026, 1) if r["source"] == "book"]
    assert len(rows) == 2


FINISHED = pd.DataFrame([
    {"week": 1, "game_type": "REG", "home_team": "KC", "away_team": "DEN",
     "spread_line": 2.5, "total_line": 43.5, "home_score": 24, "away_score": 17,
     "gameday": "2026-09-14", "gametime": "20:15"},
])


def _at(ts, spread):
    return {"season": 2026, "week": 1, "source": "book", "fetched_at": ts,
            "games": [{"home": "KC", "away": "DEN", "spread": spread, "total": 43.5,
                       "ml_home": -148, "ml_away": 124, "yes_home": None,
                       "yes_away": None, "p_home": None}]}


def test_thinning_keeps_the_opening_and_the_last_read_before_kickoff():
    from winspool.oddslog import thin_week
    store = InMemoryStore({})
    # kickoff is 2026-09-14T20:15 local; these are ordered, not absolute
    for ts, spread in [(100.0, -1.5), (200.0, -2.0), (300.0, -2.5)]:
        store.add_odds(_at(ts, spread))
    removed = thin_week(store, FINISHED, 2026, 1)
    kept = store.odds_for_week(2026, 1)
    assert removed == 1
    assert [r["fetched_at"] for r in kept] == [100.0, 300.0]


def test_thinning_a_week_that_is_still_being_played_removes_nothing():
    from winspool.oddslog import thin_week
    store = InMemoryStore({})
    store.add_odds(_at(100.0, -1.5))
    store.add_odds(_at(200.0, -2.0))
    unplayed = FINISHED.copy()
    unplayed["home_score"] = [None]
    unplayed["away_score"] = [None]
    assert thin_week(store, unplayed, 2026, 1) == 0
    assert len(store.odds_for_week(2026, 1)) == 2


def test_thinning_is_idempotent():
    from winspool.oddslog import thin_week
    store = InMemoryStore({})
    for ts, spread in [(100.0, -1.5), (200.0, -2.0), (300.0, -2.5)]:
        store.add_odds(_at(ts, spread))
    thin_week(store, FINISHED, 2026, 1)
    assert thin_week(store, FINISHED, 2026, 1) == 0


def test_thinning_keeps_every_source_separately():
    from winspool.oddslog import thin_week
    store = InMemoryStore({})
    for ts in (100.0, 200.0, 300.0):
        store.add_odds(_at(ts, -2.0))
        store.add_odds({**_at(ts, -2.0), "source": "kalshi"})
    thin_week(store, FINISHED, 2026, 1)
    kept = store.odds_for_week(2026, 1)
    assert sorted(r["source"] for r in kept) == ["book", "book", "kalshi", "kalshi"]
