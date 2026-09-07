import pandas as pd
from winspool import standings


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


def test_fetch_wins_uses_cache_and_reports_stale(monkeypatch):
    calls = []
    def fake_load():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("network")
        return df([("REG", "KC", "BUF", 27, 20)])
    monkeypatch.setattr(standings, "_load_schedule", fake_load)
    standings._CACHE.clear()
    w, stale = standings.fetch_wins()
    assert w["KC"] == 1 and stale is False
    w, stale = standings.fetch_wins()          # cached, no second call
    assert len(calls) == 1
    w, stale = standings.fetch_wins(refresh=True)  # fails → last good + stale
    assert w["KC"] == 1 and stale is True
