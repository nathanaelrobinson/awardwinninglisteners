import numpy as np
import pandas as pd

from winspool.recommend import _assemble_sources
from winspool.store import InMemoryStore

FIX = "tests/fixtures"

# The full 272-game, 32-team schedule. The small 8-game fixtures cannot be used
# here: backout_market bails out on win totals a 2-game schedule cannot reach,
# so every strength comes back zero and the comparison below would pass no
# matter what the loader did.
SCHEDULE = f"{FIX}/schedule_full.csv"
# The market files deliberately post only 28 of the 32 teams, so the "teams with
# no posted number default to the mean of those posted" rule actually executes.
# With all 32 posted that fill is dead code and a broken one still compares equal.
TOTALS = f"{FIX}/win_totals_market.csv"
DIST = f"{FIX}/kalshi_distributions_market.csv"
POWER = f"{FIX}/power_ratings.csv"
UNPOSTED = {"WAS", "SEA", "MIA", "CHI"}


def test_the_store_path_reproduces_the_file_path_exactly():
    """The load-bearing property of the whole ratings migration.

    Same numbers in, identical strengths out — exactly, not approximately.
    If this cannot pass, the store-backed loader is wrong and the migration
    stops."""
    sched = pd.read_csv(SCHEDULE)
    sched = sched[sched["game_type"].str.upper() == "REG"]
    from winspool.teams import TEAM_INDEX
    home = sched["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    away = sched["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)

    from_files, sd_files = _assemble_sources(TOTALS, POWER, home, away, DIST)

    # Load the same CSVs into a store as ratings rows.
    store = InMemoryStore({})
    totals = pd.read_csv(TOTALS)
    store.add_rating({"source": "covers", "kind": "totals", "fetched_at": 1.0,
                      "ok": True,
                      "doc": {r["team"]: float(r["win_total"]) for _, r in totals.iterrows()}})
    power = pd.read_csv(POWER).set_index("team")
    for col in power.select_dtypes("number").columns:
        store.add_rating({"source": col, "kind": "power", "fetched_at": 1.0,
                          "ok": True,
                          "doc": {c: float(v) for c, v in power[col].items()}})
    dist = pd.read_csv(DIST).set_index("team")
    pcols = [f"p{k}" for k in range(18)]
    store.add_rating({"source": "kalshi", "kind": "distribution", "fetched_at": 1.0,
                      "ok": True,
                      "doc": {code: [float(v) for v in row]
                              for code, row in zip(dist.index, dist[pcols].to_numpy())}})

    from_store, sd_store = _assemble_sources(None, None, home, away, None, store=store)

    # The file path names the totals voice "vegas"; the store names it by its
    # source. Compare the strength vectors, which is what the model consumes.
    powercols = set(power.select_dtypes("number").columns)
    assert set(from_store) == {"covers", "kalshi"} | powercols
    np.testing.assert_array_equal(from_store["covers"], from_files["vegas"])
    np.testing.assert_array_equal(from_store["kalshi"], from_files["kalshi"])
    for col in powercols:
        np.testing.assert_array_equal(from_store[col], from_files[col])
    np.testing.assert_array_equal(sd_store, sd_files)

    # Guard against the comparison going vacuous again: an all-zero strength
    # vector or an all-NaN target_sd would make every assertion above unable to
    # fail, which is how the first version of this test shipped three bugs green.
    assert np.any(from_files["vegas"] != 0)
    assert np.any(from_files["kalshi"] != 0)
    assert np.any(~np.isnan(sd_files))
    # ...and that some teams really are unposted, or the nan-to-mean fill both
    # loaders apply would never run and could diverge undetected.
    assert set(totals["team"]).isdisjoint(UNPOSTED)
    assert np.any(np.isnan(sd_files))
