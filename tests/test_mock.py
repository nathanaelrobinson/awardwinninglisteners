import numpy as np
from winspool.opponents import chalk_power, entropy, greedy_self
from winspool.mock import auto_draft, positional_study

def _wins():
    rng = np.random.default_rng(0)
    base = np.linspace(12, 4, 32)
    return (base[None, :] + rng.normal(0, 2, (3000, 32))).round().clip(0, 17).astype(np.int16)

def test_auto_draft_completes_full_board():
    wins = _wins()
    strengths = np.linspace(12, 4, 32)
    pols = {p: entropy(strengths, 8.0) for p in range(1, 6)}
    pols[1] = greedy_self(wins)
    final = auto_draft(wins, pols, my_player=1, rng=np.random.default_rng(1))
    assert len(final.picks) == 30
    assert len(final.drafted()) == 30  # no duplicates

def test_positional_study_returns_all_slots():
    wins = _wins()
    strengths = np.linspace(12, 4, 32)
    res = positional_study(wins, greedy_self(wins), entropy(strengths, 8.0),
                           k=15, rng=np.random.default_rng(3))
    assert set(res) == {1, 2, 3, 4, 5}
    assert all(0.0 <= v <= 1.0 for v in res.values())
