import os
import numpy as np
import pandas as pd
from winspool.draft import DraftState
from winspool.recommend import naive_recommend, build_wins, _assemble_sources
from winspool.teams import TEAM_INDEX, TEAMS, N_TEAMS
from winspool.data import load_schedule, schedule_matchups

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


def _kalshi_csv(tmp_path):
    # give every team a spiked PMF at a distinct win count so pmf_sd varies:
    # half the teams sharply peaked (low SD), half spread (high SD)
    cols = [f"p{k}" for k in range(18)]
    rows = []
    for i, code in enumerate(TEAMS):
        pmf = np.zeros(18)
        if i % 2 == 0:
            pmf[9] = 1.0                      # degenerate -> SD 0
        else:
            pmf[6] = pmf[12] = 0.5            # bimodal -> large SD
        rows.append({"team": code, **dict(zip(cols, pmf))})
    p = tmp_path / "kdist.csv"
    pd.DataFrame(rows, columns=["team", *cols]).to_csv(p, index=False)
    return str(p)


def test_assemble_sources_adds_kalshi_voice_when_file_present(tmp_path):
    df = load_schedule("data/cache/schedule_2026.csv")
    home, away = schedule_matchups(df)
    kp = _kalshi_csv(tmp_path)
    src_with, target = _assemble_sources("data/preseason/win_totals.csv",
                                         "data/preseason/power_ratings.csv", home, away, kp)
    assert "kalshi" in src_with
    assert np.isfinite(target).all()          # every team had a Kalshi SD
    src_without, target2 = _assemble_sources("data/preseason/win_totals.csv",
                                             "data/preseason/power_ratings.csv", home, away, None)
    assert "kalshi" not in src_without
    assert np.isnan(target2).all()


def test_build_wins_variance_tracks_kalshi_sd(tmp_path):
    from winspool.fetch.kalshi import pmf_sd
    from winspool.market import load_distributions
    kp = _kalshi_csv(tmp_path)
    wins, _ = build_wins("data/cache/schedule_2026.csv", "data/preseason/win_totals.csv",
                         n_seasons=6000, seed=0, power_path="data/preseason/power_ratings.csv",
                         kalshi_dist_path=kp)
    sim_sd = wins.std(axis=0)
    codes, mat = load_distributions(kp)
    k_sd = np.zeros(N_TEAMS)
    for code, row in zip(codes, mat):
        k_sd[TEAM_INDEX[code]] = pmf_sd(row)
    # teams the market says are high-variance (bimodal) should simulate wider than
    # the low-variance (spiked) teams
    hi = sim_sd[k_sd > 1.0].mean()
    lo = sim_sd[k_sd == 0.0].mean()
    assert hi > lo


def test_build_wins_kalshi_none_degrades_to_phase1_variance(tmp_path):
    """Absent Kalshi path (kalshi_dist_path=None) must NOT calibrate per-team
    variance to Kalshi SD -- that's the Phase-1 behavior the np.any(~np.isnan
    (target_sd)) gate in build_wins is supposed to preserve. With the file, the
    per-team sim SD should clearly track Kalshi's per-team SD; without it,
    the correlation should collapse."""
    from winspool.fetch.kalshi import pmf_sd
    from winspool.market import load_distributions

    kp = _kalshi_csv(tmp_path)
    codes, mat = load_distributions(kp)
    k_sd = np.zeros(N_TEAMS)
    for code, row in zip(codes, mat):
        k_sd[TEAM_INDEX[code]] = pmf_sd(row)

    wins_with, _ = build_wins("data/cache/schedule_2026.csv", "data/preseason/win_totals.csv",
                              n_seasons=6000, seed=0, power_path="data/preseason/power_ratings.csv",
                              kalshi_dist_path=kp)
    wins_without, _ = build_wins("data/cache/schedule_2026.csv", "data/preseason/win_totals.csv",
                                 n_seasons=6000, seed=0, power_path="data/preseason/power_ratings.csv",
                                 kalshi_dist_path=None)

    sd_with = wins_with.std(axis=0)
    sd_without = wins_without.std(axis=0)

    corr_with = np.corrcoef(sd_with, k_sd)[0, 1]
    corr_without = np.corrcoef(sd_without, k_sd)[0, 1]

    assert corr_with > corr_without + 0.3, (
        f"corr_with={corr_with:.3f} corr_without={corr_without:.3f}")
