import numpy as np
import pandas as pd
import pytest
from winspool.market import load_distributions, summarize, sample_independent


def _write_csv(tmp_path):
    cols = [f"p{k}" for k in range(18)]
    buf = np.zeros(18); buf[11] = 1.0            # BUF always 11 wins
    ari = np.zeros(18); ari[4] = 1.0             # ARI always 4 wins
    df = pd.DataFrame([{"team": "BUF", **dict(zip(cols, buf))},
                       {"team": "ARI", **dict(zip(cols, ari))}])
    p = tmp_path / "kalshi_distributions.csv"
    df.to_csv(p, index=False)
    return str(p)


def test_load_and_summarize(tmp_path):
    codes, mat = load_distributions(_write_csv(tmp_path))
    assert mat.shape == (2, 18)
    s = {d["team"]: d for d in summarize(codes, mat)}
    assert pytest.approx(s["BUF"]["mean"], abs=1e-9) == 11.0
    assert pytest.approx(s["ARI"]["mean"], abs=1e-9) == 4.0
    assert s["BUF"]["sd"] == 0.0                 # degenerate PMF -> zero spread


def test_sample_independent_recovers_means(tmp_path):
    codes, mat = load_distributions(_write_csv(tmp_path))
    rng = np.random.default_rng(0)
    draws = sample_independent(mat, 5000, rng)
    assert draws.shape == (5000, 2)
    assert draws[:, codes.index("BUF")].mean() == 11.0   # degenerate -> exact
