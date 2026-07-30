import numpy as np
from winspool.data import load_schedule, schedule_matchups, load_win_totals
from winspool.ratings import backout_market
from winspool.game import expected_wins, HFA, SCALE

def test_backout_reproduces_posted_totals():
    # A dedicated, internally-consistent fixture: 4 teams in a closed
    # home-and-away round robin (12 games total). Unlike schedule_2026.csv /
    # win_totals.csv (a handful of games paired with full-season O/U lines,
    # used by other tests), here sum(win_total) == num_games, so the
    # per-team targets are actually reachable by construction.
    df = load_schedule("tests/fixtures/schedule_calibration.csv")
    home, away = schedule_matchups(df)
    totals = load_win_totals("tests/fixtures/win_totals_calibration.csv")
    s = backout_market(totals, home, away, hfa=HFA, scale=SCALE)
    ew = expected_wins(s, home, away)
    # only teams that actually appear in the fixture schedule are constrained
    played = sorted(set(home.tolist()) | set(away.tolist()))
    assert np.allclose(ew[played], totals[played], atol=0.05)
