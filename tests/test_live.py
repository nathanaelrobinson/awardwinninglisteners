import numpy as np
import pandas as pd
import pytest

from winspool import live
from winspool.teams import TEAM_INDEX, TEAMS

COLS = ["week", "game_type", "home_team", "away_team", "home_score", "away_score"]


def sched(rows):
    return pd.DataFrame(rows, columns=COLS)


@pytest.fixture
def inseason():
    """Weeks 1-2 played, week 3 has one final and one unplayed, week 4 unplayed."""
    return sched([
        (1, "REG", "KC", "BUF", 27, 20),
        (1, "REG", "DAL", "PHI", 17, 17),      # tie
        (2, "REG", "BUF", "KC", 10, 13),
        (2, "REG", "PHI", "DAL", 30, 10),
        (3, "REG", "KC", "PHI", 21, 14),
        (3, "REG", "BUF", "DAL", None, None),
        (4, "REG", "DAL", "KC", None, None),
        (4, "REG", "PHI", "BUF", None, None),
        (19, "POST", "KC", "BUF", None, None),  # ignored
    ])


def test_split_schedule_reg_only(inseason):
    played, remaining = live.split_schedule(inseason)
    assert len(played) == 5 and len(remaining) == 3
    assert set(played["game_type"]) == {"REG"} and set(remaining["game_type"]) == {"REG"}


def test_banked_wins_counts_ties_as_half(inseason):
    played, _ = live.split_schedule(inseason)
    b = live.banked_wins(played)
    assert b.shape == (32,)
    assert b[TEAM_INDEX["KC"]] == 3
    assert b[TEAM_INDEX["BUF"]] == 0
    assert b[TEAM_INDEX["DAL"]] == 0.5 and b[TEAM_INDEX["PHI"]] == 1.5


def test_week_of_is_first_week_with_unplayed_game(inseason):
    assert live.week_of(inseason) == 3
    done = inseason.copy()
    done.loc[done["home_score"].isna(), ["home_score", "away_score"]] = 1
    assert live.week_of(done) == 19


def test_remaining_matchups_and_games_in_week(inseason):
    _, remaining = live.split_schedule(inseason)
    home, away = live.remaining_matchups(remaining)
    assert list(home) == [TEAM_INDEX["BUF"], TEAM_INDEX["DAL"], TEAM_INDEX["PHI"]]
    assert list(away) == [TEAM_INDEX["DAL"], TEAM_INDEX["KC"], TEAM_INDEX["BUF"]]
    wk = live.games_in_week(remaining, 3)
    assert len(wk) == 1 and wk.iloc[0]["home_team"] == "BUF"
    per = live.remaining_games_per_team(remaining)
    assert per[TEAM_INDEX["KC"]] == 1 and per[TEAM_INDEX["BUF"]] == 2


FIX = "tests/fixtures"


def test_vegas_share_full_at_week_1_and_gone_by_week_9():
    assert live.vegas_share(1) == 1.0
    assert live.vegas_share(5) == pytest.approx(0.5)
    assert live.vegas_share(9) == 0.0
    assert live.vegas_share(14) == 0.0


def _fixture_matchups():
    from winspool.data import load_schedule, schedule_matchups
    return schedule_matchups(load_schedule(f"{FIX}/schedule_2026.csv"))


def test_source_matrix_equal_voices_with_vegas_fading():
    home, away = _fixture_matchups()
    m, w, names, sigma = live.source_matrix_for_week(
        f"{FIX}/win_totals.csv", f"{FIX}/power_ratings.csv", None, home, away, week=1)
    assert names == ["vegas", "fpi", "sagarin", "massey"]
    assert m.shape == (4, 32) and sigma.shape == (32,)
    assert np.allclose(w, 0.25)                      # pre-season: seven-equal-voices rule
    assert np.allclose(sigma, 4.5)                   # no Kalshi file -> flat base sigma
    _, w5, _, _ = live.source_matrix_for_week(
        f"{FIX}/win_totals.csv", f"{FIX}/power_ratings.csv", None, home, away, week=5)
    assert w5[0] == pytest.approx(0.5 / 3.5) and np.allclose(w5[1:], 1 / 3.5)
    _, w9, _, _ = live.source_matrix_for_week(
        f"{FIX}/win_totals.csv", f"{FIX}/power_ratings.csv", None, home, away, week=9)
    assert w9[0] == 0.0 and np.allclose(w9[1:], 1 / 3)
    assert w.sum() == pytest.approx(1) and w5.sum() == pytest.approx(1) and w9.sum() == pytest.approx(1)


def test_ensemble_is_memoised_across_weeks(monkeypatch):
    from winspool import recommend
    home, away = _fixture_matchups()
    calls = []
    real = recommend._assemble_sources
    monkeypatch.setattr(recommend, "_assemble_sources",
                        lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    live._ENSEMBLE_CACHE.clear()
    for wk in (1, 2, 9):
        live.source_matrix_for_week(f"{FIX}/win_totals.csv", f"{FIX}/power_ratings.csv",
                                    None, home, away, week=wk)
    assert len(calls) == 1


def test_live_matches_preseason_before_kickoff():
    """Before any game is played the live model must agree with Draft Review
    (recommend.build_wins) up to Monte Carlo noise: same voices, same weights."""
    from winspool.recommend import build_wins
    from winspool.data import load_schedule
    sched = load_schedule(f"{FIX}/schedule_2026.csv")
    n = 6000
    wins, _ = build_wins(f"{FIX}/schedule_2026.csv", f"{FIX}/win_totals.csv", n_seasons=n,
                         seed=0, power_path=f"{FIX}/power_ratings.csv", kalshi_dist_path=None)
    teams = sorted(set(sched["home_team"]) | set(sched["away_team"]))
    rosters = {"A": teams[0::2], "B": teams[1::2]}
    pre = live.pool_pwin(live._player_totals(rosters, wins.astype(float)))
    df = pd.DataFrame({"week": (np.arange(len(sched)) % 18) + 1, "game_type": "REG",
                       "home_team": sched["home_team"], "away_team": sched["away_team"],
                       "home_score": np.nan, "away_score": np.nan})
    doc = live.compute_live(rosters, df, totals_path=f"{FIX}/win_totals.csv",
                            power_path=f"{FIX}/power_ratings.csv", kalshi_dist_path=None,
                            ratings_fetched_at=None, n_seasons=n, seed=1)
    for r in doc["rows"]:
        assert r["pwin"] == pytest.approx(pre[r["player"]], abs=0.03), r["player"]


def test_season_sigma_shrinks_with_games_left():
    per = np.full(32, 17)
    per[0] = 0
    per[1] = 4
    s = live.season_sigma(per, base_sigma=4.5)
    assert s[2] == pytest.approx(4.5)
    assert s[0] == 0.0
    assert s[1] == pytest.approx(4.5 * np.sqrt(4 / 17))


def test_consensus_is_weighted_mean():
    m = np.array([[1.0] * 32, [3.0] * 32])
    assert np.allclose(live.consensus(m, np.array([0.25, 0.75])), 2.5)


ROSTERS = {
    "A": ["KC", "PHI"],
    "B": ["BUF", "DAL"],
}


def test_pool_pwin_ties_count_for_both():
    t = {"A": np.array([10, 12, 8]), "B": np.array([10, 11, 9])}
    p = live.pool_pwin(t)
    assert p["A"] == pytest.approx(2 / 3)   # seasons 0 (tie) and 1
    assert p["B"] == pytest.approx(2 / 3)   # seasons 0 (tie) and 2


def test_compute_live_shape_and_banked(inseason):
    doc = live.compute_live(ROSTERS, inseason,
                            totals_path=f"{FIX}/win_totals.csv",
                            power_path=f"{FIX}/power_ratings.csv",
                            kalshi_dist_path=None,
                            ratings_fetched_at="2026-09-23T09:00:00",
                            n_seasons=2000, seed=1, now=1000.0)
    assert doc["week"] == 3 and doc["computed_at"] == 1000.0
    assert doc["ratings_fetched_at"] == "2026-09-23T09:00:00"
    assert doc["n_sims"] == 2000 and len(doc["x"]) > 0
    rows = {r["player"]: r for r in doc["rows"]}
    assert set(rows) == {"A", "B"}
    a = rows["A"]
    # KC 3 banked + PHI 1.5 banked
    assert a["banked"] == 4.5
    assert {t["code"]: t["banked"] for t in a["teams"]} == {"KC": 3, "PHI": 1.5}
    # Each team: exp_wins >= banked and <= banked + games left (KC 1, PHI 2)
    by = {t["code"]: t for t in a["teams"]}
    assert 3 <= by["KC"]["exp_wins"] <= 4
    assert 1.5 <= by["PHI"]["exp_wins"] <= 3.5
    assert a["exp_wins"] == pytest.approx(sum(t["exp_wins"] for t in a["teams"]), abs=0.2)
    assert a["p10"] <= a["p90"]
    assert len(a["dist"]) == len(doc["x"]) and abs(sum(a["dist"]) - 1) < 1e-3
    assert a["market_pwin"] is None
    assert 0.99 <= sum(r["pwin"] for r in doc["rows"]) <= 1.2
    assert [r["pwin"] for r in doc["rows"]] == sorted((r["pwin"] for r in doc["rows"]), reverse=True)


def test_compute_live_this_week_games_and_leverage(inseason):
    doc = live.compute_live(ROSTERS, inseason,
                            totals_path=f"{FIX}/win_totals.csv",
                            power_path=f"{FIX}/power_ratings.csv",
                            kalshi_dist_path=None, ratings_fetched_at=None,
                            n_seasons=2000, seed=1)
    tw = {r["player"]: r for r in doc["this_week"]}
    # Week 3 has one unplayed game: BUF (home) vs DAL. Both are B's teams; A has none.
    assert tw["A"]["games"] == [] and tw["A"]["leverage"] == 0.0
    # B owns both sides of BUF vs DAL: one locked chip worth exactly one win.
    assert tw["B"]["games"] == [{"team": "BUF", "opp": "DAL", "home": True, "p": 1.0, "lock": True}]
    assert tw["B"]["exp_wins"] == 1.0 and tw["B"]["min_wins"] == 1 and tw["B"]["max_wins"] == 1
    assert tw["A"]["exp_wins"] == 0.0 and tw["A"]["min_wins"] == 0 and tw["A"]["max_wins"] == 0
    assert tw["B"]["leverage"] == 0.0
    assert [r["leverage"] for r in doc["this_week"]] == sorted(
        (r["leverage"] for r in doc["this_week"]), reverse=True)


def test_compute_live_leverage_positive_when_opponent_is_not_mine(inseason):
    rosters = {"A": ["KC", "BUF"], "B": ["PHI", "DAL"]}
    doc = live.compute_live(rosters, inseason,
                            totals_path=f"{FIX}/win_totals.csv",
                            power_path=f"{FIX}/power_ratings.csv",
                            kalshi_dist_path=None, ratings_fetched_at=None,
                            n_seasons=3000, seed=2)
    tw = {r["player"]: r for r in doc["this_week"]}
    assert tw["A"]["leverage"] > 0.05 and tw["B"]["leverage"] > 0.05
    a = tw["A"]["games"]
    assert a == [{"team": "BUF", "opp": "DAL", "home": True, "p": a[0]["p"], "lock": False}]
    assert tw["A"]["exp_wins"] == pytest.approx(round(a[0]["p"], 1))
    assert tw["A"]["min_wins"] == 0 and tw["A"]["max_wins"] == 1
    assert tw["A"]["games"][0]["p"] == pytest.approx(1 - tw["B"]["games"][0]["p"], abs=2e-3)


def test_compute_live_season_over(inseason):
    done = inseason.copy()
    done.loc[done["home_score"].isna(), ["home_score", "away_score"]] = [20, 10]
    doc = live.compute_live(ROSTERS, done,
                            totals_path=f"{FIX}/win_totals.csv",
                            power_path=f"{FIX}/power_ratings.csv",
                            kalshi_dist_path=None, ratings_fetched_at=None,
                            n_seasons=500, seed=0)
    assert doc["week"] == 19
    assert all(r["games"] == [] for r in doc["this_week"])
    rows = {r["player"]: r for r in doc["rows"]}
    assert rows["A"]["exp_wins"] == rows["A"]["banked"]
    assert rows["A"]["p10"] == rows["A"]["p90"]


def test_market_pwin_from_pmfs(tmp_path):
    # KC always 10 wins, BUF always 9, everyone else 0 -> A (KC) beats B (BUF) always.
    cols = ["team"] + [f"p{k}" for k in range(18)]
    rows = []
    for code in TEAMS:
        pmf = [0.0] * 18
        pmf[10 if code == "KC" else 9 if code == "BUF" else 0] = 1.0
        rows.append([code] + pmf)
    path = tmp_path / "k.csv"
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)
    p = live.market_pwin({"A": ["KC"], "B": ["BUF"]}, str(path), 200, np.random.default_rng(0))
    assert p == {"A": 1.0, "B": 0.0}
    assert live.market_pwin({"A": ["KC"]}, str(tmp_path / "nope.csv"), 10,
                            np.random.default_rng(0)) is None

    # Missing team (BUF dropped from the distributions file) -> None overall.
    rows2 = [r for r in rows if r[0] != "BUF"]
    path2 = tmp_path / "k2.csv"
    pd.DataFrame(rows2, columns=cols).to_csv(path2, index=False)
    assert live.market_pwin({"A": ["KC"], "B": ["BUF"]}, str(path2), 10,
                            np.random.default_rng(0)) is None


def test_dist_keeps_half_integer_totals_distinct():
    # _dist rounds to 5 decimals, so 1/3 and 2/3 land ~3e-6 off their exact
    # values -- outside pytest.approx's default rel=1e-6 tolerance. abs=1e-4
    # comfortably covers the rounding without loosening the actual assertion
    # (that distinct half-integer totals stay in distinct bins).
    d = live._dist(np.array([4.5, 5.5, 6.5]), 4, 4)
    assert d == [0.0, pytest.approx(1 / 3, abs=1e-4), pytest.approx(1 / 3, abs=1e-4),
                 pytest.approx(1 / 3, abs=1e-4)]
    d = live._dist(np.array([4, 4, 6]), 4, 3)
    assert d == [pytest.approx(2 / 3, abs=1e-4), 0.0, pytest.approx(1 / 3, abs=1e-4)]


def test_ratings_fetched_at_only_considers_power_sources(tmp_path):
    import json as _json
    meta = [
        {"kind": "kalshi", "ok": True, "fetched_at": "2026-09-25T09:00:00"},
        {"kind": "power", "ok": True, "fetched_at": "2026-09-20T09:00:00"},
    ]
    path = tmp_path / "sources_meta.json"
    path.write_text(_json.dumps(meta))
    assert live.ratings_fetched_at(str(tmp_path)) == "2026-09-20T09:00:00"

    meta2 = [{"kind": "kalshi", "ok": True, "fetched_at": "2026-09-25T09:00:00"}]
    path.write_text(_json.dumps(meta2))
    assert live.ratings_fetched_at(str(tmp_path)) is None


# --- Per-source views (score lens) -------------------------------------------

def test_compute_live_has_a_view_per_source(inseason):
    doc = live.compute_live(ROSTERS, inseason,
                            totals_path=f"{FIX}/win_totals.csv",
                            power_path=f"{FIX}/power_ratings.csv",
                            kalshi_dist_path=None, ratings_fetched_at=None,
                            n_seasons=1500, seed=3)
    views = doc["views"]
    assert list(views) == ["blend", "vegas", "fpi", "sagarin", "massey"]
    blend = {r["player"]: r for r in views["blend"]}
    top = {r["player"]: r for r in doc["rows"]}
    for p in ROSTERS:
        # blend view == the top-level rows, minus the chart/market fields
        assert blend[p]["pwin"] == top[p]["pwin"] and blend[p]["exp_wins"] == top[p]["exp_wins"]
        assert set(blend[p]) == {"player", "teams", "banked", "exp_wins", "pwin", "p10", "p90"}
    for name, rows in views.items():
        assert sorted(r["player"] for r in rows) == sorted(ROSTERS)
        assert [r["pwin"] for r in rows] == sorted((r["pwin"] for r in rows), reverse=True)
        for r in rows:
            assert r["banked"] == top[r["player"]]["banked"]          # banked wins never depend on the lens
            assert {t["code"] for t in r["teams"]} == set(ROSTERS[r["player"]])
            assert abs(sum(t["exp_wins"] for t in r["teams"]) - r["exp_wins"]) < 0.2
        assert 0.99 <= sum(r["pwin"] for r in rows) <= 1.2
    # single sources disagree somewhere, otherwise the lens is pointless
    exp = [tuple(r["exp_wins"] for r in sorted(rows, key=lambda r: r["player"])) for rows in views.values()]
    assert len(set(exp)) > 1


def test_views_season_over_are_all_banked(inseason):
    done = inseason.copy()
    done.loc[done["home_score"].isna(), ["home_score", "away_score"]] = [20, 10]
    doc = live.compute_live(ROSTERS, done, totals_path=f"{FIX}/win_totals.csv",
                            power_path=f"{FIX}/power_ratings.csv", kalshi_dist_path=None,
                            ratings_fetched_at=None, n_seasons=300, seed=0)
    for rows in doc["views"].values():
        for r in rows:
            assert r["exp_wins"] == r["banked"]
