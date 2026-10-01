"""The strategy-feed routes: /internal/game-probs, its history twin, /internal/games."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from winspool import gameprobs, league, live, server, standings
from winspool.store import InMemoryStore, SqliteStore, set_store
from winspool.teams import TEAMS

TOKEN = "feed-token"
H = {"X-Refresh-Token": TOKEN}


def ts(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


T1 = ts("2026-09-01T12:00:00")       # first ratings pull
T2 = ts("2026-09-20T12:00:00")       # second pull, after week 2
NOW = ts("2026-09-22T12:00:00")      # weeks 1-2 final, weeks 3-4 to play


def _round_robin_weeks(n_weeks):
    """Circle-method pairings: 16 games a week, every team once a week."""
    teams = list(TEAMS)
    rows = []
    for w in range(n_weeks):
        for i in range(16):
            a, b = teams[i], teams[31 - i]
            home, away = (a, b) if (w + i) % 2 == 0 else (b, a)
            rows.append((w + 1, home, away))
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    return rows


def schedule():
    days = {1: "2026-09-10", 2: "2026-09-17", 3: "2026-09-24", 4: "2026-10-01"}
    out = []
    for g, (week, home, away) in enumerate(_round_robin_weeks(4)):
        played = week <= 2
        hs, as_ = (24, 17) if g % 3 else (13, 20)
        out.append({"game_id": f"2026_{week:02d}_{away}_{home}", "week": week,
                    "game_type": "REG", "gameday": days[week], "gametime": "13:00",
                    "home_team": home, "away_team": away,
                    "home_score": hs if played else np.nan,
                    "away_score": as_ if played else np.nan})
    out.append({"game_id": "2026_19_KC_BUF", "week": 19, "game_type": "POST",
                "gameday": "2027-01-10", "gametime": "13:00", "home_team": "BUF",
                "away_team": "KC", "home_score": np.nan, "away_score": np.nan})
    return pd.DataFrame(out)


def _power(sign):
    return {c: sign * (i - 15.5) / 3.0 for i, c in enumerate(TEAMS)}


def seed_ratings(store, *, second=True):
    store.add_rating({"source": "espn_fpi", "kind": "power", "fetched_at": T1,
                      "ok": True, "doc": _power(1.0)})
    store.add_rating({"source": "epa_adj", "kind": "power", "fetched_at": T1,
                      "ok": True, "doc": {c: ((i * 7) % 11 - 5) / 2.0
                                          for i, c in enumerate(TEAMS)}})
    store.add_rating({"source": "covers", "kind": "totals", "fetched_at": T1,
                      "ok": True, "doc": {c: 6.0 + (i % 6) for i, c in enumerate(TEAMS)}})
    if second:
        # The later pull flips espn_fpi; history before T2 must not see it.
        store.add_rating({"source": "espn_fpi", "kind": "power", "fetched_at": T2,
                          "ok": True, "doc": _power(-1.0)})
        # A failed row after T1 never counts.
        store.add_rating({"source": "epa_adj", "kind": "power", "fetched_at": T2,
                          "ok": False, "doc": {"error": "boom"}})


def seed_odds(store, sched):
    wk3 = sched[sched["week"] == 3].iloc[0]
    for at, yes in ((T1, 0.40), (T2, 0.70)):
        store.add_odds({"season": 2026, "week": 3, "source": "kalshi", "fetched_at": at,
                        "games": [{"home": wk3.home_team, "away": wk3.away_team,
                                   "yes_home": yes, "yes_away": 1.0 - yes}]})
    return wk3


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    players = ["A", "B", "C", "D", "E"]
    doc = league.new_league(players, "A", {p: "1234" for p in players})
    s = InMemoryStore(doc) if request.param == "memory" else SqliteStore(tmp_path / "l.db")
    if request.param == "sqlite":
        s.put(doc)
    set_store(s)
    yield s
    set_store(None)
    if request.param == "sqlite":
        s.close()


@pytest.fixture
def api(store, monkeypatch):
    sched = schedule()
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv("REFRESH_TOKEN", TOKEN)
    monkeypatch.setenv("WINSPOOL_GIT_SHA", "abc1234")
    monkeypatch.setattr(gameprobs, "_GIT_SHA", [])
    monkeypatch.setattr(standings, "_load_schedule", lambda: sched)
    monkeypatch.setattr(live, "_LAST_SCHEDULE", None)
    monkeypatch.setattr(live, "_LAST_SCHEDULE_AT", None)
    monkeypatch.setattr(gameprobs, "_now", lambda: NOW)
    gameprobs._MODEL_CACHE.clear()
    return TestClient(server.app)


ROUTES = ["/internal/game-probs?season=2026",
          "/internal/game-probs/history?season=2026&as_of=2026-09-15T00:00:00Z",
          "/internal/games?season=2026"]


@pytest.mark.parametrize("path", ROUTES)
def test_token_required(api, store, monkeypatch, path):
    seed_ratings(store)
    assert api.get(path).status_code == 401
    assert api.get(path, headers={"X-Refresh-Token": "wrong"}).status_code == 401
    assert api.get(path, headers=H).status_code == 200
    monkeypatch.delenv("REFRESH_TOKEN")
    assert api.get(path, headers=H).status_code == 503


def test_game_probs_shape(api, store):
    seed_ratings(store)
    wk3 = seed_odds(store, schedule())
    body = api.get("/internal/game-probs?season=2026", headers=H).json()
    assert body["season"] == 2026
    assert body["as_of"] == "2026-09-22T12:00:00Z"
    assert body["model_version"] == f"abc1234@{int(T2)}"
    assert {t["code"] for t in body["teams"]} == set(TEAMS)
    assert {"code": "KC", "name": "Kansas City Chiefs"} in body["teams"]
    games = body["games"]
    assert len(games) == 32                         # weeks 3-4 only, no POST
    assert {g["week"] for g in games} == {3, 4}
    g = games[0]
    assert set(g) >= {"game_id", "week", "kickoff_utc", "home", "away", "p_home", "sources"}
    assert g["game_id"] == f"2026-{g['week']}-{g['away']}@{g['home']}"
    assert g["kickoff_utc"] == "2026-09-24T17:00:00Z"   # 13:00 EDT
    assert set(g["sources"]) == {"espn_fpi", "epa_adj", "covers"}
    for x in games:
        assert 0.0 < x["p_home"] < 1.0
        assert all(0.0 < p < 1.0 for p in x["sources"].values())
    by_id = {x["game_id"]: x for x in games}
    mk = by_id[f"2026-3-{wk3.away_team}@{wk3.home_team}"]
    assert mk["p_market"] == pytest.approx(0.70)
    assert sum(x["p_market"] is not None for x in games) == 1


def test_game_probs_matches_live_model(api, store):
    """p_home is compute_live's p_model for the same games: one model, two views."""
    seed_ratings(store)
    body = api.get("/internal/game-probs?season=2026", headers=H).json()
    live._ENSEMBLE_CACHE.clear()
    doc = live.compute_live({"A": ["KC"], "B": ["BUF"]}, schedule(), store=store,
                            n_seasons=200)
    feed = {(g["home"], g["away"]): g for g in body["games"] if g["week"] == 3}
    assert len(doc["games"]) == 16
    for g in doc["games"]:
        f = feed[(g["home"], g["away"])]
        assert f["p_home"] == pytest.approx(g["p_model"], abs=1e-4)
        assert f["sources"] == pytest.approx(g["p_voices"], abs=1e-4)


def test_history_at_now_reproduces_current(api, store):
    seed_ratings(store)
    seed_odds(store, schedule())
    cur = api.get("/internal/game-probs?season=2026", headers=H).json()
    hist = api.get("/internal/game-probs/history",
                   params={"season": 2026, "as_of": "2026-09-22T12:00:00Z"},
                   headers=H).json()
    assert hist == cur


def test_history_early_as_of_excludes_later_ratings(api, store, tmp_path):
    seed_ratings(store)
    seed_odds(store, schedule())
    as_of = "2026-09-15T00:00:00Z"            # after T1, before T2; week 1 final
    hist = api.get("/internal/game-probs/history",
                   params={"season": 2026, "as_of": as_of}, headers=H).json()
    again = api.get("/internal/game-probs/history",
                    params={"season": 2026, "as_of": as_of}, headers=H).json()
    assert hist == again                       # deterministic
    assert hist["as_of"] == as_of
    assert hist["model_version"] == f"abc1234@{int(T1)}"
    assert hist["ratings_fetched_at"] == "2026-09-01T12:00:00Z"
    # Week 1 is final by then (kickoff + 4 h); weeks 2-4 are not.
    assert {g["week"] for g in hist["games"]} == {2, 3, 4}

    # Same answer as a store that only ever had the T1 rows, live at that time.
    only_t1 = InMemoryStore({})
    seed_ratings(only_t1, second=False)
    seed_odds(only_t1, schedule())
    expect = gameprobs.game_probs(only_t1, schedule(), season=2026,
                                  as_of=ts("2026-09-15T00:00:00"))
    assert hist["games"] == expect["games"]

    cur = api.get("/internal/game-probs?season=2026", headers=H).json()
    h = {x["game_id"]: x for x in hist["games"]}
    c = {x["game_id"]: x for x in cur["games"]}
    shared = sorted(set(h) & set(c))
    assert shared
    # espn_fpi flipped at T2: the strength gap its voice implies (probit back
    # out, home edge removed) must change sign between the two views.
    from scipy.stats import norm
    from winspool.game import HFA, SCALE

    def gap(p):
        return norm.ppf(p) * SCALE - HFA

    for gid in shared:
        assert gap(h[gid]["sources"]["espn_fpi"]) * gap(c[gid]["sources"]["espn_fpi"]) < 0
    # The odds row at T2 is invisible too.
    mk = [x for x in hist["games"] if x["p_market"] is not None]
    assert len(mk) == 1 and mk[0]["p_market"] == pytest.approx(0.40)


def test_history_before_any_rating_is_404(api, store):
    seed_ratings(store)
    r = api.get("/internal/game-probs/history",
                params={"season": 2026, "as_of": "2026-08-01T00:00:00Z"}, headers=H)
    assert r.status_code == 404
    r = api.get("/internal/game-probs/history",
                params={"season": 2026, "as_of": "not a date"}, headers=H)
    assert r.status_code == 422


def test_other_season_404(api, store):
    seed_ratings(store)
    assert api.get("/internal/game-probs?season=2025", headers=H).status_code == 404


def test_games_shape(api, store):
    body = api.get("/internal/games?season=2026", headers=H).json()
    games = body["games"]
    assert len(games) == 64
    played = [g for g in games if g["played"]]
    assert len(played) == 32 and {g["week"] for g in played} == {1, 2}
    g = played[0]
    assert set(g) == {"game_id", "week", "kickoff_utc", "home", "away",
                      "home_score", "away_score", "played"}
    assert isinstance(g["home_score"], int) and isinstance(g["away_score"], int)
    un = next(g for g in games if not g["played"])
    assert un["home_score"] is None and un["away_score"] is None
    # Wins add up to what standings counts from the same frame.
    wins = standings.wins_from_schedule(schedule())
    counted = {c: 0 for c in TEAMS}
    for g in played:
        if g["home_score"] != g["away_score"]:
            counted[g["home"] if g["home_score"] > g["away_score"] else g["away"]] += 1
    assert counted == wins


def test_schedule_as_of_uses_kickoff_plus_four_hours():
    sched = schedule()
    ko = ts("2026-09-10T17:00:00")             # week 1, 13:00 EDT
    before = gameprobs.schedule_as_of(sched, ko + 4 * 3600 - 1)
    after = gameprobs.schedule_as_of(sched, ko + 4 * 3600)
    assert live.split_schedule(before)[0].empty
    assert len(live.split_schedule(after)[0]) == 16
