import json
import os

import pandas as pd
import pytest

from winspool.fetch.odds import (from_schedule, parse_espn, parse_kalshi,
                                 week_pairs)

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


@pytest.fixture
def espn_payload():
    return _load("espn_scoreboard_2026_wk1.json")


@pytest.fixture
def kalshi_markets():
    return _load("kalshi_games_2026_wk1.json")["markets"]


def test_espn_carries_raw_quoted_values_and_no_probability(espn_payload):
    got = parse_espn(espn_payload, fetched_at=123.0)
    assert len(got) == 16
    assert {o.source for o in got} == {"book"}
    assert {o.fetched_at for o in got} == {123.0}
    kc = next(o for o in got if o.home == "KC")
    assert kc.away == "DEN"
    assert kc.spread == pytest.approx(-2.5)
    assert kc.total == pytest.approx(43.5)
    assert kc.ml_home == pytest.approx(-148)
    assert kc.ml_away == pytest.approx(124)
    assert kc.p_home is None


def test_espn_normalises_team_codes(espn_payload):
    codes = {c for o in parse_espn(espn_payload, 0.0) for c in (o.home, o.away)}
    assert not codes & {"LAR", "WSH", "JAC"}
    assert {"LA", "WAS", "JAX"} <= codes


def test_kalshi_matches_games_by_team_pair(kalshi_markets):
    pairs = {("KC", "DEN"), ("PHI", "WAS")}
    got = parse_kalshi(kalshi_markets, pairs, fetched_at=7.0)
    assert {(o.home, o.away) for o in got} == pairs
    assert {o.source for o in got} == {"kalshi"}
    for o in got:
        assert 0 < o.yes_home < 1 and 0 < o.yes_away < 1
        assert o.p_home is None
    # a pair with no market on the exchange is skipped, not faked
    assert parse_kalshi(kalshi_markets, {("KC", "ZZZ")}, 0.0) == []


def test_from_schedule_reads_the_nflverse_columns():
    df = pd.DataFrame([
        {"week": 1, "game_type": "REG", "home_team": "KC", "away_team": "DEN",
         "spread_line": 2.5, "total_line": 43.5},
        {"week": 2, "game_type": "REG", "home_team": "LA", "away_team": "SF",
         "spread_line": 3.5, "total_line": 48.5},
        # a week-1 game with no line yet is skipped rather than defaulted
        {"week": 1, "game_type": "REG", "home_team": "NE", "away_team": "NYJ",
         "spread_line": None, "total_line": None},
    ])
    got = from_schedule(df, week=1, fetched_at=1.0)
    assert len(got) == 1
    o = got[0]
    assert (o.source, o.home, o.away) == ("nflverse", "KC", "DEN")
    # nflverse quotes home-favoured POSITIVE; we store ESPN's convention.
    assert o.spread == pytest.approx(-2.5)
    assert o.total == pytest.approx(43.5)
    assert o.p_home is None


def test_week_pairs_is_home_away_for_the_regular_season_week():
    df = pd.DataFrame([
        {"week": 1, "game_type": "REG", "home_team": "KC", "away_team": "DEN"},
        {"week": 1, "game_type": "PRE", "home_team": "LA", "away_team": "SF"},
        {"week": 2, "game_type": "REG", "home_team": "NE", "away_team": "NYJ"},
    ])
    assert week_pairs(df, 1) == {("KC", "DEN")}


@pytest.mark.live
def test_espn_endpoint_still_returns_what_the_parser_expects():
    from winspool.fetch.odds import fetch_espn
    got = fetch_espn(2026, 1)
    assert len(got) >= 14
    assert sum(1 for o in got if o.spread is not None) >= 14


@pytest.mark.live
def test_kalshi_endpoint_still_returns_what_the_parser_expects():
    from winspool.fetch.odds import fetch_kalshi
    got = fetch_kalshi({("KC", "DEN")})
    assert len(got) == 1
    assert got[0].yes_home is not None
