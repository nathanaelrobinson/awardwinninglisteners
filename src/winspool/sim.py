import numpy as np
from scipy.stats import norm
from .game import HFA, SCALE


def _play(S, home_idx, away_idx, *, hfa, scale, tie_base, rng):
    """Play every scheduled game given a per-season team-strength matrix
    S (n_seasons, n_teams). Returns win totals (n_seasons, n_teams) int16."""
    n_seasons = S.shape[0]
    wins = np.zeros(S.shape, dtype=np.int16)
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


def simulate(strengths, sigma, home_idx, away_idx, n_seasons, *,
             hfa=HFA, scale=SCALE, tie_base=0.0, rng):
    """Single-model Monte Carlo: each season draws every team's strength from
    Normal(strengths, sigma), then plays the schedule."""
    strengths = np.asarray(strengths, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    n_teams = strengths.size
    S = strengths[None, :] + rng.standard_normal((n_seasons, n_teams)) * sigma[None, :]
    return _play(S, home_idx, away_idx, hfa=hfa, scale=scale, tie_base=tie_base, rng=rng)


def simulate_mixture(source_matrix, home_idx, away_idx, n_seasons, *,
                     base_sigma=4.5, hfa=HFA, scale=SCALE, tie_base=0.0,
                     weights=None, rng):
    """Mixture-of-models Monte Carlo. `source_matrix` is (n_sources, n_teams),
    one strength vector per rating source (all on a common scale). Each season
    samples ONE source ("which model is right this year") and draws team
    strengths around that world with Normal(0, base_sigma) season noise.

    `base_sigma` may be a scalar or a per-team vector (length n_teams) — the
    latter lets each team's season noise be calibrated independently (see
    `ratings.calibrate_sigma`).

    `weights` (optional, length n_sources, sums to 1) sets how often each
    source is the sampled world; None = uniform.

    Teams the sources AGREE on stay unimodal; teams they DISAGREE on become
    genuinely multimodal (fat / bimodal tails) — the honest picture of model
    uncertainty, and where winner-take-all upside lives."""
    source_matrix = np.asarray(source_matrix, dtype=float)
    n_sources, n_teams = source_matrix.shape
    if weights is None:
        picks = rng.integers(0, n_sources, size=n_seasons)
    else:
        weights = np.asarray(weights, dtype=float)
        if weights.size != n_sources:
            raise ValueError(f"weights length {weights.size} != n_sources {n_sources}")
        picks = rng.choice(n_sources, size=n_seasons, p=weights / weights.sum())
    base_sigma = np.asarray(base_sigma, dtype=float)
    if base_sigma.ndim == 1 and base_sigma.size != n_teams:
        raise ValueError(
            f"base_sigma vector length {base_sigma.size} != n_teams {n_teams}")
    S = source_matrix[picks] + rng.standard_normal((n_seasons, n_teams)) * base_sigma
    return _play(S, home_idx, away_idx, hfa=hfa, scale=scale, tie_base=tie_base, rng=rng)
