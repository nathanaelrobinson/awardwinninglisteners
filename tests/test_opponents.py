import numpy as np
from winspool.draft import DraftState
from winspool.opponents import chalk_power, entropy, greedy_self

def test_chalk_takes_strongest_available():
    strengths = np.array([1.0, 9.0, 3.0])
    pol = chalk_power(strengths)
    st = DraftState(my_player=1, n_teams=3)
    assert pol(st, 1, np.random.default_rng(0)) == 1  # team 1 strongest

def test_chalk_skips_taken():
    strengths = np.array([1.0, 9.0, 3.0])
    st = DraftState(my_player=1, n_teams=3); st.apply_pick(1)  # strongest gone
    assert chalk_power(strengths)(st, 2, np.random.default_rng(0)) == 2

def test_entropy_returns_available_and_is_seed_deterministic():
    strengths = np.array([1.0, 2.0, 3.0, 4.0])
    pol = entropy(strengths, temperature=8.0)
    st = DraftState(my_player=1, n_teams=4)
    a = pol(st, 1, np.random.default_rng(5))
    b = pol(st, 1, np.random.default_rng(5))
    assert a == b and a in st.board()

def test_low_temperature_is_chalky():
    strengths = np.array([0.0, 0.0, 0.0, 20.0])
    pol = entropy(strengths, temperature=0.5)
    st = DraftState(my_player=1, n_teams=4)
    picks = [pol(st, 1, np.random.default_rng(s)) for s in range(50)]
    assert picks.count(3) > 40  # team 3 dominates at low temp
