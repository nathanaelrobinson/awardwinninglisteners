import numpy as np
from scipy.stats import norm

HFA = 2.0
SCALE = 13.5

def win_prob(sh, sa, hfa=HFA, scale=SCALE):
    return norm.cdf((np.asarray(sh) - np.asarray(sa) + hfa) / scale)

def expected_wins(strengths, home_idx, away_idx, hfa=HFA, scale=SCALE):
    strengths = np.asarray(strengths, dtype=float)
    p_home = win_prob(strengths[home_idx], strengths[away_idx], hfa, scale)
    ew = np.zeros(len(strengths))
    np.add.at(ew, home_idx, p_home)
    np.add.at(ew, away_idx, 1.0 - p_home)
    return ew
