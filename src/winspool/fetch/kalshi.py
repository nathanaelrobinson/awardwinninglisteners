"""Kalshi KXNFLWINS market source: per-team implied win distributions.

Pure functions (ladder -> PMF, moments) are unit-tested against a fixture.
The network fetchers hit Kalshi's PUBLIC endpoint (no auth) and are smoke-tested.
"""
import re
import numpy as np
from ..teams import resolve

MAX_WINS = 17

_KALSHI_FIX = {"LAR": "LA", "JAC": "JAX"}


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


def ladder_to_pmf(markets):
    """A team's 17-rung ladder -> normalized PMF over wins 0..17 (length 18).

    floor_strike=k prices P(W>=k). We build the survival curve P(W>=k), force it
    non-increasing (cummin) to remove bid/ask crossing noise, then difference it
    into a PMF, clip negatives, and renormalize (removes vig/underround)."""
    surv = np.full(MAX_WINS + 1, np.nan)   # surv[k] = P(W >= k)
    surv[0] = 1.0
    for m in markets:
        k = int(m["floor_strike"])
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
        pmf = ladder_to_pmf(markets)
        if pmf.sum() > 0:
            out[code] = pmf
    return out
