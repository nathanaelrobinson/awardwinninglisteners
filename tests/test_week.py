import itertools

import pandas as pd
import pytest

from winspool.week import build_week, poisson_binomial


def test_no_games_is_a_certain_zero():
    assert poisson_binomial([]) == [1.0]


def test_a_certainty_puts_all_the_mass_on_one_total():
    assert poisson_binomial([1.0, 1.0]) == pytest.approx([0.0, 0.0, 1.0])
    assert poisson_binomial([0.0, 0.0]) == pytest.approx([1.0, 0.0, 0.0])


def test_two_coin_flips():
    assert poisson_binomial([0.5, 0.5]) == pytest.approx([0.25, 0.5, 0.25])


def test_it_always_sums_to_one():
    assert sum(poisson_binomial([0.3, 0.62, 0.41, 0.9, 0.05, 0.77])) == pytest.approx(1.0)


def test_it_matches_brute_force_enumeration():
    ps = [0.3, 0.62, 0.41, 0.9, 0.05, 0.77]
    want = [0.0] * (len(ps) + 1)
    for combo in itertools.product([0, 1], repeat=len(ps)):
        prob = 1.0
        for p, hit in zip(ps, combo):
            prob *= p if hit else (1 - p)
        want[sum(combo)] += prob
    assert poisson_binomial(ps) == pytest.approx(want)


def test_its_mean_is_the_sum_of_the_probabilities():
    ps = [0.3, 0.62, 0.41]
    dist = poisson_binomial(ps)
    mean = sum(i * d for i, d in enumerate(dist))
    assert mean == pytest.approx(sum(ps))


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


def test_chalk_is_expected_wins_from_the_probabilities_used():
    out = build_week(LIVE, ROSTERS, SCHED, 1, [])
    a = next(p for p in out["players"] if p["name"] == "A")
    assert a["chalk"] == pytest.approx(0.60 + 0.50)


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


def test_the_distribution_covers_every_uncertain_game():
    out = build_week(LIVE, ROSTERS, SCHED, 1, [])
    a = next(p for p in out["players"] if p["name"] == "A")
    assert len(a["dist"]) == 3          # two uncertain games -> totals 0, 1, 2
    assert sum(a["dist"]) == pytest.approx(1.0)


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


def test_a_week_is_final_only_when_every_game_has_a_score():
    played = SCHED.copy()
    played["home_score"] = [24, 20, 20]
    played["away_score"] = [17, 17, 17]
    assert build_week(LIVE, ROSTERS, SCHED, 1, [])["state"] == "live"
    assert build_week(LIVE, ROSTERS, played, 1, [])["state"] == "final"


def test_a_completed_week_reports_what_actually_happened():
    played = SCHED.copy()
    played["home_score"] = [24, 20, 20]
    played["away_score"] = [17, 17, 17]
    out = build_week(LIVE, ROSTERS, played, 1, [])
    a = next(p for p in out["players"] if p["name"] == "A")
    assert a["actual"] == 2          # KC and LA both won at home
    assert out["state"] == "final"


def test_a_live_week_has_no_actual():
    out = build_week(LIVE, ROSTERS, SCHED, 1, [])
    assert all(p["actual"] is None for p in out["players"])


def test_each_player_carries_their_pool_odds_for_the_swing_tooltip():
    out = build_week(LIVE, ROSTERS, SCHED, 1, [])
    assert {p["name"]: p["pwin"] for p in out["players"]} == {"A": 0.6, "B": 0.4}


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
