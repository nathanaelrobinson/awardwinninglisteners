"""`winspool export` -> `winspool import` is the Cloud Run -> Pi cutover path.
Nothing may be lost or renumbered on the way across."""
import json
import random

import pytest

from winspool import league
from winspool.cli import main
from winspool.store import InMemoryStore, SqliteStore, set_store

PLAYERS = ["Nate Robinson", "Evan Goguillon-Bader", "Logan Borgelt",
           "Eric Whitley", "Mitch Fischer"]
PIN = "awardwinninglisteners"


def populated():
    """An in-memory store shaped like a real league mid-season."""
    doc = league.new_league(PLAYERS, "Nate Robinson", {p: PIN for p in PLAYERS})
    doc = league.randomize(doc, random.Random(1))
    s = InMemoryStore(doc)
    s.add_message("Mitch Fischer", "lets go")
    s.add_message("Nate Robinson", "on the clock")
    s.add_snapshot({"taken_at": 1.0, "reason": "restart", "n_picks": 0,
                    "status": "lobby", "league": {"x": 1}, "messages": []})
    s.add_snapshot({"taken_at": 2.0, "reason": "complete", "n_picks": 30,
                    "status": "done", "league": {"y": 2}, "messages": []})
    s.put_standings({"wins": {"KC": 3, "BUF": 2}, "updated_at": 123.0})
    return s


def run(argv, store):
    set_store(store)
    try:
        return main(argv)
    finally:
        set_store(None)


def test_export_import_round_trip_preserves_everything(tmp_path):
    src = populated()
    out = tmp_path / "league_export.json"
    assert run(["export", "--out", str(out)], src) == 0

    dst = SqliteStore(tmp_path / "league.db")
    assert run(["import", "--from", str(out)], dst) == 0

    assert dst.get() == src.get()
    assert league.view(dst.get()) == league.view(src.get())
    assert dst.all_messages() == src.all_messages()
    assert dst.get_standings() == src.get_standings()
    assert ([{k: s[k] for k in ("id", "taken_at", "reason", "n_picks", "status")}
             for s in dst.list_snapshots()]
            == [{k: s[k] for k in ("id", "taken_at", "reason", "n_picks", "status")}
                for s in src.list_snapshots()])
    assert dst.all_snapshots() == src.all_snapshots()
    dst.close()


def test_export_writes_expected_keys(tmp_path):
    out = tmp_path / "e.json"
    run(["export", "--out", str(out)], populated())
    payload = json.loads(out.read_text())
    assert set(payload) == {"league", "messages", "snapshots", "standings",
                            "exported_at"}
    assert len(payload["messages"]) == 2
    assert len(payload["snapshots"]) == 2
    assert payload["league"]["players"] == PLAYERS


def test_message_ids_and_timestamps_survive(tmp_path):
    """The feed polls with ?since=<ts>; renumbering would replay the whole feed."""
    src = populated()
    out = tmp_path / "e.json"
    run(["export", "--out", str(out)], src)
    dst = SqliteStore(tmp_path / "l.db")
    run(["import", "--from", str(out)], dst)

    before, after = src.all_messages(), dst.all_messages()
    assert [m["id"] for m in before] == [m["id"] for m in after]
    assert [m["ts"] for m in before] == [m["ts"] for m in after]
    # and `since` still filters correctly against the imported timestamps
    assert [m["text"] for m in dst.messages(before[0]["ts"])] == ["on the clock"]
    dst.close()


def test_import_refuses_non_empty_target_without_force(tmp_path, capsys):
    out = tmp_path / "e.json"
    run(["export", "--out", str(out)], populated())
    dst = SqliteStore(tmp_path / "l.db")
    dst.put(league.new_league(PLAYERS, "Nate Robinson", {p: PIN for p in PLAYERS}))

    with pytest.raises(SystemExit) as e:
        run(["import", "--from", str(out)], dst)
    assert "--force" in str(e.value)
    dst.close()


def test_import_force_overwrites_and_is_idempotent(tmp_path):
    src = populated()
    out = tmp_path / "e.json"
    run(["export", "--out", str(out)], src)
    dst = SqliteStore(tmp_path / "l.db")
    dst.put(league.new_league(PLAYERS, "Nate Robinson", {p: PIN for p in PLAYERS}))

    assert run(["import", "--from", str(out), "--force"], dst) == 0
    assert run(["import", "--from", str(out), "--force"], dst) == 0  # re-run
    assert dst.get() == src.get()
    assert len(dst.all_messages()) == 2      # not duplicated
    assert len(dst.all_snapshots()) == 2     # not duplicated
    dst.close()


def test_import_force_drops_snapshots_the_target_already_had(tmp_path):
    src = populated()
    out = tmp_path / "e.json"
    run(["export", "--out", str(out)], src)
    dst = SqliteStore(tmp_path / "l.db")
    dst.put(league.new_league(PLAYERS, "Nate Robinson", {p: PIN for p in PLAYERS}))
    dst.add_snapshot({"taken_at": 1.0, "reason": "restart", "n_picks": 0, "status": "drafting"})

    assert run(["import", "--from", str(out), "--force"], dst) == 0
    assert dst.all_snapshots() == src.all_snapshots()   # the stray test snapshot is gone
    dst.close()


def test_export_of_empty_store_exits(tmp_path):
    with pytest.raises(SystemExit) as e:
        run(["export", "--out", str(tmp_path / "e.json")], InMemoryStore())
    assert "no league" in str(e.value)


def test_import_rejects_a_file_that_is_not_an_export(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"hello": "world"}')
    dst = SqliteStore(tmp_path / "l.db")
    with pytest.raises(SystemExit) as e:
        run(["import", "--from", str(bad)], dst)
    assert "not a winspool export" in str(e.value)
    dst.close()
