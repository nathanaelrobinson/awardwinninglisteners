import numpy as np
from winspool.ratings import strength_from_totals

def test_higher_total_gets_higher_strength():
    totals = np.array([11.5, 6.5, 9.0])
    s = strength_from_totals(totals)
    assert s[0] > s[2] > s[1]

def test_strengths_mean_centered():
    s = strength_from_totals(np.array([11.5, 6.5, 9.0, 8.0]))
    assert abs(s.mean()) < 1e-9

from winspool.data import load_power_ratings
from winspool.ratings import power_strength, blend, team_sigma

def test_blend_endpoints():
    m = np.array([2.0, -2.0, 0.0]); p = np.array([-1.0, 1.0, 0.0])
    assert np.allclose(blend(m, p, w=1.0), m)
    assert np.allclose(blend(m, p, w=0.0), p)

def test_power_strength_orders_teams():
    df = load_power_ratings("tests/fixtures/power_ratings.csv")
    s = power_strength(df)
    from winspool.teams import TEAM_INDEX
    assert s[TEAM_INDEX["BUF"]] > s[TEAM_INDEX["NYJ"]]

def test_team_sigma_rises_with_disagreement():
    df = load_power_ratings("tests/fixtures/power_ratings.csv")
    sig = team_sigma(df)
    assert (sig > 0).all()
