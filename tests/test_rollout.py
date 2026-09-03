import numpy as np
import pytest
from winspool.draft import DraftState
from winspool.opponents import chalk_power, entropy, greedy_self
from winspool.recommend import playout, rollout_recommend

def _wins():
    # 6 teams, cols 0..5; team win totals descend so ordering is clear
    rng = np.random.default_rng(0)
    base = np.array([13, 11, 10, 8, 6, 4], dtype=float)
    return (base[None, :] + rng.normal(0, 2, (4000, 6))).round().clip(0, 17).astype(np.int16)

def test_playout_fills_all_picks_capped_to_board():
    wins = _wins()
    st = DraftState(my_player=1, n_teams=6)
    # only 6 teams exist, so a 30-pick order can't fully run; playout must stop at board exhaustion
    final = playout(st, wins, greedy_self(wins), chalk_power(np.arange(6)[::-1]),
                    np.random.default_rng(1))
    drafted = final.drafted()
    assert len(drafted) == 6  # all teams taken, no duplicates
    assert len(drafted) == len(set(drafted))

def test_rollout_returns_sorted_survival_bounded():
    wins = _wins()
    st = DraftState(my_player=1, n_teams=6)
    recs = rollout_recommend(st, wins, greedy_self(wins),
                             entropy(np.arange(6)[::-1], temperature=8.0),
                             n_rollouts=40, rng=np.random.default_rng(2))
    assert {r["team"] for r in recs} == set(range(6))
    assert 0.0 <= recs[0]["survival"] <= 1.0
    assert recs == sorted(recs, key=lambda r: r["pwin"], reverse=True)

def test_rollout_candidates_limits_evaluation():
    wins = _wins()
    st = DraftState(my_player=1, n_teams=6)
    recs = rollout_recommend(st, wins, greedy_self(wins),
                             entropy(np.arange(6)[::-1], temperature=8.0),
                             n_rollouts=20, rng=np.random.default_rng(3),
                             candidates=[0, 2])
    assert {r["team"] for r in recs} == {0, 2}  # only the given candidates evaluated

def test_rollout_requires_my_turn():
    wins = _wins()
    st = DraftState(my_player=1, n_teams=6)
    st.apply_pick(0)  # player 1 (me) picks -> now it's player 2's turn
    with pytest.raises(ValueError):
        rollout_recommend(st, wins, greedy_self(wins),
                          entropy(np.arange(6)[::-1], temperature=8.0),
                          n_rollouts=5, rng=np.random.default_rng(4))
