import pytest

from winspool.ratingsjob import (MIN_TEAM_COVERAGE, MAX_AGE_S, refresh_ratings,
                                 stale)
from winspool.store import InMemoryStore
from winspool.teams import TEAMS


def _full(value=1.0):
    """A doc covering all 32 teams — anything less is now refused at write time."""
    return {t: float(i) + value for i, t in enumerate(TEAMS)}


def test_a_failing_source_is_recorded_without_masking_the_last_good_one():
    store = InMemoryStore({})

    def ok(season, week):
        return {**_full(), "KC": 5.0}

    def boom(season, week):
        raise RuntimeError("espn is down")

    out = refresh_ratings(store, season=2026, week=3,
                          sources={"espn_fpi": ("power", ok)}, now=100.0)
    assert out["written"] == {"espn_fpi": len(TEAMS)} and out["errors"] == {}

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
    """Week 1 is a remaining slate (weeks 1..18). Posted week-1 lines must
    still produce a real answer -- the source used to fail on a cold start
    and keep the health check red for a known non-problem."""
    from winspool.gameodds import GameOdds
    from winspool.oddslog import snapshot
    from winspool.ratingsjob import default_sources

    store = InMemoryStore({})
    week1 = [
        GameOdds(source="book", home="KC", away="BUF", fetched_at=10.0, spread=-3.0),
        GameOdds(source="book", home="DEN", away="SEA", fetched_at=10.0, spread=1.0),
    ]
    store.add_odds(snapshot("book", 2026, 1, week1, now=10.0))

    def fetch_week(season, week):
        return week1

    doc = default_sources(store, fetch_week=fetch_week)["market_strength"][1](2026, 1)
    assert set(doc) == {"KC", "BUF", "DEN", "SEA"}
    assert doc["KC"] > doc["BUF"], "the home favourite is the stronger team"


def test_remaining_slate_recovers_a_large_favorite_closer_than_week1_ridge():
    """Week-1 closes alone are 16 disjoint pairs; sparsity_ridge hands a
    7-point favourite ~1.75. Baldwin GPF is the remaining slate. Feeding
    weeks current..18 must recover that favourite closer to the raw spread.
    """
    from winspool.game import HFA
    from winspool.gameodds import GameOdds
    from winspool.marketstrength import closing_spreads, strength_from_spreads
    from winspool.oddslog import snapshot
    from winspool.ratingsjob import default_sources

    store = InMemoryStore({})
    # Week 1: the under-determined shape the ridge exists to damp.
    week1 = []
    for i in range(16):
        home, away = TEAMS[2 * i], TEAMS[2 * i + 1]
        week1.append(GameOdds(source="book", home=home, away=away,
                              fetched_at=1.0, spread=-7.0))
    store.add_odds(snapshot("book", 2026, 1, week1, now=1.0))
    week1_solve = strength_from_spreads(
        closing_spreads(store, 2026, range(1, 2)), current_week=1)
    favourite = TEAMS[0]

    # Remaining weeks: posted from a 7-point favourite vs the field. That
    # identifies the graph; week-1 ridge cannot.
    true = {t: (-7.0 / 31.0) for t in TEAMS}
    true[favourite] = 7.0
    mu = sum(true.values()) / len(true)
    true = {t: v - mu for t, v in true.items()}
    for week in range(2, 19):
        order = TEAMS[week % 2:] + TEAMS[:week % 2]
        games = []
        for i in range(0, len(TEAMS), 2):
            home, away = order[i], order[i + 1]
            games.append(GameOdds(
                source="book", home=home, away=away, fetched_at=float(week),
                spread=true[away] - true[home] - HFA))
        store.add_odds(snapshot("book", 2026, week, games, now=float(week)))

    def replay(season, week):
        rows = store.odds_for_week(season, week)
        return [GameOdds(source="book", home=g["home"], away=g["away"],
                         fetched_at=1.0, spread=g["spread"])
                for g in rows[-1]["games"]]

    got = default_sources(store, fetch_week=replay)["market_strength"][1](2026, 1)
    raw = true[favourite]
    assert abs(got[favourite] - raw) < abs(week1_solve[favourite] - raw), (
        f"remaining-slate favourite={got[favourite]} "
        f"week1-ridge={week1_solve[favourite]} raw={raw}")


def test_market_strength_fails_when_remaining_lines_are_missing():
    """No silent fallback to the 1..current-only solve. Week 2 with only
    week-1 closes in the log must raise, not invert the past slate."""
    from winspool.gameodds import GameOdds
    from winspool.oddslog import snapshot
    from winspool.ratingsjob import default_sources

    store = InMemoryStore({})
    store.add_odds(snapshot("book", 2026, 1, [
        GameOdds(source="book", home="KC", away="BUF", fetched_at=10.0, spread=-3.0),
    ], now=10.0))
    with pytest.raises(RuntimeError, match="remaining-slate"):
        default_sources(store, fetch_week=lambda s, w: [])["market_strength"][1](2026, 2)


def test_market_strength_fetches_and_stores_remaining_week_lines():
    """Remaining ESPN weeks are fetched through the existing snapshot path
    and stored week-keyed. A week with no posted spread fails the source."""
    from winspool.gameodds import GameOdds
    from winspool.ratingsjob import default_sources

    store = InMemoryStore({})
    calls = []

    def fetch_week(season, week):
        calls.append(week)
        return [GameOdds(source="book", home="KC", away="BUF",
                         fetched_at=float(week), spread=-3.0)]

    default_sources(store, fetch_week=fetch_week)["market_strength"][1](2026, 16)
    assert calls == [16, 17, 18]
    assert store.odds_for_week(2026, 17)

    def empty_week(season, week):
        return []

    with pytest.raises(RuntimeError, match="week 3"):
        default_sources(InMemoryStore({}), fetch_week=empty_week
                        )["market_strength"][1](2026, 3)


def test_a_partially_parsed_source_is_refused_rather_than_stored():
    """26 of 32 teams is the shape of a rename ESPN made and `resolve` missed.
    Stored, it is invisible: the six missing teams become 0.0 (league average),
    `to_common_scale` z-scores the source, its spread SHRINKS and the 26
    survivors' votes are inflated — a silently different model that reports
    healthy. A partial parse is worse than no parse, so it is a failure."""
    store = InMemoryStore({})
    partial = dict(list(_full().items())[:MIN_TEAM_COVERAGE - 1])
    out = refresh_ratings(store, season=2026, week=5, now=100.0,
                          sources={"espn_fpi": ("power", lambda s, w: partial)})
    assert out["written"] == {}
    err = out["errors"]["espn_fpi"]
    assert f"{MIN_TEAM_COVERAGE - 1}/32" in err and str(MIN_TEAM_COVERAGE) in err
    assert store.latest_ratings() == {}, "a partial parse must not become the live row"

    # ...and the floor is a floor, not a demand for perfection: one rebranded
    # club must not red-light an otherwise fine fetch.
    nearly = dict(list(_full().items())[:MIN_TEAM_COVERAGE])
    out = refresh_ratings(store, season=2026, week=5, now=200.0,
                          sources={"espn_fpi": ("power", lambda s, w: nearly)})
    assert out["written"] == {"espn_fpi": MIN_TEAM_COVERAGE}


def test_a_malformed_win_distribution_fails_the_source_at_write_time():
    """A ragged PMF otherwise surfaces inside `rng.choice` during a live
    refresh, in a numpy message naming neither the team nor the source."""
    store = InMemoryStore({})
    good = {t: [1.0 / 18] * 18 for t in TEAMS}
    for label, broken in (("short", [1.0 / 5] * 5),
                          ("nan", [float("nan")] * 18),
                          ("zero", [0.0] * 18)):
        doc = {**good, "KC": broken}
        out = refresh_ratings(store, season=2026, week=5, now=100.0,
                              sources={"kalshi": ("distribution", lambda s, w, d=doc: d)})
        assert "KC" in out["errors"]["kalshi"], label
    assert refresh_ratings(store, season=2026, week=5, now=100.0,
                           sources={"kalshi": ("distribution", lambda s, w: good)}
                           )["written"] == {"kalshi": len(TEAMS)}


def test_a_source_whose_store_write_fails_does_not_cost_the_later_sources():
    """The design promise is that a source which fails is recorded and skipped
    while the others still write — one source being down must never cost us the
    other two, which is most of the argument for having three. The per-source
    try used to wrap only the fetch, so a store write that raised escaped it and
    aborted the loop mid-iteration: every later source produced no row at all,
    not even the failure row. Here the FETCH succeeds and the WRITE is what
    breaks, which is exactly the case that shipped."""
    class PickyStore(InMemoryStore):
        def add_rating(self, row):
            if row["source"] == "kalshi" and row["ok"]:
                raise TypeError("Object of type ndarray is not JSON serializable")
            return super().add_rating(row)

    store = PickyStore({})
    sources = {
        "espn_fpi": ("power", lambda s, w: _full(1.0)),
        "kalshi": ("distribution", lambda s, w: {t: [1.0 / 18] * 18 for t in TEAMS}),
        "epa_adj": ("power", lambda s, w: _full(2.0)),
    }
    out = refresh_ratings(store, season=2026, week=5, sources=sources, now=100.0)

    assert set(out["written"]) == {"espn_fpi", "epa_adj"}, \
        "the sources after the broken one must still be written"
    assert "ndarray" in out["errors"]["kalshi"]
    assert set(store.latest_ratings()) == {"espn_fpi", "epa_adj"}
    # the failure itself is recorded, so Admin health can name it
    assert [r["ok"] for r in store.ratings_history("kalshi")] == [False]

    # ...and the degenerate case: if the STORE is what is broken, the ok=False
    # row cannot be written either. That must not recurse, must not raise and
    # must not go quiet — the run finishes every source and the report still
    # names each failure, which is what makes the endpoint 503 and the systemd
    # unit go red.
    class DeadStore(InMemoryStore):
        def add_rating(self, row):
            raise RuntimeError("disk is gone")

    out = refresh_ratings(DeadStore({}), season=2026, week=5, now=100.0,
                          sources={k: v for k, v in sources.items() if k != "kalshi"})
    assert out["written"] == {}
    assert set(out["errors"]) == {"espn_fpi", "epa_adj"}
    assert "could not be stored" in out["errors"]["espn_fpi"]
