import numpy as np
import pandas as pd
import pytest

from winspool.fetch.scrapers import EPA_SHRINK_K, epa_adjusted, shrink_weight


def _pbp(rows):
    """rows: (posteam, defteam, epa) triples, one per play."""
    return pd.DataFrame(
        [{"posteam": o, "defteam": d, "epa": e, "pass": 1, "rush": 0} for o, d, e in rows])


def test_opponent_adjustment_separates_a_good_offence_from_a_weak_schedule():
    # KC and BUF both average +0.30 EPA/play. KC did it against DEN, whose
    # defence is terrible; BUF did it against SEA, whose defence is strong.
    # An unadjusted mean rates them equal; opponent adjustment must rate BUF
    # higher. Extra plays pin the two defences relative to each other.
    rows = []
    rows += [("KC", "DEN", 0.30)] * 40
    rows += [("BUF", "SEA", 0.30)] * 40
    rows += [("SEA", "DEN", 0.60)] * 40      # DEN's defence bleeds against everyone
    rows += [("DEN", "SEA", 0.00)] * 40      # SEA's defence holds everyone
    out = epa_adjusted(_pbp(rows), ridge=0.01)
    assert out["BUF"] > out["KC"], f"expected BUF above KC, got {out}"


def test_shrinkage_moves_from_last_season_to_this_one_as_plays_accumulate():
    assert shrink_weight(0) == 0.0
    assert shrink_weight(EPA_SHRINK_K) == pytest.approx(0.5)
    assert shrink_weight(10 ** 9) > 0.99
    # week 1 of a season is a few hundred plays: this season must barely count
    assert shrink_weight(166) < 0.05
