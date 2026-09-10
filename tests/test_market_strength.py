import pytest

from winspool.marketstrength import HALF_LIFE_WEEKS, strength_from_spreads


def test_it_recovers_the_strengths_that_generated_the_spreads():
    # True strengths, in points. A spread is s_away - s_home - HFA, i.e. the
    # home-favoured-negative convention, so we generate from known values and
    # check the solve inverts it.
    true = {"KC": 6.0, "BUF": 3.0, "DEN": -3.0, "SEA": -6.0}
    from winspool.game import HFA
    games = []
    for h in true:
        for a in true:
            if h != a:
                games.append((h, a, true[a] - true[h] - HFA, 1))
    got = strength_from_spreads(games, current_week=2, ridge=1e-6)
    # recovered up to a shared additive constant, so compare centered
    c_true = {t: v - sum(true.values()) / len(true) for t, v in true.items()}
    c_got = {t: v - sum(got.values()) / len(got) for t, v in got.items()}
    for t in true:
        assert c_got[t] == pytest.approx(c_true[t], abs=0.05), f"{t}: {c_got} vs {c_true}"


def test_recent_weeks_outweigh_old_ones():
    from winspool.game import HFA
    # KC was 7 points better than BUF long ago, and 7 points worse last week.
    old = [("KC", "BUF", -7.0 - HFA, 1)] * 3
    recent = [("BUF", "KC", -7.0 - HFA, 9)] * 3
    got = strength_from_spreads(old + recent, current_week=10,
                                half_life=HALF_LIFE_WEEKS, ridge=1e-6)
    assert got["BUF"] > got["KC"], "the recent result must dominate"
