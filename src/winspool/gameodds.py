"""Game-level odds: one raw value type, and the conversions that read it.

A GameOdds carries what a source *said* — American odds as posted, Kalshi
bid/ask mids as posted, the spread as posted. Probabilities are derived here,
on read, never stored. That is what lets a better conversion be run back over
every week already in the log.
"""
from dataclasses import dataclass

from scipy.stats import norm

from .game import SCALE

# Sources that speak for a market, best first. Order matters: market_prob
# averages every market voice it finds, and only falls through to nflverse when
# none of them are present.
MARKET_SOURCES = ("book", "kalshi")
FALLBACK_SOURCES = ("nflverse",)


@dataclass(frozen=True)
class GameOdds:
    source: str
    home: str
    away: str
    fetched_at: float
    spread: float | None = None      # home-favoured negative, as ESPN quotes it
    total: float | None = None
    ml_home: float | None = None     # American odds, as posted
    ml_away: float | None = None
    yes_home: float | None = None    # Kalshi yes-price, bid/ask mid, as posted
    yes_away: float | None = None
    p_home: float | None = None      # only ever set by source "model"

    def as_dict(self) -> dict:
        return {"home": self.home, "away": self.away, "spread": self.spread,
                "total": self.total, "ml_home": self.ml_home,
                "ml_away": self.ml_away, "yes_home": self.yes_home,
                "yes_away": self.yes_away, "p_home": self.p_home}


def prob_from_spread(spread: float) -> float:
    """Home win probability from a home-favoured-negative spread."""
    return float(norm.cdf(-float(spread) / SCALE))


def _implied(american: float) -> float:
    a = float(american)
    return 100.0 / (a + 100.0) if a > 0 else (-a) / (-a + 100.0)


def prob_from_moneyline(ml_home: float, ml_away: float) -> float | None:
    """Home win probability from a two-way moneyline, vig removed
    proportionally. Measured on Week 1 2026 the additive and Shin methods move
    this by under half a point, and the log keeps the raw odds, so the choice
    stays reversible."""
    h, a = _implied(ml_home), _implied(ml_away)
    total = h + a
    if total <= 0:
        return None
    return h / total


def prob_from_kalshi(yes_home: float, yes_away: float) -> float | None:
    """Home win probability from the two yes-prices, normalised to sum to 1."""
    h, a = float(yes_home), float(yes_away)
    total = h + a
    if total <= 0:
        return None
    return h / total


def to_prob(o: GameOdds) -> float | None:
    """One source's home win probability, or None if it quoted nothing usable."""
    if o.p_home is not None:
        return float(o.p_home)
    if o.yes_home is not None and o.yes_away is not None:
        return prob_from_kalshi(o.yes_home, o.yes_away)
    if o.ml_home is not None and o.ml_away is not None:
        return prob_from_moneyline(o.ml_home, o.ml_away)
    if o.spread is not None:
        return prob_from_spread(o.spread)
    return None


def market_prob(odds: list[GameOdds]) -> float | None:
    """Consensus market probability for one game: the mean of the market voices
    present, else the nflverse spread, else None. The model is never part of
    the consensus — it is the thing being replaced."""
    for group in (MARKET_SOURCES, FALLBACK_SOURCES):
        ps = [p for o in odds if o.source in group
              for p in (to_prob(o),) if p is not None]
        if ps:
            return sum(ps) / len(ps)
    return None
