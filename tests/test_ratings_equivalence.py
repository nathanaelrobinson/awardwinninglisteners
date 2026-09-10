import numpy as np
import pandas as pd

from winspool.recommend import _assemble_sources
from winspool.store import InMemoryStore

FIX = "tests/fixtures"


def test_the_store_path_reproduces_the_file_path_exactly():
    """The load-bearing property of the whole ratings migration.

    Same numbers in, identical strengths out — exactly, not approximately.
    If this cannot pass, the store-backed loader is wrong and the migration
    stops."""
    sched = pd.read_csv(f"{FIX}/schedule_2026.csv")
    sched = sched[sched["game_type"].str.upper() == "REG"]
    from winspool.teams import TEAM_INDEX
    home = sched["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    away = sched["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)

    from_files, sd_files = _assemble_sources(
        f"{FIX}/win_totals.csv", f"{FIX}/power_ratings.csv", home, away, None)

    # Load the same CSVs into a store as ratings rows.
    store = InMemoryStore({})
    totals = pd.read_csv(f"{FIX}/win_totals.csv")
    store.add_rating({"source": "covers", "kind": "totals", "fetched_at": 1.0,
                      "ok": True,
                      "doc": {r["team"]: float(r["win_total"]) for _, r in totals.iterrows()}})
    power = pd.read_csv(f"{FIX}/power_ratings.csv").set_index("team")
    for col in power.select_dtypes("number").columns:
        store.add_rating({"source": col, "kind": "power", "fetched_at": 1.0,
                          "ok": True,
                          "doc": {c: float(v) for c, v in power[col].items()}})

    from_store, sd_store = _assemble_sources(None, None, home, away, None, store=store)

    # The file path names the totals voice "vegas"; the store names it by its
    # source. Compare the strength vectors, which is what the model consumes.
    assert set(from_store) == {"covers"} | set(power.select_dtypes("number").columns)
    np.testing.assert_array_equal(from_store["covers"], from_files["vegas"])
    for col in power.select_dtypes("number").columns:
        np.testing.assert_array_equal(from_store[col], from_files[col])
    np.testing.assert_array_equal(sd_store, sd_files)
