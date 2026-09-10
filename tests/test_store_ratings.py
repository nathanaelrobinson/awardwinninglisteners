import pytest

from winspool.store import InMemoryStore, SqliteStore


def _row(source, fetched_at, ok=True, value=1.0):
    doc = {"KC": value, "BUF": -value} if ok else {"error": "boom"}
    return {"source": source, "kind": "power", "fetched_at": fetched_at,
            "ok": ok, "doc": doc}


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    return InMemoryStore({}) if request.param == "memory" else SqliteStore(tmp_path / "t.db")


def test_latest_is_the_newest_ok_row_per_source(store):
    store.add_rating(_row("espn_fpi", 100.0, value=1.0))
    store.add_rating(_row("espn_fpi", 200.0, value=2.0))     # newer, wins
    store.add_rating(_row("espn_fpi", 300.0, ok=False))      # newest but failed
    store.add_rating(_row("kalshi", 150.0, value=9.0))

    latest = store.latest_ratings()
    assert set(latest) == {"espn_fpi", "kalshi"}
    # the failed row must NOT mask the last good one — that is the whole point
    assert latest["espn_fpi"]["doc"]["KC"] == 2.0
    assert latest["espn_fpi"]["fetched_at"] == 200.0
    # ...and the failure is still recorded, distinguishable from never having run
    hist = store.ratings_history("espn_fpi")
    assert [r["fetched_at"] for r in hist] == [100.0, 200.0, 300.0]
    assert hist[-1]["ok"] is False and hist[-1]["doc"]["error"] == "boom"


def test_rows_are_appended_never_replaced_and_survive_a_round_trip(store, tmp_path):
    first = store.add_rating(_row("epa_adj", 100.0, value=1.0))
    store.add_rating(_row("epa_adj", 200.0, value=2.0))
    kept = next(r for r in store.ratings_history("epa_adj") if r["id"] == first)
    assert kept["doc"]["KC"] == 1.0            # the earlier row is untouched

    dst = SqliteStore(tmp_path / "dst.db")
    for row in store.all_ratings():
        dst.put_rating(row)
    assert [r["id"] for r in dst.ratings_history("epa_adj")] == \
           [r["id"] for r in store.ratings_history("epa_adj")]
