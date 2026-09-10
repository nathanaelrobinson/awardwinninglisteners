import pandas as pd
import pytest

from winspool import live

COLS = ["week", "game_type", "home_team", "away_team", "home_score", "away_score"]
FIX = "tests/fixtures"
ROSTERS = {"A": ["KC", "BUF"], "B": ["PHI", "DAL"]}


def sched(rows):
    return pd.DataFrame(rows, columns=COLS)


@pytest.fixture
def inseason():
    """Weeks 1-2 played; week 3 has two unplayed games, each head-to-head."""
    return sched([
        (1, "REG", "KC", "BUF", 27, 20),
        (1, "REG", "DAL", "PHI", 17, 14),
        (2, "REG", "BUF", "KC", 10, 13),
        (2, "REG", "PHI", "DAL", 30, 10),
        (3, "REG", "BUF", "DAL", None, None),
        (3, "REG", "KC", "PHI", None, None),
        (4, "REG", "DAL", "KC", None, None),
        (4, "REG", "PHI", "BUF", None, None),
    ])


def _kw(**over):
    base = dict(totals_path=f"{FIX}/win_totals.csv",
                power_path=f"{FIX}/power_ratings.csv",
                kalshi_dist_path=None, ratings_fetched_at=None,
                n_seasons=2000, seed=1)
    base.update(over)
    return base


def test_market_probs_keys_on_the_home_away_pair():
    rows = [{"source": "book", "games": [
        {"home": "KC", "away": "DEN", "spread": None, "total": None,
         "ml_home": -148, "ml_away": 124, "yes_home": None, "yes_away": None,
         "p_home": None}]}]
    got = live.market_probs(rows)
    assert set(got) == {("KC", "DEN")}
    assert got[("KC", "DEN")] == pytest.approx(0.572, abs=1e-3)


def test_market_probs_ignores_the_model_source():
    rows = [{"source": "model", "games": [
        {"home": "KC", "away": "DEN", "spread": None, "total": None,
         "ml_home": None, "ml_away": None, "yes_home": None, "yes_away": None,
         "p_home": 0.99}]}]
    assert live.market_probs(rows) == {}


def test_current_week_games_are_simulated_from_the_market(inseason):
    doc = live.compute_live(ROSTERS, inseason, market={("BUF", "DAL"): 0.90},
                            **_kw())
    game = next(g for g in doc["games"] if g["home"] == "BUF")
    assert game["p_used"] == pytest.approx(0.90)
    assert game["source"] == "market"
    assert game["p_model"] != pytest.approx(0.90)


def test_a_game_with_no_market_falls_back_to_the_model(inseason):
    doc = live.compute_live(ROSTERS, inseason, market={("BUF", "DAL"): 0.90},
                            **_kw())
    other = next(g for g in doc["games"] if g["home"] == "KC")
    assert other["source"] == "model"
    assert other["p_used"] == pytest.approx(other["p_model"])


def test_no_market_at_all_reproduces_the_projection_exactly(inseason):
    without = live.compute_live(ROSTERS, inseason, **_kw())
    empty = live.compute_live(ROSTERS, inseason, market={}, **_kw())
    assert [r["pwin"] for r in without["rows"]] == [r["pwin"] for r in empty["rows"]]


def test_every_game_carries_a_swing_for_every_player(inseason):
    doc = live.compute_live(ROSTERS, inseason, **_kw())
    assert len(doc["games"]) == 2
    for g in doc["games"]:
        assert set(g["swing"]) == set(ROSTERS)


def test_a_head_to_head_game_moves_its_two_owners_in_opposite_directions(inseason):
    doc = live.compute_live(ROSTERS, inseason, **_kw(n_seasons=4000))
    g = next(g for g in doc["games"] if g["home"] == "BUF")
    assert g["swing"]["A"] > 0 > g["swing"]["B"]


def test_the_two_branches_recombine_to_the_unconditional_probability(inseason):
    doc = live.compute_live(ROSTERS, inseason, **_kw(n_seasons=8000))
    g = next(g for g in doc["games"] if g["home"] == "BUF")
    base = {r["player"]: r["pwin"] for r in doc["rows"]}
    p = g["p_used"]
    for player, swing in g["swing"].items():
        if_home = base[player] + (1 - p) * swing
        if_away = if_home - swing
        assert p * if_home + (1 - p) * if_away == pytest.approx(base[player], abs=0.02)
