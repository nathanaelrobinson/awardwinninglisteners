import os
import random
import re
import time
import pytest
from fastapi.testclient import TestClient

from winspool import auth, league, server
from winspool import api_league
from winspool.store import InMemoryStore, SqliteStore, set_store
from winspool.draft import PICK_ORDER
from winspool.teams import TEAMS

PLAYERS = ["Nate Robinson", "Evan Goguillon-Bader", "Logan Borgelt",
           "Eric Whitley", "Mitch Fischer"]
PIN = "awardwinninglisteners"


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    """Every endpoint test runs twice: against the dev store and against the
    SQLite store the Pi serves from."""
    doc = league.new_league(PLAYERS, "Nate Robinson", {p: PIN for p in PLAYERS})
    if request.param == "memory":
        s = InMemoryStore(doc)
    else:
        s = SqliteStore(tmp_path / "league.db")
        s.put(doc)
    set_store(s)
    yield s
    set_store(None)
    if request.param == "sqlite":
        s.close()


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
    import pandas as pd
    empty = pd.DataFrame([], columns=["game_type", "home_team", "away_team",
                                       "home_score", "away_score"])
    monkeypatch.setattr(standings, "_load_schedule", lambda: empty)
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


def test_restart_commissioner_only(api, store):
    c, _ = login(api, "Eric Whitley")
    assert c.post("/api/league/restart").status_code == 403


def test_restart_after_picks_snapshots_and_clears_messages(api, store):
    n, _ = login(api, "Nate Robinson")
    n.post("/api/league/randomize")
    doc = store.get()
    first = name_for_slot(doc, PICK_ORDER[0])
    second = name_for_slot(doc, PICK_ORDER[1])
    c1, _ = login(api, first)
    c1.post("/api/league/pick", json={"team": "KC"})
    c2, _ = login(api, second)
    c2.post("/api/league/pick", json={"team": "BUF"})
    c1.post("/api/messages", json={"text": "gl hf"})

    r = n.post("/api/league/restart")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "lobby"
    assert body["picks"] == []
    assert body["slots"] is None

    assert store.messages(None) == []

    snaps = store.list_snapshots()
    assert len(snaps) == 1
    assert snaps[0]["reason"] == "restart"
    assert snaps[0]["n_picks"] == 2

    r = n.get("/api/league/snapshots")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_restart_works_from_lobby_and_from_done(api, store):
    n, _ = login(api, "Nate Robinson")
    r = n.post("/api/league/restart")
    assert r.status_code == 200 and r.json()["status"] == "lobby"

    n.post("/api/league/randomize")
    doc = store.get()
    for i in range(30):
        who = name_for_slot(doc, PICK_ORDER[i])
        c, _ = login(api, who)
        c.post("/api/league/pick", json={"team": TEAMS[i]})
        doc = store.get()
    assert store.get()["status"] == "done"
    r = n.post("/api/league/restart")
    assert r.status_code == 200 and r.json()["status"] == "lobby"


def test_completing_draft_writes_complete_snapshot(api, store):
    n, _ = login(api, "Nate Robinson")
    n.post("/api/league/randomize")
    doc = store.get()
    for i in range(30):
        who = name_for_slot(doc, PICK_ORDER[i])
        c, _ = login(api, who)
        r = c.post("/api/league/pick", json={"team": TEAMS[i]})
        doc = store.get()
    assert r.json()["status"] == "done"
    snaps = store.list_snapshots()
    assert len(snaps) == 1
    assert snaps[0]["reason"] == "complete"
    assert snaps[0]["n_picks"] == 30


def test_login_cookie_max_age_is_season_long(api):
    r = api.post("/api/login", json={"name": "Nate Robinson", "pin": PIN})
    set_cookie_header = r.headers.get("set-cookie", "")
    assert "wp_session" in set_cookie_header
    m = re.search(r"[Mm]ax-[Aa]ge=(\d+)", set_cookie_header)
    assert m is not None
    assert int(m.group(1)) >= 180 * 24 * 3600


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


def test_standings_response_has_fetched_at(api, store, monkeypatch):
    from winspool import standings
    import pandas as pd
    empty = pd.DataFrame([], columns=["game_type", "home_team", "away_team",
                                       "home_score", "away_score"])
    monkeypatch.setattr(standings, "_load_schedule", lambda: empty)
    n, _ = login(api, "Nate Robinson")
    r = n.get("/api/standings").json()
    assert isinstance(r["fetched_at"], float)
    assert r["stale"] is False


def test_internal_refresh_standings_requires_token(api, store, monkeypatch):
    from winspool import standings
    import pandas as pd
    df = pd.DataFrame([("REG", "KC", "BUF", 27, 20)],
                       columns=["game_type", "home_team", "away_team",
                                "home_score", "away_score"])
    monkeypatch.setattr(standings, "_load_schedule", lambda: df)

    monkeypatch.delenv("REFRESH_TOKEN", raising=False)
    r = api.post("/internal/refresh-standings")
    assert r.status_code == 503

    monkeypatch.setenv("REFRESH_TOKEN", "secret-token")
    r = api.post("/internal/refresh-standings")
    assert r.status_code == 403
    r = api.post("/internal/refresh-standings", headers={"X-Refresh-Token": "wrong"})
    assert r.status_code == 403

    r = api.post("/internal/refresh-standings", headers={"X-Refresh-Token": "secret-token"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["fetched_at"], float)
    assert body["teams_with_wins"] == 1
    assert store.get_standings()["wins"]["KC"] == 1


def test_internal_refresh_standings_503_on_failure_keeps_previous_wins(api, store, monkeypatch):
    from winspool import standings

    prev = {"wins": {t: 0 for t in standings.TEAMS}, "fetched_at": 111.0,
            "ok": True, "error": None}
    prev["wins"]["KC"] = 5
    store.put_standings(prev)

    def boom():
        raise RuntimeError("nflverse down")
    monkeypatch.setattr(standings, "_load_schedule", boom)
    monkeypatch.setenv("REFRESH_TOKEN", "secret-token")

    r = api.post("/internal/refresh-standings", headers={"X-Refresh-Token": "secret-token"})
    assert r.status_code == 503
    body = r.json()
    assert body["ok"] is False
    assert body["fetched_at"] == 111.0
    assert "nflverse down" in body["error"]

    stored = store.get_standings()
    assert stored["ok"] is False
    assert stored["wins"]["KC"] == 5
    assert stored["fetched_at"] == 111.0


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


def test_login_cookie_not_secure_on_plain_http_dev(api, monkeypatch):
    monkeypatch.delenv("WINSPOOL_BEHIND_PROXY", raising=False)
    r = api.post("/api/login", json={"name": "Nate Robinson", "pin": PIN})
    assert "secure" not in r.headers.get("set-cookie", "").lower()


def test_login_cookie_secure_behind_cloudflare_tunnel(api, monkeypatch):
    """On the Pi the browser still talks HTTPS to Cloudflare, so the session
    cookie must be marked secure even though uvicorn is serving plain HTTP."""
    monkeypatch.setenv("WINSPOOL_BEHIND_PROXY", "1")
    r = api.post("/api/login", json={"name": "Nate Robinson", "pin": PIN})
    assert "secure" in r.headers.get("set-cookie", "").lower()


# --- boot-time guard: a real deployment must bring its own session secret ---

def test_configured_store_without_session_secret_refuses_to_boot(monkeypatch):
    monkeypatch.setenv("STORE", "sqlite")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        server.seed_dev_league()


def test_configured_store_with_secret_seeds_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("STORE", "sqlite")
    monkeypatch.setenv("SESSION_SECRET", "real-secret")
    s = SqliteStore(tmp_path / "l.db")
    set_store(s)
    try:
        server.seed_dev_league()
        with pytest.raises(LookupError):
            s.get()          # no dev league conjured into a real store
    finally:
        set_store(None)
        s.close()


def test_local_dev_still_gets_a_default_secret(monkeypatch):
    monkeypatch.delenv("STORE", raising=False)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    s = InMemoryStore()
    set_store(s)
    try:
        server.seed_dev_league()
        assert os.environ["SESSION_SECRET"] == "dev-secret"
        assert s.get()["players"]        # dev league seeded
    finally:
        set_store(None)



def _complete_draft(api, store):
    n, _ = login(api, "Nate Robinson")
    n.post("/api/league/randomize")
    doc = store.get()
    for i in range(30):
        who = name_for_slot(doc, PICK_ORDER[i])
        c, _ = login(api, who)
        c.post("/api/league/pick", json={"team": TEAMS[i]})
        doc = store.get()
    assert doc["status"] == "done"
    return n


def test_projections_409_until_draft_is_done(api, store):
    c, _ = login(api, "Mitch Fischer")
    assert c.get("/api/league/projections").status_code == 409
    assert c.get("/api/league/sample_season?seed=1").status_code == 409


def test_projections_readable_by_any_player_and_keyed_by_name(api, store):
    _complete_draft(api, store)
    c, _ = login(api, "Mitch Fischer")
    r = c.get("/api/league/projections")
    assert r.status_code == 200
    body = r.json()
    rows = body["rows"]
    assert sorted(x["player"] for x in rows) == sorted(PLAYERS)
    assert body["n_sims"] > 0 and len(body["x"]) > 0
    view = league.view(store.get())
    for row in rows:
        codes = [t["code"] for t in row["teams"]]
        assert sorted(codes) == sorted(view["rosters"][row["player"]])
        assert len(row["dist"]) == len(body["x"])
        assert abs(sum(row["dist"]) - 1) < 1e-3
        assert row["p10"] <= row["p90"]
        assert abs(sum(t["exp_wins"] for t in row["teams"]) - row["exp_wins"]) < 0.2
    # >= rule: ties count for both, so the sum is at least 1
    assert 0.99 <= sum(x["pwin"] for x in rows) <= 1.2
    # sorted by chance to win, descending
    assert [x["pwin"] for x in rows] == sorted((x["pwin"] for x in rows), reverse=True)


def test_sample_season_is_seeded_and_names_a_winner(api, store):
    _complete_draft(api, store)
    c, _ = login(api, "Eric Whitley")
    a = c.get("/api/league/sample_season?seed=7").json()
    b = c.get("/api/league/sample_season?seed=7").json()
    assert a == b
    assert set(a["winners"]) <= set(PLAYERS) and len(a["winners"]) >= 1
    top = a["standings"][0]["total_wins"]
    assert all(r["total_wins"] <= top for r in a["standings"])
    assert all(r["total_wins"] == top for r in a["standings"] if r["player"] in a["winners"])


def test_projections_do_not_write_to_store(api, store):
    _complete_draft(api, store)
    before = store.get()
    c, _ = login(api, "Logan Borgelt")
    c.get("/api/league/projections")
    c.get("/api/league/sample_season?seed=3")
    assert store.get() == before


# --- Public read-only access once the draft is done -------------------------

PUBLIC_READS = ["/api/league", "/api/standings", "/api/messages",
                "/api/league/projections", "/api/league/sample_season?seed=1"]


def test_anonymous_reads_401_until_draft_is_done(api, store):
    for path in PUBLIC_READS:
        assert api.get(path).status_code == 401, path
    assert api.get("/api/me").status_code == 401


def test_anonymous_reads_allowed_after_draft(api, store, monkeypatch):
    monkeypatch.setattr(api_league._standings, "refresh_standings",
                        lambda s: {"wins": {t: 0 for t in TEAMS}, "fetched_at": time.time(), "ok": True, "error": None})
    _complete_draft(api, store)
    anon = TestClient(server.app)
    for path in PUBLIC_READS:
        assert anon.get(path).status_code == 200, path
    assert anon.get("/api/league").json()["status"] == "done"
    assert anon.get("/api/me").status_code == 401


def test_anonymous_cannot_write_after_draft(api, store):
    _complete_draft(api, store)
    anon = TestClient(server.app)
    assert anon.post("/api/messages", json={"text": "hi"}).status_code == 401
    assert anon.post("/api/league/undo").status_code == 401
    assert anon.post("/api/standings/override", json={"team": "KC", "wins": 1}).status_code == 401
    assert anon.post("/api/league/pick", json={"team": "KC"}).status_code == 401


# --- Pre-season projections are frozen once computed ------------------------

def test_projections_frozen_after_first_computation(api, store):
    _complete_draft(api, store)
    c, _ = login(api, "Logan Borgelt")
    a = c.get("/api/league/projections").json()
    assert a["locked_at"] > 0
    # Stored, and served verbatim afterwards even if the store's copy is edited.
    frozen = store.get_preseason()
    assert frozen["locked_at"] == a["locked_at"]
    store.put_preseason({**frozen, "n_sims": 1})
    b = c.get("/api/league/projections").json()
    assert b["n_sims"] == 1 and b["locked_at"] == a["locked_at"]


def test_projections_not_frozen_before_draft_is_done(api, store):
    c, _ = login(api, "Logan Borgelt")
    assert c.get("/api/league/projections").status_code == 409
    assert store.get_preseason() is None


# --- Live projection ----------------------------------------------------------

def _inseason_df():
    import pandas as pd
    cols = ["week", "game_type", "home_team", "away_team", "home_score", "away_score"]
    rows = [(1, "REG", h, a, 20, 10) for h, a in zip(TEAMS[::2], TEAMS[1::2])]     # week 1 final
    rows += [(2, "REG", a, h, None, None) for h, a in zip(TEAMS[::2], TEAMS[1::2])]  # week 2 open
    return pd.DataFrame(rows, columns=cols)


@pytest.fixture
def live_env(monkeypatch, tmp_path):
    from winspool import live, standings
    monkeypatch.setattr(standings, "_load_schedule", _inseason_df)
    monkeypatch.setattr(live, "_LAST_SCHEDULE", None)
    monkeypatch.setattr(api_league, "LIVE_CACHE_DIR", "tests/fixtures")
    monkeypatch.setattr(api_league, "LIVE_N_SEASONS", 300)
    monkeypatch.setenv("REFRESH_TOKEN", "tok")
    return live


def test_live_404_until_refreshed_and_public_after_draft(api, store, live_env):
    _complete_draft(api, store)
    anon = TestClient(server.app)
    assert anon.get("/api/league/live").status_code == 404
    r = api.post("/internal/refresh-live", headers={"X-Refresh-Token": "tok"})
    assert r.status_code == 200, r.text
    body = anon.get("/api/league/live").json()
    assert body["week"] == 2
    assert sorted(x["player"] for x in body["rows"]) == sorted(PLAYERS)
    # six teams each play once; a game between two of a player's own teams is one locked chip
    assert all(sum(2 if g["lock"] else 1 for g in r["games"]) == 6 for r in body["this_week"])
    assert store.get_live()["week"] == 2
    # The model's own per-game read is logged too, or the completed-week
    # model-against-market comparison has nothing to score.
    model = [r for r in store.all_odds() if r["source"] == "model"]
    assert model and model[-1]["games"]
    assert all(g["p_home"] is not None for g in model[-1]["games"])


def test_live_and_weeks_401_before_draft_done(api, store, live_env):
    assert api.get("/api/league/live").status_code == 401
    assert api.get("/api/league/weeks").status_code == 401


def test_refresh_live_token_gate(api, store, live_env, monkeypatch):
    assert api.post("/internal/refresh-live").status_code == 403
    monkeypatch.delenv("REFRESH_TOKEN")
    assert api.post("/internal/refresh-live").status_code == 503


def test_weekly_snapshot_written_once_per_week(api, store, live_env):
    _complete_draft(api, store)
    h = {"X-Refresh-Token": "tok"}
    assert api.post("/internal/refresh-live", headers=h).status_code == 200
    first = store.list_weeks()
    assert [w["week"] for w in first] == [2]
    # Second refresh in the same week: live doc updates, snapshot does not.
    assert api.post("/internal/refresh-live", headers=h).status_code == 200
    assert store.list_weeks()[0]["computed_at"] == first[0]["computed_at"]
    weeks = api.get("/api/league/weeks").json()
    assert weeks[0]["week"] == 2
    assert set(weeks[0]["rows"][0]) == {"player", "pwin", "exp_wins"}
    # per-source views ride along so the card can show a delta under any lens
    assert list(weeks[0]["views"]) == ["blend", "vegas", "fpi", "sagarin", "massey"]
    assert set(weeks[0]["views"]["fpi"][0]) == {"player", "pwin", "exp_wins"}
    assert weeks[0]["views"]["blend"] == weeks[0]["rows"]


def test_refresh_live_reuses_last_schedule_on_fetch_failure(api, store, live_env, monkeypatch):
    from winspool import standings
    _complete_draft(api, store)
    h = {"X-Refresh-Token": "tok"}
    assert api.post("/internal/refresh-live", headers=h).status_code == 200

    def boom():
        raise RuntimeError("network down")
    monkeypatch.setattr(standings, "_load_schedule", boom)
    r = api.post("/internal/refresh-live", headers=h)
    assert r.status_code == 200 and r.json()["week"] == 2


def test_refresh_live_503_with_no_schedule_at_all(api, store, live_env, monkeypatch):
    from winspool import standings
    _complete_draft(api, store)

    def boom():
        raise RuntimeError("network down")
    monkeypatch.setattr(standings, "_load_schedule", boom)
    r = api.post("/internal/refresh-live", headers={"X-Refresh-Token": "tok"})
    assert r.status_code == 503
    assert api.get("/api/league/live").status_code == 404


def test_asset_and_html_cache_headers(api):
    """A deploy has to take effect on the next page load. index.html names the
    bundle, so it must revalidate; the bundle's name carries its content hash,
    so it can be kept forever. Getting this backwards serves the old app."""
    client = api
    r = client.get("/api/league")
    assert r.headers["cache-control"] == "no-store"

    from winspool import server as _server
    dist = _server._DIST
    if not dist.exists():
        pytest.skip("no built frontend to serve")
    assert client.get("/").headers["cache-control"] == "no-cache"
    asset = next(iter((dist / "assets").glob("*.js")), None)
    if asset is None:
        pytest.skip("no built assets")
    r = client.get(f"/assets/{asset.name}")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


# ---- login throttling ----

@pytest.fixture
def fast_throttle(monkeypatch):
    """A throttle tuned so the backoff is observable without slow tests:
    two free attempts, then a penalty capped at 50ms."""
    from winspool.throttle import Throttle
    t = Throttle(free=2, cap=0.05)
    monkeypatch.setattr(api_league, "_LOGIN_THROTTLE", t)
    return t


def test_repeated_wrong_pins_are_throttled(api, fast_throttle):
    for _ in range(3):
        assert login(api, "Mitch Fischer", "nope")[1].status_code == 401
    r = login(api, "Mitch Fischer", "nope")[1]
    assert r.status_code == 429
    assert float(r.headers["retry-after"]) > 0


def test_throttle_rejects_the_correct_pin_too(api, fast_throttle):
    """The penalty is applied before the PIN is checked, so a guesser learns
    nothing from the response while locked out."""
    for _ in range(3):
        login(api, "Mitch Fischer", "nope")
    assert login(api, "Mitch Fischer", PIN)[1].status_code == 429


def test_login_succeeds_again_once_the_penalty_lapses(api, fast_throttle):
    for _ in range(3):
        login(api, "Mitch Fischer", "nope")
    assert login(api, "Mitch Fischer", PIN)[1].status_code == 429
    time.sleep(0.06)
    assert login(api, "Mitch Fischer", PIN)[1].status_code == 200


def test_a_good_login_clears_the_failure_count(api, fast_throttle):
    login(api, "Mitch Fischer", "nope")
    login(api, "Mitch Fischer", "nope")
    assert login(api, "Mitch Fischer", PIN)[1].status_code == 200
    # Counter reset, so the free attempts are available again.
    assert login(api, "Mitch Fischer", "nope")[1].status_code == 401


def test_throttling_one_player_does_not_lock_out_another(api, fast_throttle):
    for _ in range(4):
        login(api, "Mitch Fischer", "nope")
    assert login(api, "Mitch Fischer", PIN)[1].status_code == 429
    assert login(api, "Eric Whitley", PIN)[1].status_code == 200


def test_unknown_names_are_throttled_without_burning_a_real_players_budget(api, fast_throttle):
    for _ in range(4):
        login(api, "Nobody", "nope")
    assert login(api, "Nobody", "nope")[1].status_code == 429
    assert login(api, "Mitch Fischer", PIN)[1].status_code == 200


def test_oversized_login_fields_are_rejected_before_they_reach_the_throttle(api, fast_throttle):
    """The name becomes a throttle-table key, so it must be bounded."""
    r = login(api, "x" * 10_000, "y" * 10_000)[1]
    assert r.status_code == 422
    assert len(fast_throttle) == 0


def test_refresh_odds_requires_the_token(api, store, monkeypatch):
    monkeypatch.setenv("REFRESH_TOKEN", "secret")
    assert api.post("/internal/refresh-odds").status_code == 403
    assert api.post("/internal/refresh-odds",
                    headers={"X-Refresh-Token": "wrong"}).status_code == 403


def test_week_requires_a_viewer(api):
    assert api.get("/api/week").status_code in (401, 403)


def test_week_rejects_an_out_of_range_week(api, store):
    c, _ = login(api, PLAYERS[0])
    assert c.get("/api/week?week=0").status_code == 422
    assert c.get("/api/week?week=19").status_code == 422


def test_week_is_503_before_a_projection_exists(api, store):
    c, _ = login(api, PLAYERS[0])
    assert c.get("/api/week").status_code == 503


def test_week_serves_the_current_week_from_the_live_doc(api, store):
    c, _ = login(api, PLAYERS[0])
    store.put_live({"week": 1, "computed_at": 0.0,
                     "rows": [{"player": PLAYERS[0], "pwin": 0.11}], "games": []})
    body = c.get("/api/week").json()
    assert body["week"] == 1 and body["state"] in ("live", "final")
    assert isinstance(body["games"], list)
    assert {p["name"] for p in body["players"]}

    # A past week must come from what was RECORDED at the time, not from a
    # recompute against the live doc. Give the stored week-2 record a pwin
    # for PLAYERS[0] that could only have come from that record, not the
    # live doc above (0.11) — this fails if the route ever falls through to
    # the live doc for a past week.
    store.put_week(2, {"week": 2, "computed_at": 0.0,
                        "rows": [{"player": PLAYERS[0], "pwin": 0.87}], "games": []})
    past = c.get("/api/week?week=2").json()
    assert past["week"] == 2
    mine = next(p for p in past["players"] if p["name"] == PLAYERS[0])
    assert mine["pwin"] == 0.87

    # No recorded document for week 3, and it isn't the current live week
    # either: 404, not a silent fall-through to the live doc.
    assert c.get("/api/week?week=3").status_code == 404
