import numpy as np
from scipy.stats import norm
from .game import HFA, SCALE

def simulate(strengths, sigma, home_idx, away_idx, n_seasons, *,
             hfa=HFA, scale=SCALE, tie_base=0.0, rng):
    strengths = np.asarray(strengths, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    n_teams = strengths.size
    # one true-strength draw per season per team (preseason uncertainty)
    S = strengths[None, :] + rng.standard_normal((n_seasons, n_teams)) * sigma[None, :]
    wins = np.zeros((n_seasons, n_teams), dtype=np.int16)
    for h, a in zip(home_idx, away_idx):
        z = (S[:, h] - S[:, a] + hfa) / scale
        p_home = norm.cdf(z)
        tie_p = tie_base * np.exp(-0.5 * z * z) if tie_base > 0 else 0.0
        u = rng.random(n_seasons)          # decides tie
        r = rng.random(n_seasons)          # decides winner if not tie
        tie = u < tie_p
        home_win = (~tie) & (r < p_home)
        away_win = (~tie) & (~(r < p_home))
        wins[:, h] += home_win
        wins[:, a] += away_win
    return wins
