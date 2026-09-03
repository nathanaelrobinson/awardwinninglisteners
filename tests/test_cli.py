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
