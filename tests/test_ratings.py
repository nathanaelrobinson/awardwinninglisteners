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

def test_ensemble_averages_and_widens_on_disagreement():
    from winspool.ratings import ensemble
    # team0: sources disagree (+2 vs 0); team1: agree; team2: disagree (-2 vs 0)
    sources = {"a": np.array([2.0, 0.0, -2.0]), "b": np.array([0.0, 0.0, 0.0])}
    strength, sigma = ensemble(sources, base_sigma=4.0, spread_k=1.0)
    # each source is centered first, then averaged
    assert np.allclose(strength, [1.0, 0.0, -1.0])
    # disagreement teams get a larger sigma than the agreed team
    assert sigma[0] > sigma[1] and sigma[2] > sigma[1]
    assert np.isclose(sigma[1], 4.0)  # no disagreement -> just base

def test_ensemble_standardizes_so_scale_doesnt_dominate():
    from winspool.ratings import ensemble
    # two sources with the SAME ranking but 10x different scale should be read
    # as agreement (low sigma), not disagreement — proves standardization.
    big = np.array([10.0, 0.0, -10.0])
    small = np.array([1.0, 0.0, -1.0])
    strength, sigma = ensemble({"big": big, "small": small}, base_sigma=4.0, spread_k=1.0)
    assert np.allclose(sigma, 4.0, atol=0.2)          # agreement -> ~base sigma
    assert strength[0] > strength[1] > strength[2]    # ranking preserved
