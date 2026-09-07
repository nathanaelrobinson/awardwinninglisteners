import pandas as pd
from winspool import standings
from winspool.store import InMemoryStore


def df(rows):
    return pd.DataFrame(rows, columns=["game_type", "home_team", "away_team",
                                       "home_score", "away_score"])


def test_wins_count_reg_only_ties_zero_unplayed_ignored():
    d = df([
        ("REG", "KC", "BUF", 27, 20),      # KC win
        ("REG", "DAL", "PHI", 17, 17),     # tie: nobody
        ("REG", "SF", "LA", None, None),   # unplayed
        ("POST", "KC", "BUF", 30, 10),     # playoffs: ignored
        ("REG", "BUF", "KC", 10, 13),      # KC win (away)
    ])
    w = standings.wins_from_schedule(d)
    assert w["KC"] == 2
    assert w["BUF"] == 0 and w["DAL"] == 0 and w["PHI"] == 0
    assert w["SF"] == 0 and w["LA"] == 0
    assert len(w) == 32  # every team present


def test_apply_overrides():
    w = {"KC": 2, "BUF": 0}
    assert standings.apply_overrides(w, {"BUF": 1})["BUF"] == 1
    assert standings.apply_overrides(w, {"BUF": 1})["KC"] == 2


def test_refresh_standings_success_writes_doc(monkeypatch):
    store = InMemoryStore()
    monkeypatch.setattr(standings, "_load_schedule",
                         lambda: df([("REG", "KC", "BUF", 27, 20)]))
    doc = standings.refresh_standings(store)
    assert doc["wins"]["KC"] == 1 and doc["ok"] is True and doc["error"] is None
    assert len(doc["wins"]) == 32
    assert isinstance(doc["fetched_at"], float)
    assert store.get_standings() == doc


def test_refresh_standings_failure_keeps_previous_wins(monkeypatch):
    store = InMemoryStore()
    monkeypatch.setattr(standings, "_load_schedule",
                         lambda: df([("REG", "KC", "BUF", 27, 20)]))
    first = standings.refresh_standings(store)

    def boom():
        raise RuntimeError("network down")
    monkeypatch.setattr(standings, "_load_schedule", boom)
    second = standings.refresh_standings(store)
    assert second["wins"] == first["wins"]
    assert second["fetched_at"] == first["fetched_at"]
    assert second["ok"] is False
    assert "network down" in second["error"]
    assert store.get_standings() == second


def test_refresh_standings_failure_with_no_previous_writes_zeros(monkeypatch):
    store = InMemoryStore()

    def boom():
        raise RuntimeError("network down")
    monkeypatch.setattr(standings, "_load_schedule", boom)
    doc = standings.refresh_standings(store)
    assert all(w == 0 for w in doc["wins"].values())
    assert len(doc["wins"]) == 32
    assert doc["ok"] is False
    assert "network down" in doc["error"]
    assert store.get_standings() == doc
