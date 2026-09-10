"""Shared test helpers.

Ratings live in the store now, so anything that exercises a refresh needs a
store with rating rows in it. These load the same small fixture CSVs the file
path tests use, so both paths are fed identical numbers.
"""
import pandas as pd

FIX = "tests/fixtures"


def seed_fixture_ratings(store, fetched_at=1_700_000_000.0):
    """Load tests/fixtures win totals + power ratings into `store` as ratings
    rows: one totals voice named for its source, one power voice per column."""
    totals = pd.read_csv(f"{FIX}/win_totals.csv")
    store.add_rating({"source": "covers", "kind": "totals", "fetched_at": fetched_at,
                      "ok": True,
                      "doc": {r["team"]: float(r["win_total"]) for _, r in totals.iterrows()}})
    power = pd.read_csv(f"{FIX}/power_ratings.csv").set_index("team")
    for col in power.select_dtypes("number").columns:
        store.add_rating({"source": col, "kind": "power", "fetched_at": fetched_at,
                          "ok": True, "doc": {c: float(v) for c, v in power[col].items()}})
    return store
