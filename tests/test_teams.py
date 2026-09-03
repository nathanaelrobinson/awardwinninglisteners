# tests/test_teams.py
from winspool.teams import TEAMS, TEAM_INDEX, DIVISION, N_TEAMS

def test_thirty_two_unique_sorted_teams():
    assert len(TEAMS) == N_TEAMS == 32
    assert len(set(TEAMS)) == 32
    assert TEAMS == sorted(TEAMS)

def test_index_matches_position():
    assert all(TEAM_INDEX[c] == i for i, c in enumerate(TEAMS))

def test_eight_divisions_of_four():
    from collections import Counter
    counts = Counter(DIVISION[c] for c in TEAMS)
    assert len(counts) == 8
    assert all(v == 4 for v in counts.values())
