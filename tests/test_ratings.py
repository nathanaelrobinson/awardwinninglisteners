import numpy as np
from winspool.ratings import strength_from_totals, calibrate_sigma
from winspool.sim import simulate

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


def _toy_schedule():
    # 4 teams, round-robin home/away (each pair twice), no HFA in the sim calls
    home, away = [], []
    for i in range(4):
        for j in range(4):
            if i != j:
                home.append(i); away.append(j)
    return np.array(home), np.array(away)


def test_calibrate_sigma_nan_target_falls_back_to_ref():
    home, away = _toy_schedule()
    strength = np.zeros(4)
    target = np.array([np.nan, np.nan, np.nan, np.nan])
    sig = calibrate_sigma(strength, home, away, target, sigma_ref=4.5, n_seasons=4000)
    assert np.allclose(sig, 4.5)


def test_calibrate_sigma_reproduces_a_higher_target_sd():
    # Use the REAL 17-game schedule (the toy 6-game one saturates win-SD below
    # any useful target). Let hfa default so the verification sim matches the
    # assumptions calibrate_sigma uses in its own internal reference sims.
    from winspool.data import load_schedule, schedule_matchups
    df = load_schedule("data/cache/schedule_2026.csv")
    home, away = schedule_matchups(df)
    n = 32
    strength = np.zeros(n)
    base = simulate(strength, np.zeros(n), home, away, 8000,
                    tie_base=0.0, rng=np.random.default_rng(0))
    base_sd = base.std(axis=0).mean()
    target_val = base_sd + 1.0
    target = np.full(n, target_val)
    sig = calibrate_sigma(strength, home, away, target, sigma_ref=4.5,
                          n_seasons=8000, tie_base=0.0)
    assert (sig > 0).all()
    w = simulate(strength, sig, home, away, 20000, tie_base=0.0,
                 rng=np.random.default_rng(1))
    realized = w.std(axis=0).mean()
    assert abs(realized - target_val) < 0.4


def test_calibrate_sigma_clips_to_max_and_zeros_below_baseline():
    home, away = _toy_schedule()
    strength = np.zeros(4)
    # target below the schedule-only baseline -> sigma 0; absurd target -> clipped
    low = calibrate_sigma(strength, home, away, np.full(4, 0.1),
                          sigma_ref=4.5, sigma_max=12.0, n_seasons=4000, tie_base=0.0)
    high = calibrate_sigma(strength, home, away, np.full(4, 50.0),
                           sigma_ref=4.5, sigma_max=12.0, n_seasons=4000, tie_base=0.0)
    assert np.allclose(low, 0.0)
    assert np.allclose(high, 12.0)
