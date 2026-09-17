import numpy as np
from scipy.stats import norm

HFA = 2.0
SCALE = 13.5


def fit_hfa_scale(home_margin):
    """Gaussian MLE of home-field advantage and margin scale.

    `home_margin` is home_score - away_score for completed regular-season
    games. Production freezes the fitted NFL values as HFA/SCALE; this is
    the offline fit, not a live dependency.
    """
    m = np.asarray(home_margin, dtype=float)
    return float(m.mean()), float(m.std(ddof=1))


def win_prob(sh, sa, hfa=HFA, scale=SCALE):
    return norm.cdf((np.asarray(sh) - np.asarray(sa) + hfa) / scale)

def expected_wins(strengths, home_idx, away_idx, hfa=HFA, scale=SCALE):
    strengths = np.asarray(strengths, dtype=float)
    p_home = win_prob(strengths[home_idx], strengths[away_idx], hfa, scale)
    ew = np.zeros(len(strengths))
    np.add.at(ew, home_idx, p_home)
    np.add.at(ew, away_idx, 1.0 - p_home)
    return ew
