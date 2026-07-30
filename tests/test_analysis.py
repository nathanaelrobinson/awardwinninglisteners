import numpy as np
from winspool.analysis import team_attributes, win_correlation, strength_of_schedule

def test_attributes_basic():
    wins = np.array([[12, 4], [13, 5], [11, 6]], dtype=np.int16)
    attrs = {a["team"]: a for a in team_attributes(wins)}
    assert attrs[0]["mean"] == 12.0
    assert attrs[0]["ceiling"] > attrs[1]["ceiling"]   # team 0 hits >=12 often
    assert attrs[1]["floor"] > attrs[0]["floor"]       # team 1 low-win often

def test_division_rivals_negatively_correlated():
    # teams that only play each other are perfectly anti-correlated in wins
    from winspool.sim import simulate
    home = np.array([0, 1]); away = np.array([1, 0])
    wins = simulate(np.zeros(2), np.zeros(2), home, away, 5000, hfa=0.0,
                    rng=np.random.default_rng(0))
    c = win_correlation(wins)
    assert c[0, 1] < 0

def test_sos_higher_for_tougher_schedule():
    strengths = np.array([0.0, 5.0, -5.0])
    # team 0 plays team1(+5) twice; team 2 plays team? make team0 face strong
    home = np.array([0, 0]); away = np.array([1, 1])
    sos = strength_of_schedule(strengths, home, away)
    assert sos[0] == 5.0
