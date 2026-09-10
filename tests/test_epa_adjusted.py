import pandas as pd
import pytest

from winspool.fetch import scrapers
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


def _fake_nflverse(monkeypatch, frames):
    """Stand in for nfl_data_py, which epa_ratings imports lazily. `frames` maps
    season -> DataFrame; a missing season yields the EMPTY frame that
    import_pbp_data really returns when a year fails to download."""
    import sys
    import types
    mod = types.ModuleType("nfl_data_py")

    def import_pbp_data(years, columns=None, downcast=True, include_participation=True):
        assert include_participation is False, "participation is a dead second download"
        assert columns, "the Pi cannot afford all ~380 pbp columns for two seasons"
        return frames.get(years[0], pd.DataFrame(columns=columns))

    mod.import_pbp_data = import_pbp_data
    monkeypatch.setitem(sys.modules, "nfl_data_py", mod)


def test_a_missing_current_season_is_a_cold_start_in_week_1_and_a_failure_after():
    """nfl_data_py swallows a download failure and hands back an empty frame, so
    "the season hasn't started" and "nflverse is down" look identical. Week 1
    may lean on last season — that is what the shrinkage is for. Week 3 must
    NOT: last season's 32 ratings stored ok=True with today's timestamp would
    satisfy staleness, return 200, and never look wrong to anyone."""
    prior = _pbp([("KC", "DEN", 0.30)] * 40 + [("DEN", "KC", 0.00)] * 40)
    cur, prior_season = scrapers.epa_seasons()

    with pytest.MonkeyPatch.context() as mp:
        _fake_nflverse(mp, {prior_season: prior})
        out = scrapers.epa_ratings(week=1)
        assert out["KC"] > out["DEN"], "week 1 falls back to last season"
        assert out["__meta__"]["n_plays"] == 0 and out["__meta__"]["w"] == 0.0

        with pytest.raises(RuntimeError) as e:
            scrapers.epa_ratings(week=3)
        assert str(cur) in str(e.value) and "week 3" in str(e.value)

    # nflverse down entirely: no season at all is always a failure, never a
    # silent empty result that some other layer has to notice.
    with pytest.MonkeyPatch.context() as mp:
        _fake_nflverse(mp, {})
        with pytest.raises(RuntimeError):
            scrapers.epa_ratings(week=1)

    # With both seasons present the doc records HOW MUCH of the rating is this
    # season. Without n_plays and w stored, a 2%-current rating and a
    # 90%-current one are indistinguishable documents in the Admin panel.
    with pytest.MonkeyPatch.context() as mp:
        _fake_nflverse(mp, {cur: prior.copy(), prior_season: prior})
        meta = scrapers.epa_ratings(week=3)["__meta__"]
    assert meta["n_plays"] == 80
    assert meta["w"] == pytest.approx(shrink_weight(80), abs=1e-4)
    assert meta["season"] == cur and meta["prior_season"] == prior_season
