import numpy as np

# d(expected wins)/d(strength) at a neutral matchup over a 17-game season:
#   17 * (1/SCALE) * pdf(0) = 17 * (1/13.5) * 0.3989 ≈ 0.502 wins per point.
WINS_PER_POINT = 0.502

def strength_from_totals(win_totals):
    totals = np.asarray(win_totals, dtype=float)
    centered = totals - totals.mean()
    return centered / WINS_PER_POINT

from scipy.optimize import brentq
from .teams import TEAMS, TEAM_INDEX, N_TEAMS
from .game import expected_wins, HFA, SCALE

def power_strength(power_df):
    """Mean of centered source columns. Averages ALL numeric columns present,
    so adding a new Elo/power source needs no code change."""
    cols = list(power_df.columns)
    s = np.zeros(N_TEAMS)
    for col in cols:
        col_arr = np.zeros(N_TEAMS)
        for code, val in power_df[col].items():
            col_arr[TEAM_INDEX[code]] = float(val)
        s += col_arr - col_arr.mean()
    return s / len(cols)

def team_sigma(power_df, base=5.0, disagreement_weight=1.0):
    """Preseason SD per team = base + weight * SD across the team's source values."""
    sig = np.full(N_TEAMS, base)
    for code, row in power_df.iterrows():
        sig[TEAM_INDEX[code]] = base + disagreement_weight * float(
            np.std(row.to_numpy(dtype=float)))
    return sig

def _team_games(home_idx, away_idx, n_teams):
    """For each team: list of (opponent_idx, is_home)."""
    games = {t: [] for t in range(n_teams)}
    for h, a in zip(home_idx, away_idx):
        games[h].append((a, True))
        games[a].append((h, False))
    return games

def backout_market(win_totals, home_idx, away_idx, *, hfa=HFA, scale=SCALE,
                   iters=60, tol=1e-4):
    from scipy.stats import norm
    totals = np.asarray(win_totals, dtype=float)
    n_teams = totals.size
    s = np.zeros(n_teams)
    games = _team_games(home_idx, away_idx, n_teams)

    def team_ew(t, st):
        ew = 0.0
        for opp, is_home in games[t]:
            d = (st - s[opp] + (hfa if is_home else -hfa)) / scale
            ew += norm.cdf(d)
        return ew

    for _ in range(iters):
        max_delta = 0.0
        for t in range(n_teams):
            if not games[t]:
                continue
            target = totals[t]
            f = lambda st: team_ew(t, st) - target
            lo, hi = -40.0, 40.0
            if f(lo) > 0 or f(hi) < 0:
                continue  # target unreachable given opponents; leave as is
            new_s = brentq(f, lo, hi, xtol=1e-4)
            max_delta = max(max_delta, abs(new_s - s[t]))
            s[t] = new_s
        if max_delta < tol:
            break
    return s - s.mean()

def blend(market, power, w=0.65):
    market = np.asarray(market) - np.asarray(market).mean()
    power = np.asarray(power) - np.asarray(power).mean()
    return w * market + (1.0 - w) * power

def ensemble(source_strengths, base_sigma=4.0, spread_k=1.0):
    """Combine independent source strength estimates (each a length-32 points
    vector — Vegas, FPI, nfelo, Clay, …) WITHOUT anchoring on any one.

    Returns (strength, sigma):
      - strength = equal-weight mean across sources (each source mean-centered
        first so no source biases the overall level).
      - sigma = base_sigma + spread_k * (cross-source std per team). Teams the
        sources DISAGREE on get a wider preseason draw → fatter win-total tails
        → they read as the high-ceiling, high-variance picks that matter in a
        winner-take-all pool. Disagreement, not consensus, drives the variance.
    """
    names = list(source_strengths)
    raw = np.vstack([np.asarray(source_strengths[n], dtype=float) for n in names])
    means = raw.mean(axis=1, keepdims=True)
    stds = raw.std(axis=1, keepdims=True)
    # Standardize each source to z-scores so sources on different native scales
    # (FPI points vs Elo-derived vs Clay-derived) each vote EQUALLY on the
    # ranking — otherwise the widest-scale source silently dominates and inflates
    # apparent disagreement.
    scale = float(np.mean(stds[stds > 0])) if np.any(stds > 0) else 1.0
    z = np.where(stds > 0, (raw - means) / np.where(stds > 0, stds, 1.0), 0.0)
    strength = z.mean(axis=0) * scale             # consensus ranking, rescaled to points
    spread = z.std(axis=0)                         # scale-free cross-source disagreement
    sigma = base_sigma + spread_k * spread * scale
    return strength, sigma

def to_common_scale(source_strengths):
    """Each source standardized then rescaled to one common points scale, as a
    (n_sources, n_teams) matrix — the set of comparable 'model worlds' the
    mixture sim samples from. Same standardization ensemble() uses."""
    names = list(source_strengths)
    raw = np.vstack([np.asarray(source_strengths[n], dtype=float) for n in names])
    means = raw.mean(axis=1, keepdims=True)
    stds = raw.std(axis=1, keepdims=True)
    scale = float(np.mean(stds[stds > 0])) if np.any(stds > 0) else 1.0
    z = np.where(stds > 0, (raw - means) / np.where(stds > 0, stds, 1.0), 0.0)
    return z * scale


def calibrate_sigma(strength, home_idx, away_idx, target_sd, *,
                    sigma_ref=4.5, sigma_max=12.0, n_seasons=8000,
                    tie_base=0.003, seed=0):
    """Per-team strength-space season-noise sigma (points) whose simulated
    total-win SD matches each team's target win-SD.

    Self-calibrated from two reference sims of THIS schedule (no hardcoded
    wins-per-point): win-variance is ~quadratic in sigma, so a sim at sigma=0
    and one at sigma=sigma_ref fix the per-team slope exactly. Then solve for the
    sigma that hits target_sd**2. target_sd entries that are NaN (no market data)
    fall back to sigma_ref. Result is clipped to [0, sigma_max]."""
    from .sim import simulate
    strength = np.asarray(strength, dtype=float)
    target_sd = np.asarray(target_sd, dtype=float)
    n = strength.size
    base = simulate(strength, np.zeros(n), home_idx, away_idx, n_seasons,
                    tie_base=tie_base, rng=np.random.default_rng(seed))
    ref = simulate(strength, np.full(n, sigma_ref), home_idx, away_idx, n_seasons,
                   tie_base=tie_base, rng=np.random.default_rng(seed + 1))
    base_var = base.var(axis=0)
    ref_var = ref.var(axis=0)
    slope2 = np.maximum((ref_var - base_var) / (sigma_ref ** 2), 1e-9)
    excess = np.maximum(target_sd ** 2 - base_var, 0.0)
    sigma = np.sqrt(excess / slope2)
    sigma = np.clip(sigma, 0.0, sigma_max)
    sigma = np.where(np.isnan(target_sd), sigma_ref, sigma)
    return sigma
