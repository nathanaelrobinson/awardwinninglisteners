"""Kalshi KXNFLWINS market source: per-team implied win distributions.

Pure functions (ladder -> PMF, moments) are unit-tested against a fixture.
The network fetchers hit Kalshi's PUBLIC endpoint (no auth) and are smoke-tested.
"""
import os
import re
import requests
import numpy as np
import pandas as pd
from ..teams import resolve

MAX_WINS = 17
MIN_PRICED_RUNGS = 3

_KALSHI_FIX = {"LAR": "LA", "JAC": "JAX"}

SERIES = "KXNFLWINS"
BASE = "https://external-api.kalshi.com/trade-api/v2"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
TIMEOUT = 30


def _price(m):
    """Usable yes-price for a rung: bid/ask mid when present, else last."""
    def f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    yb, ya, last = f(m.get("yes_bid_dollars")), f(m.get("yes_ask_dollars")), f(m.get("last_price_dollars"))
    if yb is not None and ya is not None:
        return (yb + ya) / 2.0
    return last


def n_priced_rungs(markets):
    """Count rungs with both a valid floor_strike (0..17) and a usable price."""
    n = 0
    for m in markets:
        strike = m.get("floor_strike")
        if strike is None:
            continue
        try:
            k = int(strike)
        except (TypeError, ValueError):
            continue
        if 0 <= k <= MAX_WINS and _price(m) is not None:
            n += 1
    return n


def ladder_to_pmf(markets):
    """A team's 17-rung ladder -> normalized PMF over wins 0..17 (length 18).

    floor_strike=k prices P(W>=k). We build the survival curve P(W>=k), force it
    non-increasing (cummin) to remove bid/ask crossing noise, then difference it
    into a PMF, clip negatives, and renormalize (removes vig/underround)."""
    surv = np.full(MAX_WINS + 1, np.nan)   # surv[k] = P(W >= k)
    surv[0] = 1.0
    for m in markets:
        strike = m.get("floor_strike")
        if strike is None:
            continue
        k = int(strike)
        p = _price(m)
        if p is not None and 0 <= k <= MAX_WINS:
            surv[k] = p
    # fill gaps by carrying the last known survival value forward
    last = 1.0
    for k in range(MAX_WINS + 1):
        if np.isnan(surv[k]):
            surv[k] = last
        last = surv[k]
    surv = np.minimum.accumulate(surv)     # enforce non-increasing survival
    pmf = np.zeros(MAX_WINS + 1)
    for k in range(MAX_WINS + 1):
        upper = surv[k + 1] if k < MAX_WINS else 0.0
        pmf[k] = max(surv[k] - upper, 0.0)
    total = pmf.sum()
    return pmf / total if total > 0 else pmf


def pmf_mean(pmf):
    k = np.arange(len(pmf))
    return float((k * pmf).sum())


def pmf_sd(pmf):
    k = np.arange(len(pmf))
    mean = float((k * pmf).sum())
    var = float(((k - mean) ** 2 * pmf).sum())
    return float(np.sqrt(max(var, 0.0)))


def pmf_line(pmf):
    """Continuous O/U line: interpolated k where the survival CDF crosses 0.5."""
    surv = 1.0 - np.cumsum(pmf) + pmf      # surv[k] = P(W >= k)
    for k in range(1, len(pmf)):
        if surv[k - 1] >= 0.5 >= surv[k] and surv[k - 1] != surv[k]:
            return float((k - 1) + (surv[k - 1] - 0.5) / (surv[k - 1] - surv[k]))
    return pmf_mean(pmf)


def team_from_event_ticker(ticker):
    raw = re.sub(r"^\d+", "", ticker.split("-")[-1])   # "27BUF" -> "BUF"
    return _KALSHI_FIX.get(raw) or resolve(raw)


def events_to_distributions(events):
    out = {}
    for e in events:
        code = team_from_event_ticker(e.get("event_ticker", ""))
        markets = e.get("markets", [])
        if not code or not markets:
            continue
        n = n_priced_rungs(markets)
        if n < MIN_PRICED_RUNGS:
            print(f"  WARNING: kalshi {code}: only {n} priced rungs (<{MIN_PRICED_RUNGS}), omitting")
            continue
        pmf = ladder_to_pmf(markets)
        # Plain floats, not the ndarray `ladder_to_pmf` returns: this dict is
        # stored verbatim as a rating doc, and `json.dumps` cannot serialize an
        # ndarray. Converting here, at the boundary where a computed array
        # becomes a document, keeps every consumer JSON-safe — the numeric
        # consumers all go through `np.asarray`, which is indifferent.
        out[code] = [float(x) for x in pmf]
    return out


def fetch_events():
    r = requests.get(f"{BASE}/events", headers=HEADERS, timeout=TIMEOUT,
                     params={"series_ticker": SERIES, "with_nested_markets": "true", "limit": 200})
    r.raise_for_status()
    return r.json().get("events", [])


def kalshi_distributions():
    return events_to_distributions(fetch_events())


def kalshi_totals():
    return {code: pmf_line(pmf) for code, pmf in kalshi_distributions().items()}


def write_distributions(dists, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    cols = [f"p{k}" for k in range(MAX_WINS + 1)]
    rows = [{"team": code, **{c: float(v) for c, v in zip(cols, pmf)}}
            for code, pmf in sorted(dists.items())]
    path = os.path.join(cache_dir, "kalshi_distributions.csv")
    pd.DataFrame(rows, columns=["team", *cols]).to_csv(path, index=False)
    return path
