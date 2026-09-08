import numpy as np
import pandas as pd
import pytest

from winspool import live
from winspool.teams import TEAM_INDEX

COLS = ["week", "game_type", "home_team", "away_team", "home_score", "away_score"]


def sched(rows):
    return pd.DataFrame(rows, columns=COLS)


@pytest.fixture
def inseason():
    """Weeks 1-2 played, week 3 has one final and one unplayed, week 4 unplayed."""
    return sched([
        (1, "REG", "KC", "BUF", 27, 20),
        (1, "REG", "DAL", "PHI", 17, 17),      # tie
        (2, "REG", "BUF", "KC", 10, 13),
        (2, "REG", "PHI", "DAL", 30, 10),
        (3, "REG", "KC", "PHI", 21, 14),
        (3, "REG", "BUF", "DAL", None, None),
        (4, "REG", "DAL", "KC", None, None),
        (4, "REG", "PHI", "BUF", None, None),
        (19, "POST", "KC", "BUF", None, None),  # ignored
    ])


def test_split_schedule_reg_only(inseason):
    played, remaining = live.split_schedule(inseason)
    assert len(played) == 5 and len(remaining) == 3
    assert set(played["game_type"]) == {"REG"} and set(remaining["game_type"]) == {"REG"}


def test_banked_wins_counts_ties_as_half(inseason):
    played, _ = live.split_schedule(inseason)
    b = live.banked_wins(played)
    assert b.shape == (32,)
    assert b[TEAM_INDEX["KC"]] == 3
    assert b[TEAM_INDEX["BUF"]] == 0
    assert b[TEAM_INDEX["DAL"]] == 0.5 and b[TEAM_INDEX["PHI"]] == 1.5


def test_week_of_is_first_week_with_unplayed_game(inseason):
    assert live.week_of(inseason) == 3
    done = inseason.copy()
    done.loc[done["home_score"].isna(), ["home_score", "away_score"]] = 1
    assert live.week_of(done) == 19


def test_remaining_matchups_and_games_in_week(inseason):
    _, remaining = live.split_schedule(inseason)
    home, away = live.remaining_matchups(remaining)
    assert list(home) == [TEAM_INDEX["BUF"], TEAM_INDEX["DAL"], TEAM_INDEX["PHI"]]
    assert list(away) == [TEAM_INDEX["DAL"], TEAM_INDEX["KC"], TEAM_INDEX["BUF"]]
    wk = live.games_in_week(remaining, 3)
    assert len(wk) == 1 and wk.iloc[0]["home_team"] == "BUF"
    per = live.remaining_games_per_team(remaining)
    assert per[TEAM_INDEX["KC"]] == 1 and per[TEAM_INDEX["BUF"]] == 2


FIX = "tests/fixtures"


def test_vegas_weight_decays_to_zero_by_week_9():
    assert live.vegas_weight(1) == pytest.approx(8 / 9)
    assert live.vegas_weight(5) == pytest.approx(4 / 9)
    assert live.vegas_weight(9) == 0.0
    assert live.vegas_weight(14) == 0.0


def test_source_matrix_weights_and_order():
    from winspool.data import load_schedule, schedule_matchups
    home, away = schedule_matchups(load_schedule(f"{FIX}/schedule_2026.csv"))
    m, w, names = live.source_matrix_for_week(f"{FIX}/win_totals.csv",
                                              f"{FIX}/power_ratings.csv",
                                              home, away, week=3)
    assert names[0] == "vegas" and names[1:] == ["fpi", "sagarin", "massey"]
    assert m.shape == (4, 32)
    assert w.sum() == pytest.approx(1.0)
    assert w[0] == pytest.approx(live.vegas_weight(3))
    assert np.allclose(w[1:], (1 - w[0]) / 3)
    m9, w9, _ = live.source_matrix_for_week(f"{FIX}/win_totals.csv",
                                            f"{FIX}/power_ratings.csv",
                                            home, away, week=9)
    assert w9[0] == 0.0 and np.allclose(w9[1:], 1 / 3)


def test_source_matrix_without_totals_file_has_no_vegas(tmp_path):
    from winspool.data import load_schedule, schedule_matchups
    home, away = schedule_matchups(load_schedule(f"{FIX}/schedule_2026.csv"))
    m, w, names = live.source_matrix_for_week(str(tmp_path / "missing.csv"),
                                              f"{FIX}/power_ratings.csv",
                                              home, away, week=1)
    assert names == ["fpi", "sagarin", "massey"] and np.allclose(w, 1 / 3)


def test_season_sigma_shrinks_with_games_left():
    per = np.full(32, 17)
    per[0] = 0
    per[1] = 4
    s = live.season_sigma(per, base_sigma=4.5)
    assert s[2] == pytest.approx(4.5)
    assert s[0] == 0.0
    assert s[1] == pytest.approx(4.5 * np.sqrt(4 / 17))


def test_consensus_is_weighted_mean():
    m = np.array([[1.0] * 32, [3.0] * 32])
    assert np.allclose(live.consensus(m, np.array([0.25, 0.75])), 2.5)
