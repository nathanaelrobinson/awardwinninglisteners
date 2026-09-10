import itertools

import pandas as pd
import pytest

from winspool.week import build_week, poisson_binomial


def test_the_degenerate_cases_land_where_they_must():
    assert poisson_binomial([]) == [1.0]
    assert poisson_binomial([1.0, 1.0]) == pytest.approx([0.0, 0.0, 1.0])
    assert poisson_binomial([0.0, 0.0]) == pytest.approx([1.0, 0.0, 0.0])
    assert poisson_binomial([0.5, 0.5]) == pytest.approx([0.25, 0.5, 0.25])


def test_it_matches_brute_force_enumeration():
    ps = [0.3, 0.62, 0.41, 0.9, 0.05, 0.77]
    want = [0.0] * (len(ps) + 1)
    for combo in itertools.product([0, 1], repeat=len(ps)):
        prob = 1.0
        for p, hit in zip(ps, combo):
            prob *= p if hit else (1 - p)
        want[sum(combo)] += prob
    assert poisson_binomial(ps) == pytest.approx(want)


LIVE = {
    "week": 1,
    "rows": [{"player": "A", "pwin": 0.6}, {"player": "B", "pwin": 0.4}],
    "games": [
        {"home": "KC", "away": "DEN", "p_model": 0.55, "p_used": 0.60,
         "source": "market", "swing": {"A": 0.04, "B": -0.04}},
        {"home": "LA", "away": "SF", "p_model": 0.50, "p_used": 0.50,
         "source": "model", "swing": {"A": 0.01, "B": -0.01}},
    ],
}
ROSTERS = {"A": ["KC", "LA"], "B": ["DEN", "SF"]}
SCHED = pd.DataFrame([
    {"week": 1, "game_type": "REG", "home_team": "KC", "away_team": "DEN",
     "home_score": None, "away_score": None, "gameday": "2026-09-14",
     "gametime": "20:15"},
    {"week": 1, "game_type": "REG", "home_team": "LA", "away_team": "SF",
     "home_score": None, "away_score": None, "gameday": "2026-09-14",
     "gametime": "16:25"},
    {"week": 1, "game_type": "REG", "home_team": "NE", "away_team": "NYJ",
     "home_score": 20, "away_score": 17, "gameday": "2026-09-11",
     "gametime": "20:15"},
])


def test_chalk_and_the_distribution_come_from_the_probabilities_used():
    out = build_week(LIVE, ROSTERS, SCHED, 1, [])
    a = next(p for p in out["players"] if p["name"] == "A")
    assert a["chalk"] == pytest.approx(0.60 + 0.50)
    # KC at 0.60 and LA at 0.50, two uncertain games -> totals 0, 1, 2.
    assert a["dist"] == pytest.approx([0.20, 0.50, 0.30])
    # B owns the away side of both games, so B runs on 1 - p, not p.
    b = next(p for p in out["players"] if p["name"] == "B")
    assert b["chalk"] == pytest.approx(0.40 + 0.50)
    assert b["dist"] == pytest.approx([0.30, 0.50, 0.20])
    # The board's swing tooltip needs each player's unconditional pool odds.
    assert {p["name"]: p["pwin"] for p in out["players"]} == {"A": 0.6, "B": 0.4}


def test_a_played_game_is_banked_and_leaves_the_distribution():
    rosters = {"A": ["NE"], "B": ["NYJ"]}
    live = {**LIVE, "rows": [{"player": "A", "pwin": 0.6},
                             {"player": "B", "pwin": 0.4}], "games": []}
    out = build_week(live, rosters, SCHED, 1, [])
    a = next(p for p in out["players"] if p["name"] == "A")
    assert a["banked"] == 1 and a["chalk"] == pytest.approx(1.0)
    assert a["dist"] == pytest.approx([1.0])


def test_a_game_between_two_of_my_own_teams_is_a_lock():
    out = build_week(LIVE, {"A": ["KC", "DEN"], "B": ["LA", "SF"]}, SCHED, 1, [])
    a = next(p for p in out["players"] if p["name"] == "A")
    assert a["locks"] == 1 and a["chalk"] == pytest.approx(1.0)
    assert a["dist"] == pytest.approx([1.0])


def test_games_are_ordered_by_their_largest_swing():
    out = build_week(LIVE, ROSTERS, SCHED, 1, [])
    # SCHED's third game (NE/NYJ) is already final, so it sorts last regardless
    # of swing; the two live games sort by descending largest absolute swing.
    assert [(g["home"], g["away"]) for g in out["games"]] == [
        ("KC", "DEN"), ("LA", "SF"), ("NE", "NYJ")]


def test_played_games_come_back_with_their_score_and_no_swing():
    out = build_week(LIVE, ROSTERS, SCHED, 1, [])
    ne = next(g for g in out["games"] if g["home"] == "NE")
    assert ne["state"] == "final" and ne["home_score"] == 20 and ne["away_score"] == 17
    assert ne["swing"] == {}


def test_a_week_goes_final_only_when_played_out_and_only_then_has_actuals():
    played = SCHED.copy()
    played["home_score"] = [24, 20, 20]
    played["away_score"] = [17, 17, 17]

    live_out = build_week(LIVE, ROSTERS, SCHED, 1, [])
    assert live_out["state"] == "live"
    assert all(p["actual"] is None for p in live_out["players"])

    out = build_week(LIVE, ROSTERS, played, 1, [])
    assert out["state"] == "final"
    a = next(p for p in out["players"] if p["name"] == "A")
    assert a["actual"] == 2          # KC and LA both won at home


def test_the_line_comes_from_the_odds_log():
    rows = [{"source": "book", "fetched_at": 5.0, "games": [
        {"home": "KC", "away": "DEN", "spread": -2.5, "total": 43.5,
         "ml_home": -148, "ml_away": 124, "yes_home": None, "yes_away": None,
         "p_home": None}]}]
    out = build_week(LIVE, ROSTERS, SCHED, 1, rows)
    kc = next(g for g in out["games"] if g["home"] == "KC")
    assert kc["spread"] == pytest.approx(-2.5)
    assert kc["total"] == pytest.approx(43.5)
    assert kc["p_book"] == pytest.approx(0.572, abs=1e-3)
    assert kc["p_kalshi"] is None


def test_history_is_one_market_prob_per_cycle_and_skips_unpriced_ones():
    # Cycle 1 prices both games; cycle 2 only re-prices KC/DEN, so LA/SF's
    # history should have one entry, not two with a gap filled in.
    rows = [
        {"source": "book", "fetched_at": 1.0, "games": [
            {"home": "KC", "away": "DEN", "spread": -2.5, "total": 43.5,
             "ml_home": None, "ml_away": None, "yes_home": None,
             "yes_away": None, "p_home": None},
            {"home": "LA", "away": "SF", "spread": 1.0, "total": 44.0,
             "ml_home": None, "ml_away": None, "yes_home": None,
             "yes_away": None, "p_home": None}]},
        {"source": "book", "fetched_at": 2.0, "games": [
            {"home": "KC", "away": "DEN", "spread": -3.0, "total": 43.5,
             "ml_home": None, "ml_away": None, "yes_home": None,
             "yes_away": None, "p_home": None}]},
    ]
    out = build_week(LIVE, ROSTERS, SCHED, 1, rows)
    kc = next(g for g in out["games"] if g["home"] == "KC")
    la = next(g for g in out["games"] if g["home"] == "LA")
    assert [fetched_at for fetched_at, _ in kc["history"]] == [1.0, 2.0]
    assert kc["history"][-1][1] == pytest.approx(kc["p_book"], abs=1e-4)
    assert len(la["history"]) == 1
