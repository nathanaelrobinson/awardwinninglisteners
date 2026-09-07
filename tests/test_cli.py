from winspool.cli import main

def test_cli_recommend_runs(capsys):
    code = main(["recommend", "--slot", "1",
                 "--schedule", "tests/fixtures/schedule_2026.csv",
                 "--totals", "tests/fixtures/win_totals.csv",
                 "--n", "300", "--seed", "0"])
    out = capsys.readouterr().out
    assert code == 0
    assert "pwin" in out.lower()
    # every board team should appear in the printed table
    assert "BUF" in out

def test_market_subcommand(tmp_path, capsys):
    import pandas as pd, numpy as np
    from winspool.cli import main
    cols = [f"p{k}" for k in range(18)]
    buf = np.zeros(18); buf[11] = 1.0
    p = tmp_path / "d.csv"
    pd.DataFrame([{"team": "BUF", **dict(zip(cols, buf))}]).to_csv(p, index=False)
    rc = main(["market", "--dist", str(p)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "BUF" in out and "line" in out

def test_league_init_writes_doc_and_refuses_overwrite_with_picks(monkeypatch):
    from winspool import cli, league
    from winspool.store import InMemoryStore, set_store
    s = InMemoryStore()
    set_store(s)
    monkeypatch.setenv("LEAGUE_PIN", "pw")
    players = "Nate Robinson,Evan Goguillon-Bader,Logan Borgelt,Eric Whitley,Mitch Fischer"
    cli.main(["league-init", "--players", players, "--commissioner", "Nate Robinson"])
    d = s.get()
    assert d["status"] == "lobby" and league.check_pin(d, "pw")
    # simulate a pick then refuse re-init without --force
    d["picks"].append({"n": 1, "slot": 1, "team": "KC", "by": "Nate Robinson", "ts": 1})
    s.put(d)
    import pytest
    with pytest.raises(SystemExit):
        cli.main(["league-init", "--players", players, "--commissioner", "Nate Robinson"])
    cli.main(["league-init", "--players", players, "--commissioner", "Nate Robinson", "--force"])
    assert s.get()["picks"] == []
    set_store(None)
