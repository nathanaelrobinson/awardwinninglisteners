"""Standalone market view over Kalshi-implied per-team win distributions.

Independent of the correlated season sim: this reads the PMF artifact and reports
the market's implied line, mean, and SD (confidence), and can draw season win
totals i.i.d. per team. Explicitly NOT the pick decision engine (no schedule
correlation) — a pure market lens."""
import numpy as np
import pandas as pd
from .fetch.kalshi import pmf_mean, pmf_sd, pmf_line


def load_distributions(path):
    df = pd.read_csv(path).set_index("team")
    cols = [f"p{k}" for k in range(18)]
    codes = list(df.index)
    mat = df[cols].to_numpy(dtype=float)
    return codes, mat


def summarize(codes, pmf_matrix):
    out = []
    for code, pmf in zip(codes, pmf_matrix):
        out.append({"team": code, "line": pmf_line(pmf),
                    "mean": pmf_mean(pmf), "sd": pmf_sd(pmf)})
    return out


def sample_independent(pmf_matrix, n_seasons, rng):
    n_teams = pmf_matrix.shape[0]
    wins = np.zeros((n_seasons, n_teams), dtype=np.int16)
    outcomes = np.arange(pmf_matrix.shape[1])
    for t in range(n_teams):
        wins[:, t] = rng.choice(outcomes, size=n_seasons, p=pmf_matrix[t])
    return wins
