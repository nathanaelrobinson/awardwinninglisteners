import numpy as np
from winspool.data import load_schedule, schedule_matchups, load_win_totals
from winspool.teams import TEAM_INDEX, N_TEAMS

SCHED = "tests/fixtures/schedule_2026.csv"
TOTALS = "tests/fixtures/win_totals.csv"

def test_load_schedule_drops_non_regular():
    df = load_schedule(SCHED)
    assert len(df) == 7  # the PRE row is dropped

def test_matchups_are_team_indices():
    home, away = schedule_matchups(load_schedule(SCHED))
    assert home.dtype.kind == "i" and away.dtype.kind == "i"
    assert home[0] == TEAM_INDEX["BUF"] and away[0] == TEAM_INDEX["NYJ"]
    assert len(home) == len(away) == 7

def test_win_totals_aligned_and_full_length():
    totals = load_win_totals(TOTALS)
    assert totals.shape == (N_TEAMS,)
    assert totals[TEAM_INDEX["BUF"]] == 11.5
    # teams absent from the file default to the league-average total
    assert np.isfinite(totals).all()
