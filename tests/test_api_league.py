import random
import pytest
from fastapi.testclient import TestClient

from winspool import auth, league, server
from winspool import api_league
from winspool.store import InMemoryStore, set_store
from winspool.draft import PICK_ORDER

PLAYERS = ["Nate Robinson", "Evan Goguillon-Bader", "Logan Borgelt",
           "Eric Whitley", "Mitch Fischer"]
PIN = "awardwinninglisteners"


@pytest.fixture
def store():
    s = InMemoryStore(league.new_league(PLAYERS, "Nate Robinson",
                                        {p: PIN for p in PLAYERS}))
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


def test_player_pin_does_not_login_other_player(monkeypatch):
    from winspool.store import InMemoryStore, set_store
    pins = {"Nate Robinson": "1111", "Evan Goguillon-Bader": "2222",
            "Logan Borgelt": "3333", "Eric Whitley": "4444",
            "Mitch Fischer": "5555"}
    s = InMemoryStore(league.new_league(PLAYERS, "Nate Robinson", pins))
    set_store(s)
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    try:
        c = TestClient(server.app)
        r = c.post("/api/login", json={"name": "Evan Goguillon-Bader", "pin": "1111"})
        assert r.status_code == 401
        r = c.post("/api/login", json={"name": "Nate Robinson", "pin": "1111"})
        assert r.status_code == 200
    finally:
        set_store(None)


def test_league_view_and_logged_in_touch(api, store):
    c, _ = login(api, "Logan Borgelt")
    v = c.get("/api/league").json()
    assert v["status"] == "lobby"
    assert "Logan Borgelt" in v["logged_in"]
    assert "pins" not in v


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
    non_commissioner = next(p for p in PLAYERS if p not in {first, "Nate Robinson"})
    c3, _ = login(api, non_commissioner)
    assert c3.post("/api/league/undo").status_code == 403
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


def test_me_and_messages_503_when_league_uninitialized(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    set_store(InMemoryStore())
    try:
        c = TestClient(server.app)
        c.cookies.set(auth.COOKIE, auth.sign("Nate Robinson"))
        assert c.get("/api/me").status_code == 503
        assert c.get("/api/messages").status_code == 503
        assert c.post("/api/messages", json={"text": "hi"}).status_code == 503
    finally:
        set_store(None)


def test_standings_zero_before_games_and_override(api, store, monkeypatch):
    from winspool import standings
    monkeypatch.setattr(standings, "fetch_wins", lambda refresh=False: ({t: 0 for t in standings.TEAMS}, False))
    n, _ = login(api, "Nate Robinson")
    n.post("/api/league/randomize")
    doc = store.get()
    first = name_for_slot(doc, PICK_ORDER[0])
    c1, _ = login(api, first)
    c1.post("/api/league/pick", json={"team": "KC"})
    r = n.get("/api/standings").json()
    row = next(x for x in r["rows"] if x["player"] == first)
    assert row["teams"] == [{"code": "KC", "wins": 0}] and row["total"] == 0
    assert n.post("/api/standings/override", json={"team": "KC", "wins": 3}).status_code == 200
    r = n.get("/api/standings").json()
    assert next(x for x in r["rows"] if x["player"] == first)["total"] == 3
    c2, _ = login(api, "Mitch Fischer")
    assert c2.post("/api/standings/override", json={"team": "KC", "wins": 9}).status_code == 403


class CountingStore(InMemoryStore):
    def __init__(self, doc=None):
        super().__init__(doc)
        self.update_calls = 0

    def update(self, fn):
        self.update_calls += 1
        return super().update(fn)


def test_league_poll_does_not_write_when_drafting(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    s = CountingStore(league.new_league(PLAYERS, "Nate Robinson",
                                        {p: PIN for p in PLAYERS}))
    set_store(s)
    try:
        c = TestClient(server.app)
        n, _ = login(TestClient(server.app), "Nate Robinson")
        n.post("/api/league/randomize")
        assert s.get()["status"] == "drafting"
        before = s.update_calls
        c.cookies.set(auth.COOKIE, auth.sign("Logan Borgelt"))
        for _ in range(5):
            r = c.get("/api/league")
            assert r.status_code == 200
        assert s.update_calls == before
    finally:
        set_store(None)


def test_league_poll_touches_at_most_once_per_20s_in_lobby(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    s = CountingStore(league.new_league(PLAYERS, "Nate Robinson",
                                        {p: PIN for p in PLAYERS}))
    set_store(s)
    try:
        c = TestClient(server.app)
        c.cookies.set(auth.COOKIE, auth.sign("Logan Borgelt"))
        base = 1_000_000.0
        monkeypatch.setattr(api_league.time, "time", lambda: base)
        for _ in range(5):
            r = c.get("/api/league")
            assert r.status_code == 200
        assert s.update_calls == 1
        monkeypatch.setattr(api_league.time, "time", lambda: base + 25)
        r = c.get("/api/league")
        assert r.status_code == 200
        assert s.update_calls == 2
    finally:
        set_store(None)


def test_standings_and_commissioner_routes_503_when_uninitialized(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    set_store(InMemoryStore())
    try:
        c = TestClient(server.app)
        c.cookies.set(auth.COOKIE, auth.sign("Nate Robinson"))
        assert c.get("/api/standings").status_code == 503
        assert c.post("/api/league/randomize").status_code == 503
    finally:
        set_store(None)


class ExhaustingStore(InMemoryStore):
    def update(self, fn):
        raise ValueError("Failed to commit transaction in 5 attempts.")


def test_run_maps_transaction_exhaustion_to_503(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    s = ExhaustingStore(league.new_league(PLAYERS, "Nate Robinson",
                                          {p: PIN for p in PLAYERS}))
    set_store(s)
    try:
        c = TestClient(server.app)
        c.cookies.set(auth.COOKIE, auth.sign("Nate Robinson"))
        r = c.post("/api/league/undo")
        assert r.status_code == 503
    finally:
        set_store(None)
