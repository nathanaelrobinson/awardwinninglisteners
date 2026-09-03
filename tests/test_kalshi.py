import json
import numpy as np
import pytest
from winspool.fetch.kalshi import ladder_to_pmf, pmf_mean, pmf_sd, pmf_line


def _markets(entries):
    # entries: list of (floor_strike, yes_bid, yes_ask) in dollars
    return [{"floor_strike": k, "yes_bid_dollars": str(b),
             "yes_ask_dollars": str(a), "last_price_dollars": None}
            for k, b, a in entries]


def test_ladder_to_pmf_is_normalized_and_nonnegative():
    # simple 3-rung ladder: P(>=1)=1.0, P(>=2)=0.5, P(>=3)=0.0
    pmf = ladder_to_pmf(_markets([(1, 1.0, 1.0), (2, 0.5, 0.5), (3, 0.0, 0.0)]))
    assert pmf.shape == (18,)
    assert pytest.approx(pmf.sum(), abs=1e-9) == 1.0
    assert (pmf >= 0).all()
    # P(W=1) = P>=1 - P>=2 = 0.5 ; P(W=2) = 0.5 ; rest 0
    assert pytest.approx(pmf[1], abs=1e-9) == 0.5
    assert pytest.approx(pmf[2], abs=1e-9) == 0.5


def test_ladder_to_pmf_enforces_monotonic_cdf():
    # deliberately non-monotone: P(>=2) printed HIGHER than P(>=1) (bid/ask noise)
    pmf = ladder_to_pmf(_markets([(1, 0.6, 0.6), (2, 0.8, 0.8), (3, 0.1, 0.1)]))
    assert (pmf >= 0).all()
    assert pytest.approx(pmf.sum(), abs=1e-9) == 1.0


def test_pmf_moments_and_line():
    pmf = ladder_to_pmf(_markets([(1, 1.0, 1.0), (2, 0.5, 0.5), (3, 0.0, 0.0)]))
    assert pytest.approx(pmf_mean(pmf), abs=1e-9) == 1.5   # 0.5*1 + 0.5*2
    assert pmf_sd(pmf) > 0
    # survival P(>=2)=0.5 exactly, so the 0.5-crossing O/U line resolves to 2.0
    assert pytest.approx(pmf_line(pmf), abs=1e-9) == 2.0
