import numpy as np
from winspool.sim import simulate, simulate_mixture

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


def test_simulate_mixture_shape_and_determinism():
    home = np.array([0, 1]); away = np.array([1, 0])
    mat = np.array([[7.0, -7.0], [-7.0, 7.0]])   # two opposite "worlds"
    a = simulate_mixture(mat, home, away, 20000, base_sigma=0.0, hfa=0.0,
                         rng=np.random.default_rng(1))
    b = simulate_mixture(mat, home, away, 20000, base_sigma=0.0, hfa=0.0,
                         rng=np.random.default_rng(1))
    assert a.shape == (20000, 2) and a.dtype == np.int16
    assert np.array_equal(a, b)

def test_simulate_mixture_is_bimodal_on_disagreement():
    # team 0 dominant in world 0, terrible in world 1 -> bimodal win total
    home = np.array([0, 1]); away = np.array([1, 0])
    mat = np.array([[14.0, -14.0], [-14.0, 14.0]])
    w = simulate_mixture(mat, home, away, 20000, base_sigma=0.0, hfa=0.0,
                         rng=np.random.default_rng(2))
    t0 = w[:, 0]
    frac_mid = np.mean(t0 == 1)
    frac_ext = np.mean((t0 == 0) | (t0 == 2))
    assert frac_ext > frac_mid   # mass piles at the extremes, not the middle
