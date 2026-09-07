import random
import pytest
from fastapi.testclient import TestClient

from winspool import league, server
from winspool.store import InMemoryStore, set_store
from winspool.draft import PICK_ORDER

PLAYERS = ["Nate Robinson", "Evan Goguillon-Bader", "Logan Borgelt",
           "Eric Whitley", "Mitch Fischer"]
PIN = "awardwinninglisteners"


@pytest.fixture
def store():
    s = InMemoryStore(league.new_league(PLAYERS, "Nate Robinson", PIN))
    set_store(s)
    yield s
    set_store(None)


@pytest.fixture
def api(store, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    return TestClient(server.app)


def login(api, name, pin=PIN):
    c = TestClient(server.app)
    r = c.post("/api/login", json={"name": name, "pin": pin})
    return c, r


def name_for_slot(doc, slot):
    return next(n for n, s in doc["slots"].items() if s == slot)


def test_login_sets_cookie_and_me(api):
    c, r = login(api, "Mitch Fischer")
    assert r.status_code == 200
    assert "wp_session" in c.cookies
    me = c.get("/api/me").json()
    assert me == {"name": "Mitch Fischer", "is_commissioner": False, "slot": None}


def test_login_wrong_pin_401_unknown_name_401(api):
    _, r = login(api, "Mitch Fischer", "nope")
    assert r.status_code == 401
    _, r = login(api, "Nobody")
    assert r.status_code == 401


def test_league_requires_cookie(api):
    assert api.get("/api/league").status_code == 401


def test_league_view_and_logged_in_touch(api, store):
    c, _ = login(api, "Logan Borgelt")
    v = c.get("/api/league").json()
    assert v["status"] == "lobby"
    assert "Logan Borgelt" in v["logged_in"]
    assert "pin_hash" not in v


def test_randomize_commissioner_only(api, store):
    c, _ = login(api, "Eric Whitley")
    assert c.post("/api/league/randomize").status_code == 403
    n, _ = login(api, "Nate Robinson")
    r = n.post("/api/league/randomize")
    assert r.status_code == 200 and r.json()["status"] == "drafting"
    assert n.post("/api/league/randomize").status_code == 409
    assert n.post("/api/league/reset").status_code == 200
    assert store.get()["status"] == "lobby"


def test_pick_flow_turn_enforced_and_undo(api, store):
    n, _ = login(api, "Nate Robinson")
    n.post("/api/league/randomize")
    doc = store.get()
    first = name_for_slot(doc, PICK_ORDER[0])
    second = name_for_slot(doc, PICK_ORDER[1])
    c2, _ = login(api, second)
    assert c2.post("/api/league/pick", json={"team": "KC"}).status_code == 409
    c1, _ = login(api, first)
    r = c1.post("/api/league/pick", json={"team": "KC"})
    assert r.status_code == 200
    assert r.json()["rosters"][first] == ["KC"]
    assert c2.post("/api/league/pick", json={"team": "KC"}).status_code == 409
    assert c2.post("/api/league/undo").status_code == 403 or second == "Nate Robinson"
    assert n.post("/api/league/undo").status_code == 200
    assert store.get()["picks"] == []


def test_messages_roundtrip(api):
    c, _ = login(api, "Mitch Fischer")
    assert c.post("/api/messages", json={"text": ""}).status_code == 400
    assert c.post("/api/messages", json={"text": "x" * 501}).status_code == 400
    m = c.post("/api/messages", json={"text": "hello"}).json()
    assert m["by"] == "Mitch Fischer"
    all_ = c.get("/api/messages").json()
    assert [x["text"] for x in all_] == ["hello"]
    assert c.get("/api/messages", params={"since": m["ts"]}).json() == []


def test_optimizer_routes_commissioner_only(api):
    c, _ = login(api, "Mitch Fischer")
    assert c.post("/api/recommend", json={"slot": 1, "taken": []}).status_code == 403
    assert c.post("/api/results", json={"slot": 1, "taken": []}).status_code == 403
    assert c.post("/api/advance", json={"slot": 1, "taken": []}).status_code == 403
    assert api.get("/api/teams").status_code == 200  # open
