import numpy as np
from winspool.game import win_prob, expected_wins, HFA, SCALE

def test_even_matchup_on_neutral_is_half():
    assert abs(win_prob(0.0, 0.0, hfa=0.0) - 0.5) < 1e-9

def test_seven_point_favorite_neutral_about_seventy():
    p = win_prob(7.0, 0.0, hfa=0.0)
    assert 0.66 < p < 0.72

def test_home_field_helps_home_team():
    assert win_prob(0.0, 0.0, hfa=HFA) > 0.5

def test_expected_wins_sums_to_total_games():
    # 2-team, 2-game fixture: each game contributes exactly 1 win somewhere
    home = np.array([0, 1]); away = np.array([1, 0])
    ew = expected_wins(np.zeros(2), home, away, hfa=0.0)
    assert abs(ew.sum() - 2.0) < 1e-9
