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
    players = "Nate Robinson,Evan Goguillon-Bader,Logan Borgelt,Eric Whitley,Mitch Fischer"
    pins = "Nate Robinson=1111,Evan Goguillon-Bader=2222,Logan Borgelt=3333,Eric Whitley=4444,Mitch Fischer=5555"
    cli.main(["league-init", "--players", players, "--commissioner", "Nate Robinson",
             "--pins", pins])
    d = s.get()
    assert d["status"] == "lobby" and league.check_pin(d, "Nate Robinson", "1111")
    assert not league.check_pin(d, "Nate Robinson", "2222")
    # simulate a pick then refuse re-init without --force
    d["picks"].append({"n": 1, "slot": 1, "team": "KC", "by": "Nate Robinson", "ts": 1})
    s.put(d)
    import pytest
    with pytest.raises(SystemExit):
        cli.main(["league-init", "--players", players, "--commissioner", "Nate Robinson",
                 "--pins", pins])
    cli.main(["league-init", "--players", players, "--commissioner", "Nate Robinson",
             "--pins", pins, "--force"])
    assert s.get()["picks"] == []
    set_store(None)


def test_league_init_generates_random_pins_and_prints_them(monkeypatch, capsys):
    from winspool import cli, league
    from winspool.store import InMemoryStore, set_store
    s = InMemoryStore()
    set_store(s)
    players = "Nate Robinson,Evan Goguillon-Bader,Logan Borgelt,Eric Whitley,Mitch Fischer"
    cli.main(["league-init", "--players", players, "--commissioner", "Nate Robinson"])
    out = capsys.readouterr().out
    d = s.get()
    names = players.split(",")
    for name in names:
        assert name in out
    # every printed 4-digit PIN actually logs that player in
    for line in out.strip().splitlines():
        name, _, pin = line.partition(":")
        name, pin = name.strip(), pin.strip()
        assert name in names
        assert len(pin) == 4 and pin.isdigit()
        assert league.check_pin(d, name, pin)
    set_store(None)


def test_league_init_with_pins_prints_nothing_sensitive(capsys):
    from winspool import cli
    from winspool.store import InMemoryStore, set_store
    s = InMemoryStore()
    set_store(s)
    players = "Nate Robinson,Evan Goguillon-Bader,Logan Borgelt,Eric Whitley,Mitch Fischer"
    pins = "Nate Robinson=1111,Evan Goguillon-Bader=2222,Logan Borgelt=3333,Eric Whitley=4444,Mitch Fischer=5555"
    cli.main(["league-init", "--players", players, "--commissioner", "Nate Robinson",
             "--pins", pins])
    out = capsys.readouterr().out
    assert out.strip() == "league initialized"
    set_store(None)
