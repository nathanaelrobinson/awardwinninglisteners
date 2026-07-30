import numpy as np
from collections import Counter
from winspool.draft import (PICK_ORDER, DraftState, player_totals, pwin, greedy_pick)

def test_pick_order_valid():
    assert len(PICK_ORDER) == 30
    counts = Counter(PICK_ORDER)
    assert set(counts) == {1, 2, 3, 4, 5, 6}
    assert all(v == 5 for v in counts.values())
    assert PICK_ORDER[:6] == [1, 2, 3, 4, 5, 6]

def test_state_tracks_board_and_current_player():
    st = DraftState(my_player=3)
    assert st.current_player == 1
    st.apply_pick(10)  # player 1 takes team 10
    assert st.current_player == 2
    assert 10 not in st.board()
    assert st.rosters()[1] == [10]

def test_pwin_ties_count_as_win():
    # 2 sims, 2 players, identical totals -> both "win" every sim
    wins = np.array([[3, 3], [4, 4]], dtype=np.int16)  # cols are teams 0,1
    rosters = {1: [0], 2: [1], 3: [], 4: [], 5: [], 6: []}
    assert pwin(rosters, wins, 1) == 1.0
    assert pwin(rosters, wins, 2) == 1.0

def test_pwin_strict_winner():
    wins = np.array([[5, 1], [5, 1]], dtype=np.int16)
    rosters = {1: [0], 2: [1], 3: [], 4: [], 5: [], 6: []}
    assert pwin(rosters, wins, 1) == 1.0
    assert pwin(rosters, wins, 2) == 0.0

def test_greedy_picks_highest_win_team_when_alone():
    # team 2 wins most in every sim; an empty-roster player should grab it
    wins = np.array([[1, 2, 9], [0, 3, 8]], dtype=np.int16)
    st = DraftState(my_player=1, n_teams=3)
    assert greedy_pick(st, wins, 1) == 2
