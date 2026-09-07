from winspool import server


def test_cache_key_changes_when_kalshi_file_changes(tmp_path, monkeypatch):
    """The sim-matrix cache key must depend on the Kalshi distributions file —
    a Kalshi-only refresh should invalidate the cached matrix, since build_wins
    uses it for both the 'kalshi' source voice and per-team variance calibration."""
    kalshi_path = tmp_path / "kalshi_distributions.csv"
    monkeypatch.setattr(server, "KALSHI", kalshi_path)

    key_absent = server._cache_key()

    kalshi_path.write_text("team,p0\nKC,1.0\n")
    key_v1 = server._cache_key()
    assert key_v1 != key_absent

    # touch mtime with different content to make sure it's tracked
    import time
    time.sleep(0.01)
    kalshi_path.write_text("team,p0\nKC,0.5\n")
    key_v2 = server._cache_key()
    assert key_v2 != key_v1


def _ready():
    import os
    os.environ.setdefault("SESSION_SECRET", "test")
    from winspool import server
    server._ensure_ready()
    return server


def test_results_with_team_adds_hypothetical_pick_to_my_roster():
    server = _ready()
    from winspool.server import ResultsReq
    taken = ["DET", "PHI", "BAL", "KC", "BUF", "SF", "LA", "DEN", "CIN", "GB", "HOU"]
    base = server.results(ResultsReq(slot=1, taken=taken), _="x")
    hyp = server.results(ResultsReq(slot=1, taken=taken, with_team="CHI"), _="x")
    me0 = next(r for r in base["standings"] if r["is_me"])
    me1 = next(r for r in hyp["standings"] if r["is_me"])
    assert me0["teams"] == ["DET", "GB"]
    assert me1["teams"] == ["DET", "GB", "CHI"]
    assert me1["exp_wins"] > me0["exp_wins"] + 4     # CHI adds a full team of wins
    # nobody else changes roster
    for r in hyp["standings"]:
        if not r["is_me"]:
            assert "CHI" not in r["teams"]


def test_results_with_team_ignores_already_taken_team():
    server = _ready()
    from winspool.server import ResultsReq
    taken = ["DET", "PHI"]
    hyp = server.results(ResultsReq(slot=1, taken=taken, with_team="PHI"), _="x")
    me = next(r for r in hyp["standings"] if r["is_me"])
    assert me["teams"] == ["DET"]


def test_sample_season_with_team_adds_hypothetical_pick():
    server = _ready()
    from winspool.server import SampleReq
    out = server.sample_season(SampleReq(slot=1, taken=["DET", "PHI"], with_team="CHI"), _="x")
    me = next(r for r in out["standings"] if r["is_me"])
    assert [t["code"] for t in sorted(me["teams"], key=lambda t: t["code"])] == ["CHI", "DET"]
