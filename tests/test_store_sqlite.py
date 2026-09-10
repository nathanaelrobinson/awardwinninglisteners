"""SqliteStore: parity with InMemoryStore, plus the durability and concurrency
properties the Pi deployment relies on."""
import threading

import pytest

from winspool import league
from winspool.store import (MSG_CAP, InMemoryStore, SqliteStore, get_store,
                            set_store)

PLAYERS = ["Nate Robinson", "Evan Goguillon-Bader", "Logan Borgelt",
           "Eric Whitley", "Mitch Fischer"]
PIN = "awardwinninglisteners"


def fresh():
    return league.new_league(PLAYERS, "Nate Robinson", {p: PIN for p in PLAYERS})


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    """The same suite runs against both stores."""
    if request.param == "memory":
        yield InMemoryStore(fresh())
        return
    s = SqliteStore(tmp_path / "league.db")
    s.put(fresh())
    yield s
    s.close()


# --- parity: these assertions must hold for either store ---

def test_get_returns_the_league(store):
    assert store.get()["players"] == PLAYERS
    assert store.get()["status"] == "lobby"


def test_put_then_get_round_trips(store):
    d = store.get()
    d["status"] = "drafting"
    store.put(d)
    assert store.get()["status"] == "drafting"


def test_update_applies_and_returns_new_doc(store):
    out = store.update(lambda d: {**d, "status": "done"})
    assert out["status"] == "done"
    assert store.get()["status"] == "done"


def test_update_rolls_back_when_fn_raises(store):
    with pytest.raises(ValueError):
        store.update(lambda d: (_ for _ in ()).throw(ValueError("nope")))
    assert store.get()["status"] == "lobby"


def test_messages_oldest_first_and_since_filter(store):
    m1 = store.add_message("Mitch Fischer", "lol")
    m2 = store.add_message("Nate Robinson", "ok")
    assert [m["text"] for m in store.messages(None)] == ["lol", "ok"]
    assert [m["text"] for m in store.messages(m1["ts"])] == ["ok"]
    assert m2["by"] == "Nate Robinson" and m2["id"]


def test_messages_caps_at_msg_cap_keeping_newest(store):
    for i in range(MSG_CAP + 25):
        store.add_message("Nate Robinson", f"m{i}")
    got = store.messages(None)
    assert len(got) == MSG_CAP
    # newest MSG_CAP, still returned oldest-first
    assert got[0]["text"] == "m25"
    assert got[-1]["text"] == f"m{MSG_CAP + 24}"


def test_clear_messages_returns_count(store):
    store.add_message("Nate Robinson", "a")
    store.add_message("Mitch Fischer", "b")
    assert store.clear_messages() == 2
    assert store.messages(None) == []


def test_standings_round_trip(store):
    assert store.get_standings() is None
    store.put_standings({"wins": {"KC": 3}, "stale": False})
    assert store.get_standings() == {"wins": {"KC": 3}, "stale": False}


def test_snapshots_newest_first_with_metadata(store):
    a = store.add_snapshot({"taken_at": 1.0, "reason": "restart", "n_picks": 0,
                            "status": "lobby", "league": {}, "messages": []})
    b = store.add_snapshot({"taken_at": 2.0, "reason": "complete", "n_picks": 30,
                            "status": "done", "league": {}, "messages": []})
    snaps = store.list_snapshots()
    assert [s["id"] for s in snaps] == [b, a]
    assert [s["reason"] for s in snaps] == ["complete", "restart"]
    assert snaps[0]["n_picks"] == 30 and snaps[0]["status"] == "done"


def test_all_messages_and_all_snapshots_are_uncapped_and_oldest_first(store):
    for i in range(MSG_CAP + 10):
        store.add_message("Nate Robinson", f"m{i}")
    store.add_snapshot({"taken_at": 2.0, "reason": "complete", "n_picks": 30,
                        "status": "done", "league": {"a": 1}, "messages": []})
    store.add_snapshot({"taken_at": 1.0, "reason": "restart", "n_picks": 0,
                        "status": "lobby", "league": {"b": 2}, "messages": []})
    msgs = store.all_messages()
    assert len(msgs) == MSG_CAP + 10
    assert msgs[0]["text"] == "m0"
    snaps = store.all_snapshots()
    assert [s["reason"] for s in snaps] == ["restart", "complete"]
    assert snaps[0]["league"] == {"b": 2}   # full doc, not just metadata


# --- SqliteStore only ---

def test_get_on_empty_db_raises_lookup_error(tmp_path):
    s = SqliteStore(tmp_path / "empty.db")
    with pytest.raises(LookupError):
        s.get()
    s.close()


def test_data_survives_reopen(tmp_path):
    path = tmp_path / "league.db"
    s = SqliteStore(path)
    s.put(fresh())
    s.update(lambda d: {**d, "status": "drafting"})
    m = s.add_message("Nate Robinson", "hello")
    s.put_standings({"wins": {"KC": 3}})
    sid = s.add_snapshot({"taken_at": 1.0, "reason": "restart", "n_picks": 0,
                          "status": "lobby", "league": {}, "messages": []})
    s.close()

    s2 = SqliteStore(path)
    assert s2.get()["status"] == "drafting"
    assert [x["id"] for x in s2.messages(None)] == [m["id"]]
    assert s2.get_standings() == {"wins": {"KC": 3}}
    assert [x["id"] for x in s2.list_snapshots()] == [sid]
    s2.close()


def test_creates_parent_directory(tmp_path):
    s = SqliteStore(tmp_path / "nested" / "deeper" / "league.db")
    s.put(fresh())
    assert s.get()["players"] == PLAYERS
    s.close()
    assert (tmp_path / "nested" / "deeper" / "league.db").exists()


def test_concurrent_updates_do_not_lose_writes(tmp_path):
    """The transactional guarantee `update` provides: no lost updates under
    simultaneous picks. 20 threads each increment; all 20 must land."""
    s = SqliteStore(tmp_path / "league.db")
    s.put({"n": 0})
    errors = []
    start = threading.Barrier(20)

    def bump():
        try:
            start.wait()
            s.update(lambda d: {**d, "n": d.get("n", 0) + 1})
        except BaseException as e:  # noqa: BLE001 - surfaced in the assert below
            errors.append(e)

    threads = [threading.Thread(target=bump) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert s.get()["n"] == 20
    s.close()


def test_concurrent_messages_all_persist(tmp_path):
    s = SqliteStore(tmp_path / "league.db")
    s.put(fresh())

    def post(i):
        s.add_message("Nate Robinson", f"m{i}")

    threads = [threading.Thread(target=post, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(s.all_messages()) == 30
    s.close()


def test_get_store_selects_sqlite_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE", "sqlite")
    monkeypatch.setenv("WINSPOOL_DB", str(tmp_path / "env.db"))
    set_store(None)
    try:
        s = get_store()
        assert isinstance(s, SqliteStore)
    finally:
        set_store(None)
    assert (tmp_path / "env.db").exists()


def test_live_doc_round_trips(store):
    assert store.get_live() is None
    store.put_live({"week": 3, "rows": []})
    assert store.get_live() == {"week": 3, "rows": []}
    store.put_live({"week": 4, "rows": []})
    assert store.get_live()["week"] == 4


def test_weeks_are_keyed_and_sorted(store):
    assert store.list_weeks() == []
    store.put_week(3, {"week": 3, "rows": [{"player": "A", "pwin": 0.5}]})
    store.put_week(1, {"week": 1, "rows": []})
    store.put_week(3, {"week": 3, "rows": [{"player": "A", "pwin": 0.6}]})  # overwrite
    weeks = store.list_weeks()
    assert [w["week"] for w in weeks] == [1, 3]
    assert weeks[1]["rows"][0]["pwin"] == 0.6
