"""The model the Simulations tab rolls its own seasons against.

The contract that matters: a client that plays `games` from `banked`, using the
draw described in simmodel.build_model's docstring, reproduces the same
distribution live.compute_live does. These tests pin the shape and that
equivalence, so the browser and the server cannot drift apart silently.
"""
import numpy as np
import pandas as pd
import pytest

from winspool import live, simmodel
from winspool.game import win_prob
from winspool.teams import N_TEAMS, TEAM_INDEX, TEAMS

COLS = ["week", "game_type", "home_team", "away_team", "home_score", "away_score"]

CACHE = "data/cache"
TOTALS = f"{CACHE}/win_totals.csv"
POWER = f"{CACHE}/power_ratings.csv"
KALSHI = f"{CACHE}/kalshi_distributions.csv"


def full_schedule(played_weeks=0):
    """Every team plays once a week for four weeks; `played_weeks` have scores."""
    rows = []
    for wk in range(1, 5):
        order = TEAMS[wk % 2:] + TEAMS[:wk % 2]
        for i in range(0, N_TEAMS - 1, 2):
            h, a = order[i], order[i + 1]
            done = wk <= played_weeks
            rows.append((wk, "REG", h, a, 24 if done else None, 17 if done else None))
    return pd.DataFrame(rows, columns=COLS)


@pytest.fixture
def rosters():
    return {"A": list(TEAMS[:4]), "B": list(TEAMS[4:8])}


def build(df, rosters):
    return simmodel.build_model(rosters, df, totals_path=TOTALS, power_path=POWER,
                                kalshi_dist_path=KALSHI, now=0.0)


def test_shapes_line_up(rosters):
    m = build(full_schedule(), rosters)
    assert len(m["strength"]) == len(m["sources"]) == len(m["weights"])
    assert all(len(row) == N_TEAMS for row in m["strength"])
    assert len(m["sigma"]) == N_TEAMS
    assert len(m["banked"]) == N_TEAMS
    assert m["teams"] == list(TEAMS)
    assert pytest.approx(sum(m["weights"]), abs=1e-6) == 1.0
    assert m["hfa"] and m["scale"]


def test_played_games_are_banked_and_absent_from_games(rosters):
    """A result, once real, is locked into every season a client rolls: it shows
    up in `banked` and its game is gone from `games`."""
    m = build(full_schedule(played_weeks=2), rosters)
    assert m["week"] == 3
    assert sum(m["banked"]) == N_TEAMS          # 2 weeks x 16 games, one win each
    assert {g[0] for g in m["games"]} == {3, 4}
    assert m["weeks"] == [3, 4]


def test_no_games_played_means_nothing_banked(rosters):
    m = build(full_schedule(), rosters)
    assert sum(m["banked"]) == 0
    assert len(m["games"]) == 4 * (N_TEAMS // 2)
    assert m["week"] == 1


def test_rolling_the_model_matches_the_server_projection(rosters):
    """Play the model the way the browser does and land on the same win
    probabilities live.compute_live reports. Both are Monte Carlo, so this is a
    tolerance check, not equality."""
    df = full_schedule(played_weeks=1)
    m = build(df, rosters)

    rng = np.random.default_rng(0)
    n = 20000
    src = rng.choice(len(m["weights"]), size=n, p=np.array(m["weights"]))
    strength = np.array(m["strength"])
    st = strength[src] + rng.standard_normal((n, N_TEAMS)) * np.array(m["sigma"])

    wins = np.tile(np.array(m["banked"]), (n, 1))
    for _wk, home, away in m["games"]:
        h, a = TEAM_INDEX[home], TEAM_INDEX[away]
        home_win = rng.standard_normal(n) < (st[:, h] - st[:, a] + m["hfa"]) / m["scale"]
        wins[:, h] += home_win
        wins[:, a] += ~home_win

    totals = {p: wins[:, [TEAM_INDEX[c] for c in codes]].sum(axis=1)
              for p, codes in rosters.items()}
    mine = live.pool_pwin(totals)

    doc = live.compute_live(rosters, df, totals_path=TOTALS, power_path=POWER,
                            kalshi_dist_path=KALSHI, ratings_fetched_at=None,
                            n_seasons=20000, seed=0, now=0.0)
    theirs = {r["player"]: r["pwin"] for r in doc["rows"]}

    for p in rosters:
        assert mine[p] == pytest.approx(theirs[p], abs=0.03), p


def test_draw_form_agrees_with_win_prob():
    """home wins <=> diff > scale * Z is the same coin as game.win_prob(diff)."""
    rng = np.random.default_rng(3)
    sh, sa = 4.0, -1.5
    n = 200000
    hit = rng.standard_normal(n) < (sh - sa + simmodel.HFA) / simmodel.SCALE
    assert hit.mean() == pytest.approx(float(win_prob(sh, sa)), abs=0.005)


def test_model_is_json_small(rosters):
    """The point of shipping the model rather than the outcomes."""
    import json
    m = build(full_schedule(), rosters)
    assert len(json.dumps(m, separators=(",", ":"))) < 40_000


def test_one_game_final_mid_week_is_banked_and_reported(rosters):
    """The Thursday-night case. A single final is locked into `banked` and out of
    `games` while the rest of its week is still to be played, and it is reported
    in `played` so a client can show it as settled."""
    df = full_schedule()
    first = df.index[0]
    home = df.at[first, "home_team"]
    df.loc[first, ["home_score", "away_score"]] = [31, 3]

    m = build(df, rosters)
    assert m["week"] == 1                     # week 1 is still open
    assert sum(m["banked"]) == 1              # exactly one win banked
    assert m["banked"][TEAM_INDEX[home]] == 1
    assert len(m["games"]) == 4 * (N_TEAMS // 2) - 1
    assert not any(g[1] == home and g[0] == 1 for g in m["games"])
    assert m["played"] == [[1, home, df.at[first, "away_team"], 1]]


def test_a_tie_is_reported_and_split(rosters):
    df = full_schedule()
    first = df.index[0]
    df.loc[first, ["home_score", "away_score"]] = [17, 17]
    m = build(df, rosters)
    assert m["played"][0][3] == -1
    assert sum(m["banked"]) == 1.0            # half a win each side


class _StubStore:
    """Just the two methods refresh_model touches."""
    def __init__(self):
        self.saved = None

    def get(self):
        return {}

    def put_sim_model(self, doc):
        self.saved = doc


def test_refresh_model_stores_it(rosters, monkeypatch):
    """The endpoint serves a stored doc, so refreshing has to leave one."""
    from winspool import league as lg
    monkeypatch.setattr(lg, "view", lambda _doc: {"rosters": rosters})
    store = _StubStore()

    doc = simmodel.refresh_model(store, CACHE, sched_df=full_schedule(played_weeks=1))
    assert store.saved is doc
    assert doc["week"] == 2
    assert len(doc["games"]) == 3 * (N_TEAMS // 2)


def test_a_supplied_schedule_is_not_refetched(rosters, monkeypatch):
    """Loading the schedule pulls the season from nfl_data_py, about 2s. That is
    why refresh_live hands over the frame it already has."""
    from winspool import league as lg
    monkeypatch.setattr(lg, "view", lambda _doc: {"rosters": rosters})
    calls = []
    monkeypatch.setattr(simmodel.live, "_load_schedule_cached",
                        lambda: calls.append(1) or full_schedule())

    simmodel.refresh_model(_StubStore(), CACHE, sched_df=full_schedule())
    assert calls == []

    simmodel.refresh_model(_StubStore(), CACHE)
    assert calls == [1], "without one it must fall back to loading the schedule"


def test_every_store_round_trips_the_model(tmp_path):
    from winspool.store import InMemoryStore, SqliteStore
    from winspool import league as lg
    names = ["A", "B", "C", "D", "E"]
    doc = lg.new_league(names, "A", {n: "1111" for n in names})
    for store in (InMemoryStore(doc), SqliteStore(str(tmp_path / "s.db"))):
        assert store.get_sim_model() is None
        store.put_sim_model({"week": 7})
        assert store.get_sim_model() == {"week": 7}
