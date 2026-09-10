"""Game-level odds sources.

Three voices per game: the nflverse schedule frame we already fetch (a slow,
reliable baseline), DraftKings via ESPN's scoreboard (live book numbers), and
Kalshi's per-game markets (a live exchange). Parsers are pure and tested
against captured fixtures; the fetchers are covered by live smoke tests.

Adapters return raw quoted values. The only transformation permitted here is
normalising team codes.
"""
import re
import time

import pandas as pd
import requests

from ..gameodds import GameOdds
from ..teams import resolve

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
KALSHI_URL = "https://external-api.kalshi.com/trade-api/v2/markets"
KALSHI_SERIES = "KXNFLGAME"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
TIMEOUT = 30


def _f(x):
    try:
        return float(str(x).replace("+", ""))
    except (TypeError, ValueError):
        return None


def _moneyline(odds_block, side):
    """American odds for one side: the closing number, else the current one."""
    block = (odds_block or {}).get(side) or {}
    for key in ("close", "current", "open"):
        v = (block.get(key) or {}).get("odds")
        got = _f(v)
        if got is not None:
            return got
    return None


def parse_espn(payload: dict, fetched_at: float) -> list[GameOdds]:
    out = []
    for event in payload.get("events") or []:
        comps = event.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]
        sides = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        if "home" not in sides or "away" not in sides:
            continue
        home = resolve((sides["home"].get("team") or {}).get("displayName"))
        away = resolve((sides["away"].get("team") or {}).get("displayName"))
        if not home or not away:
            continue
        odds = (comp.get("odds") or [{}])[0]
        ml = odds.get("moneyline") or {}
        out.append(GameOdds(
            source="book", home=home, away=away, fetched_at=fetched_at,
            spread=_f(odds.get("spread")), total=_f(odds.get("overUnder")),
            ml_home=_moneyline(ml, "home"), ml_away=_moneyline(ml, "away")))
    return out


def fetch_espn(season: int, week: int) -> list[GameOdds]:
    r = requests.get(ESPN_URL, params={"dates": season, "seasontype": 2,
                                       "week": week}, timeout=TIMEOUT)
    r.raise_for_status()
    return parse_espn(r.json(), time.time())


_KALSHI_FIX = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS"}


def _kalshi_price(m):
    bid, ask = _f(m.get("yes_bid_dollars")), _f(m.get("yes_ask_dollars"))
    if bid is not None and ask is not None:
        return (bid + ask) / 2.0
    return _f(m.get("last_price_dollars"))


def parse_kalshi(markets: list[dict], pairs: set, fetched_at: float) -> list[GameOdds]:
    """Kalshi tickers carry no week, so games are matched by team pair.

    A ticker looks like KXNFLGAME-26SEP21NYGLAR-NYG: series, event, and the
    side this market pays out on. Each event has one market per team; a game is
    usable only when both sides are priced."""
    by_event: dict[str, dict[str, float]] = {}
    for m in markets:
        parts = (m.get("ticker") or "").split("-")
        if len(parts) != 3:
            continue
        code = resolve(_KALSHI_FIX.get(parts[2], parts[2]))
        price = _kalshi_price(m)
        if not code or price is None:
            continue
        by_event.setdefault(parts[1], {})[code] = price

    out = []
    for home, away in pairs:
        for sides in by_event.values():
            if home in sides and away in sides:
                out.append(GameOdds(source="kalshi", home=home, away=away,
                                    fetched_at=fetched_at,
                                    yes_home=sides[home], yes_away=sides[away]))
                break
    return out


def fetch_kalshi(pairs: set) -> list[GameOdds]:
    r = requests.get(KALSHI_URL, params={"series_ticker": KALSHI_SERIES,
                                         "status": "open", "limit": 1000},
                     headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return parse_kalshi(r.json().get("markets") or [], pairs, time.time())


def week_pairs(df: pd.DataFrame, week: int) -> set:
    reg = df[(df["game_type"].str.upper() == "REG") & (df["week"] == week)]
    pairs = set()
    for r in reg.itertuples(index=False):
        home, away = resolve(r.home_team), resolve(r.away_team)
        if home and away:
            pairs.add((home, away))
    return pairs


def from_schedule(df: pd.DataFrame, week: int, fetched_at: float) -> list[GameOdds]:
    """The baseline already in the frame we fetch for scores. nflverse quotes
    the spread home-favoured POSITIVE; we store ESPN's sign convention."""
    reg = df[(df["game_type"].str.upper() == "REG") & (df["week"] == week)]
    out = []
    for r in reg.itertuples(index=False):
        spread = _f(getattr(r, "spread_line", None))
        if spread is None or pd.isna(spread):
            continue
        home, away = resolve(r.home_team), resolve(r.away_team)
        if not home or not away:
            continue
        total = _f(getattr(r, "total_line", None))
        out.append(GameOdds(source="nflverse", home=home, away=away,
                            fetched_at=fetched_at, spread=-spread,
                            total=None if total is None or pd.isna(total) else total))
    return out
