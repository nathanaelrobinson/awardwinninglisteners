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
