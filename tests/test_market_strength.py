import pytest

from winspool.marketstrength import HALF_LIFE_WEEKS, strength_from_spreads
from winspool.teams import TEAMS


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


def test_production_ridge_shrinks_when_unidentified_but_not_when_connected():
    # This is the one test that exercises the production RIDGE constant --
    # every other test above pins ridge=1e-6 explicitly, which is exactly how
    # a too-small base ridge went dead without anyone noticing.
    from winspool.game import HFA

    # Week 1: 16 disjoint games, one 7-point home favourite each. Minimum-norm
    # (ridge -> 0) hands the favourite half the spread with no opponent
    # adjustment at all -- this is the under-determined shape the ridge exists
    # to damp.
    true = {"home": 3.5, "away": -3.5}
    sparse_games = []
    for i in range(16):
        home, away = TEAMS[2 * i], TEAMS[2 * i + 1]
        sparse_games.append((home, away, true["away"] - true["home"] - HFA, 1))

    shrunk = strength_from_spreads(sparse_games, current_week=1)
    unshrunk = strength_from_spreads(sparse_games, current_week=1, ridge=1e-6)
    favourite = TEAMS[0]
    assert unshrunk[favourite] == pytest.approx(3.5, abs=0.05)
    assert abs(shrunk[favourite]) < 0.7 * abs(unshrunk[favourite]), (
        f"favourite strength should be damped well below minimum-norm when "
        f"the graph is disjoint: shrunk={shrunk[favourite]} "
        f"unshrunk={unshrunk[favourite]}")

    # Late season: every team has faced every other team once, so the graph
    # is fully connected and the same base ridge should barely move anything.
    dense_games = [(h, a, true["away"] - true["home"] - HFA, 1)
                   for i, h in enumerate(TEAMS) for a in TEAMS[i + 1:]]
    dense_shrunk = strength_from_spreads(dense_games, current_week=1)
    dense_unshrunk = strength_from_spreads(dense_games, current_week=1, ridge=1e-6)
    assert dense_shrunk[favourite] == pytest.approx(
        dense_unshrunk[favourite], rel=0.05), (
        "a densely connected graph should be faithful to the unshrunk fit, "
        f"got shrunk={dense_shrunk[favourite]} unshrunk={dense_unshrunk[favourite]}")


def test_it_recovers_the_strengths_on_an_unbalanced_schedule():
    # The round-robin above hides a whole class of bug: every team is home and
    # away equally often, so X'1 = 0 and any CONSTANT error in y -- an HFA
    # applied with the wrong sign, say -- cancels out of the normal equations
    # and the solve still recovers the truth. Real NFL schedules are nothing
    # like that. Here KC only ever hosts and SEA only ever visits, which is the
    # lopsidedness that makes a constant offset in y bend the strengths instead
    # of vanishing.
    from winspool.game import HFA
    true = {"KC": 6.0, "BUF": 3.0, "DEN": -3.0, "SEA": -6.0}
    order = ["KC", "BUF", "DEN", "SEA"]        # home count 3, 2, 1, 0
    games = [(h, a, true[a] - true[h] - HFA, 1)
             for i, h in enumerate(order) for a in order[i + 1:]]
    got = strength_from_spreads(games, current_week=2, ridge=1e-6)
    c_true = {t: v - sum(true.values()) / len(true) for t, v in true.items()}
    c_got = {t: v - sum(got.values()) / len(got) for t, v in got.items()}
    for t in true:
        assert c_got[t] == pytest.approx(c_true[t], abs=0.05), f"{t}: {c_got} vs {c_true}"
