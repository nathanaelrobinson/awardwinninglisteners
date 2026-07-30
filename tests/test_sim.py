import numpy as np
from winspool.sim import simulate

def _two_team(rng, n=20000, sig=0.0):
    # team 0 is +14 pts stronger; play each other twice, no HFA
    home = np.array([0, 1]); away = np.array([1, 0])
    s = np.array([7.0, -7.0]); sigma = np.array([sig, sig])
    return simulate(s, sigma, home, away, n, hfa=0.0, rng=rng)

def test_shape_and_dtype():
    w = _two_team(np.random.default_rng(1))
    assert w.shape == (20000, 2) and w.dtype == np.int16

def test_stronger_team_wins_more():
    w = _two_team(np.random.default_rng(2))
    # 14-pt gap over 2 games -> stronger team averages well above 1 win
    assert w[:, 0].mean() > w[:, 1].mean()
    assert 1.2 < w[:, 0].mean() < 2.0

def test_deterministic_under_seed():
    a = _two_team(np.random.default_rng(7))
    b = _two_team(np.random.default_rng(7))
    assert np.array_equal(a, b)

def test_sigma_widens_spread():
    narrow = _two_team(np.random.default_rng(3), sig=0.0)
    wide = _two_team(np.random.default_rng(3), sig=8.0)
    assert wide[:, 0].std() >= narrow[:, 0].std()

def test_ties_reduce_total_wins():
    home = np.array([0, 1]); away = np.array([1, 0])
    s = np.zeros(2); sigma = np.zeros(2)
    no_tie = simulate(s, sigma, home, away, 50000, hfa=0.0, tie_base=0.0,
                      rng=np.random.default_rng(4))
    with_tie = simulate(s, sigma, home, away, 50000, hfa=0.0, tie_base=0.05,
                        rng=np.random.default_rng(4))
    assert with_tie.sum() < no_tie.sum()
