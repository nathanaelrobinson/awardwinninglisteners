import numpy as np
import pytest
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


def _one_world(n_teams=2):
    # single "world": equal strengths, a 2-team home/away pair
    sm = np.zeros((1, n_teams))
    home = np.array([0, 1]); away = np.array([1, 0])
    return sm, home, away


def _sigma_test_world(games=12):
    # 3 teams, one world, equal strengths; teams 0 and 1 each play team 2 `games`
    # times. NOT a closed 2-team system (that forces equal variance) — teams 0 and
    # 1 never play each other, so their win-SDs are free to differ by their sigma.
    sm = np.zeros((1, 3))
    home, away = [], []
    for _ in range(games):
        home += [0, 1]; away += [2, 2]
    return sm, np.array(home), np.array(away)


def test_mixture_rejects_wrong_length_sigma():
    sm, home, away = _one_world(2)
    with pytest.raises(ValueError, match="n_teams"):
        simulate_mixture(sm, home, away, 100,
                         base_sigma=np.array([1.0, 2.0, 3.0]),   # len 3 != 2 teams
                         hfa=0.0, rng=np.random.default_rng(0))


def test_mixture_per_team_sigma_widens_only_that_team():
    sm, home, away = _sigma_test_world()
    w = simulate_mixture(sm, home, away, 20000,
                         base_sigma=np.array([0.1, 8.0, 0.1]),   # team1 far noisier
                         hfa=0.0, tie_base=0.0, rng=np.random.default_rng(3))
    assert w[:, 1].std() > w[:, 0].std() + 0.5


def test_simulate_mixture_weights_select_sources():
    # Source 0: team 0 is +20 points; source 1: team 1 is +20 points.
    src = np.zeros((2, 32))
    src[0, 0] = 20.0
    src[1, 1] = 20.0
    home = np.array([0]); away = np.array([1])
    rng = np.random.default_rng(1)
    w = simulate_mixture(src, home, away, 4000, base_sigma=0.0, tie_base=0.0,
                         weights=np.array([1.0, 0.0]), rng=rng)
    # Only source 0 is ever sampled, so team 0 (home, +22 with HFA) wins ~95%.
    assert w[:, 0].mean() > 0.9
    rng = np.random.default_rng(1)
    w = simulate_mixture(src, home, away, 4000, base_sigma=0.0, tie_base=0.0,
                         weights=np.array([0.0, 1.0]), rng=rng)
    assert w[:, 0].mean() < 0.15


def test_simulate_mixture_weights_length_checked():
    src = np.zeros((2, 32))
    with pytest.raises(ValueError):
        simulate_mixture(src, np.array([0]), np.array([1]), 10,
                         weights=np.array([1.0]), rng=np.random.default_rng(0))
