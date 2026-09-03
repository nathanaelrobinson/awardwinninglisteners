import numpy as np
from winspool.draft import DraftState
from winspool.recommend import naive_recommend, build_wins

def test_naive_recommend_ranks_and_covers_board():
    # team 2 dominant, team 0 weak
    wins = np.array([[1, 5, 9], [2, 4, 8], [0, 6, 10]], dtype=np.int16)
    st = DraftState(my_player=1, n_teams=3)
    recs = naive_recommend(st, wins)
    assert [r["team"] for r in recs][0] == 2      # best first
    assert {r["team"] for r in recs} == {0, 1, 2}  # all available teams present
    assert recs[0]["pwin"] >= recs[-1]["pwin"]

def test_build_wins_shapes():
    wins, strengths = build_wins("tests/fixtures/schedule_2026.csv",
                                 "tests/fixtures/win_totals.csv",
                                 n_seasons=500, seed=0)
    from winspool.teams import N_TEAMS
    assert wins.shape == (500, N_TEAMS)
    assert strengths.shape == (N_TEAMS,)
