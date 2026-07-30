import numpy as np

# d(expected wins)/d(strength) at a neutral matchup over a 17-game season:
#   17 * (1/SCALE) * pdf(0) = 17 * (1/13.5) * 0.3989 ≈ 0.502 wins per point.
WINS_PER_POINT = 0.502

def strength_from_totals(win_totals):
    totals = np.asarray(win_totals, dtype=float)
    centered = totals - totals.mean()
    return centered / WINS_PER_POINT
