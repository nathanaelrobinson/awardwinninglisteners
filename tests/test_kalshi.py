import json
import numpy as np
import pandas as pd
import pytest
from winspool.fetch.kalshi import ladder_to_pmf, pmf_mean, pmf_sd, pmf_line, team_from_event_ticker, events_to_distributions, write_distributions


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


def test_team_from_event_ticker_strips_season_and_maps_aliases():
    assert team_from_event_ticker("KXNFLWINS-27BUF") == "BUF"
    assert team_from_event_ticker("KXNFLWINS-27LAR") == "LA"    # Kalshi LAR -> our LA
    assert team_from_event_ticker("KXNFLWINS-27JAC") == "JAX"   # Kalshi JAC -> our JAX
    assert team_from_event_ticker("KXNFLWINS-27ZZZ") is None


def test_events_to_distributions_from_fixture():
    events = json.load(open("tests/fixtures/kalshi_kxnflwins.json"))["events"]
    dists = events_to_distributions(events)
    assert set(dists) == {"BUF", "ARI"}
    for code, pmf in dists.items():
        assert pmf.shape == (18,)
        assert pytest.approx(pmf.sum(), abs=1e-6) == 1.0
    # sanity: BUF (a good team) has a higher implied mean than ARI (a weak team)
    assert pmf_mean(dists["BUF"]) > pmf_mean(dists["ARI"])


def test_write_distributions_roundtrip(tmp_path):
    dists = {"BUF": np.full(18, 1 / 18), "ARI": np.eye(18)[4]}
    path = write_distributions(dists, str(tmp_path))
    df = pd.read_csv(path).set_index("team")
    assert list(df.columns) == [f"p{k}" for k in range(18)]
    assert pytest.approx(df.loc["BUF"].sum(), abs=1e-9) == 1.0
    assert pytest.approx(df.loc["ARI", "p4"], abs=1e-9) == 1.0


def test_events_to_distributions_omits_thin_ladder():
    # ARI: all rungs unpriced (bid/ask/last all None) -> 0 priced rungs, omitted
    unpriced = [{"floor_strike": k, "yes_bid_dollars": None,
                 "yes_ask_dollars": None, "last_price_dollars": None}
                for k in range(1, 4)]
    # BUF: only 2 priced rungs -> below MIN_PRICED_RUNGS, omitted
    thin = _markets([(1, 0.9, 0.9), (2, 0.5, 0.5)]) + [
        {"floor_strike": 3, "yes_bid_dollars": None,
         "yes_ask_dollars": None, "last_price_dollars": None}
    ]
    # KC: 3 priced rungs -> meets MIN_PRICED_RUNGS, kept
    healthy = _markets([(1, 1.0, 1.0), (2, 0.5, 0.5), (3, 0.0, 0.0)])
    events = [
        {"event_ticker": "KXNFLWINS-27ARI", "markets": unpriced},
        {"event_ticker": "KXNFLWINS-27BUF", "markets": thin},
        {"event_ticker": "KXNFLWINS-27KC", "markets": healthy},
    ]
    dists = events_to_distributions(events)
    assert "ARI" not in dists
    assert "BUF" not in dists
    assert "KC" in dists
    assert pytest.approx(dists["KC"].sum(), abs=1e-9) == 1.0


def test_ladder_to_pmf_skips_market_missing_floor_strike():
    markets = _markets([(1, 1.0, 1.0), (2, 0.5, 0.5), (3, 0.0, 0.0)])
    markets.append({"yes_bid_dollars": "0.2", "yes_ask_dollars": "0.2",
                     "last_price_dollars": None})  # no floor_strike key
    pmf = ladder_to_pmf(markets)  # must not raise
    assert pmf.shape == (18,)
    assert pytest.approx(pmf.sum(), abs=1e-9) == 1.0


@pytest.mark.network
def test_kalshi_totals_live_smoke():
    from winspool.fetch.kalshi import kalshi_totals
    totals = kalshi_totals()
    assert len(totals) == 32
    assert all(0.0 <= v <= 17.0 for v in totals.values())
