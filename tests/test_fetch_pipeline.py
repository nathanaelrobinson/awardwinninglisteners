import json
import pandas as pd
import pytest
from winspool.fetch.pipeline import Source, refresh


def test_refresh_aggregates_totals_and_columns_power(tmp_path):
    srcs = [
        Source("book_a", "totals", lambda: {"BUF": 11.0, "KC": 10.0}),
        Source("book_b", "totals", lambda: {"BUF": 12.0, "KC": 10.0}),
        Source("fpi", "power", lambda: {"BUF": 6.0, "KC": 5.0}),
        Source("sagarin", "power", lambda: {"BUF": 6.5, "KC": 4.5}),
    ]
    meta = refresh(srcs, str(tmp_path), now="2026-08-20")

    wt = pd.read_csv(tmp_path / "win_totals.csv").set_index("team")["win_total"]
    assert wt["BUF"] == 11.5 and wt["KC"] == 10.0      # mean across books

    pr = pd.read_csv(tmp_path / "power_ratings.csv").set_index("team")
    assert set(pr.columns) == {"fpi", "sagarin"}       # one column per power source
    assert pr.loc["BUF", "fpi"] == 6.0

    assert {m["name"] for m in meta} == {"book_a", "book_b", "fpi", "sagarin"}
    saved = json.load(open(tmp_path / "sources_meta.json"))
    assert all(m["fetched_at"] == "2026-08-20" for m in saved)


def test_refresh_rejects_unknown_kind(tmp_path):
    with pytest.raises(ValueError):
        refresh([Source("x", "weird", lambda: {"BUF": 1.0})], str(tmp_path))


def _boom():
    raise RuntimeError("520 Server Error")


def test_refresh_skips_a_failing_source_and_keeps_the_rest(tmp_path):
    srcs = [
        Source("covers", "totals", lambda: {"BUF": 11.0, "KC": 10.0}),
        Source("betmgm", "totals", _boom),                 # dead source (e.g. 520)
        Source("fpi", "power", lambda: {"BUF": 6.0, "KC": 5.0}),
    ]
    meta = refresh(srcs, str(tmp_path), now="2026-09-03")

    # the healthy totals source still produces win_totals (mean over survivors)
    wt = pd.read_csv(tmp_path / "win_totals.csv").set_index("team")["win_total"]
    assert wt["BUF"] == 11.0 and wt["KC"] == 10.0

    pr = pd.read_csv(tmp_path / "power_ratings.csv").set_index("team")
    assert pr.loc["BUF", "fpi"] == 6.0

    # meta records every source; the failed one is flagged, not dropped silently
    by_name = {m["name"]: m for m in meta}
    assert by_name["betmgm"]["ok"] is False and "520" in by_name["betmgm"]["error"]
    assert by_name["covers"]["ok"] is True and by_name["covers"]["n_teams"] == 2
