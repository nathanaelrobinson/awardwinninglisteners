# Live Draft + Standings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five players log in, randomize slots, run the 30-pick draft live from their own devices with a message feed, and follow regular-season wins per roster, replacing the league Google Sheet.

**Architecture:** The existing FastAPI + React app gains a `league` state machine over a single Firestore document (abstracted behind a `Store` protocol with an in-memory implementation for tests), name+PIN cookie auth, a messages subcollection, and a standings module that counts wins from `nfl_data_py`. The React app gets Login, Lobby, Draft, and Standings screens; the old app becomes a commissioner-only Practice tab. Deployed to Cloud Run (one instance) in GCP project `snowpack-pika` (codename, on purpose).

**Tech Stack:** Python 3.12+, FastAPI, google-cloud-firestore, nfl_data_py, pytest + httpx TestClient; React 19 + Vite + TypeScript; Cloud Run via `gcloud run deploy --source`.

**Spec:** `docs/superpowers/specs/2026-09-07-live-draft-design.md`

## Global Constraints

- UI copy: every literal string must justify itself. No explanatory sentences. Column headers and button labels only. (Spec: "Design principle: simplicity".)
- Players, exactly as displayed: `Nate Robinson` (commissioner), `Evan Goguillon-Bader`, `Logan Borgelt`, `Eric Whitley`, `Mitch Fischer`.
- 5 players × 6 teams = 30 picks; pick order is `winspool.draft.PICK_ORDER`, never changed.
- Wins: regular season only (`game_type == "REG"`), ties count 0.
- Cloud Run: `--min-instances=1 --max-instances=1 --memory=2Gi --cpu=2`, region `us-west1`, project `snowpack-pika`.
- Never commit the PIN or `SESSION_SECRET`.
- Never push to `main`. Work on branch `live-draft`.
- Run tests with `uv run pytest -q`. Build web with `cd web && npm run build`.

---

## File map

Backend (new):
- `src/winspool/store.py` — `Store` protocol, `InMemoryStore`, `FirestoreStore`, `get_store()/set_store()`.
- `src/winspool/league.py` — pure functions over the league dict: `new_league`, `check_pin`, `randomize`, `reset`, `pick`, `undo`, `current_slot`, `view`.
- `src/winspool/auth.py` — cookie sign/verify, FastAPI dependencies `current_user`, `require_commissioner`.
- `src/winspool/api_league.py` — APIRouter with all `/api/login`, `/api/me`, `/api/league/*`, `/api/messages`, `/api/standings*` routes.
- `src/winspool/standings.py` — `wins_from_schedule(df) -> dict[str,int]`, `fetch_wins()` with 1h cache, `apply_overrides`.

Backend (modify):
- `src/winspool/server.py` — include router, gate optimizer routes, `STORE` env selection, seed dev league.
- `src/winspool/cli.py` — `league-init` subcommand.
- `pyproject.toml` — add `google-cloud-firestore`.

Frontend (new):
- `web/src/league.ts` — API client + types for league/messages/standings.
- `web/src/components/Login.tsx`, `Lobby.tsx`, `PickStrip.tsx`, `DraftBoard.tsx`, `LiveRosters.tsx`, `Feed.tsx`, `LiveDraft.tsx`, `Standings.tsx`.
- `web/src/live.css` — styles for the new screens.

Frontend (modify):
- `web/src/App.tsx` — becomes the router: Login → (Lobby | Draft | Standings | Practice). The existing App body moves to `web/src/components/Practice.tsx` unchanged.
- `web/src/main.tsx` — import `live.css`.

Deploy (new):
- `Dockerfile`, `.dockerignore`, `scripts/deploy.sh`.

Tests (new): `tests/test_league.py`, `tests/test_api_league.py`, `tests/test_standings.py`.

---

### Task 1: Store protocol + league state machine

**Files:**
- Create: `src/winspool/store.py`
- Create: `src/winspool/league.py`
- Test: `tests/test_league.py`

**Interfaces:**
- Produces: `InMemoryStore(doc: dict | None)`, `.get() -> dict`, `.update(fn) -> dict`, `.add_message(by, text) -> dict`, `.messages(since: float | None) -> list[dict]`.
- Produces: `league.new_league(players, commissioner, pin) -> dict`; `check_pin(doc, pin) -> bool`; `randomize(doc, rng) -> dict`; `reset(doc) -> dict`; `pick(doc, name, team, ts) -> dict`; `undo(doc) -> dict`; `current_slot(doc) -> int | None`; `slot_of(doc, name) -> int | None`; `view(doc) -> dict`. All raise `LeagueError(status, detail)` on invalid transitions.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_league.py
import random
import pytest
from winspool import league
from winspool.league import LeagueError
from winspool.draft import PICK_ORDER

PLAYERS = ["Nate Robinson", "Evan Goguillon-Bader", "Logan Borgelt",
           "Eric Whitley", "Mitch Fischer"]


def fresh():
    return league.new_league(PLAYERS, "Nate Robinson", "awardwinninglisteners")


def drafting():
    return league.randomize(fresh(), random.Random(1))


def name_for_slot(doc, slot):
    return next(n for n, s in doc["slots"].items() if s == slot)


def test_new_league_shape():
    d = fresh()
    assert d["status"] == "lobby"
    assert d["players"] == PLAYERS
    assert d["slots"] is None
    assert d["picks"] == []
    assert d["overrides"] == {}
    assert "awardwinninglisteners" not in str(d)  # only the hash is stored


def test_check_pin():
    d = fresh()
    assert league.check_pin(d, "awardwinninglisteners")
    assert not league.check_pin(d, "wrong")


def test_randomize_assigns_permutation_and_starts_draft():
    d = drafting()
    assert d["status"] == "drafting"
    assert sorted(d["slots"].values()) == [1, 2, 3, 4, 5]
    assert set(d["slots"]) == set(PLAYERS)


def test_randomize_only_in_lobby():
    with pytest.raises(LeagueError) as e:
        league.randomize(drafting(), random.Random(1))
    assert e.value.status == 409


def test_reset_returns_to_lobby_only_before_picks():
    d = league.reset(drafting())
    assert d["status"] == "lobby" and d["slots"] is None
    d = drafting()
    d = league.pick(d, name_for_slot(d, PICK_ORDER[0]), "KC", 1.0)
    with pytest.raises(LeagueError):
        league.reset(d)


def test_pick_by_current_player_appends():
    d = drafting()
    who = name_for_slot(d, PICK_ORDER[0])
    d = league.pick(d, who, "KC", 1.0)
    assert d["picks"] == [{"n": 1, "slot": PICK_ORDER[0], "team": "KC", "by": who, "ts": 1.0}]
    assert league.current_slot(d) == PICK_ORDER[1]


def test_pick_out_of_turn_409():
    d = drafting()
    wrong = name_for_slot(d, PICK_ORDER[1])
    with pytest.raises(LeagueError) as e:
        league.pick(d, wrong, "KC", 1.0)
    assert e.value.status == 409


def test_pick_taken_team_409():
    d = drafting()
    d = league.pick(d, name_for_slot(d, PICK_ORDER[0]), "KC", 1.0)
    with pytest.raises(LeagueError) as e:
        league.pick(d, name_for_slot(d, PICK_ORDER[1]), "kc", 2.0)
    assert e.value.status == 409


def test_pick_unknown_team_400():
    d = drafting()
    with pytest.raises(LeagueError) as e:
        league.pick(d, name_for_slot(d, PICK_ORDER[0]), "XXX", 1.0)
    assert e.value.status == 400


def test_pick_in_lobby_409():
    with pytest.raises(LeagueError):
        league.pick(fresh(), PLAYERS[0], "KC", 1.0)


def test_thirty_picks_finishes_and_undo_reopens():
    from winspool.teams import TEAMS
    d = drafting()
    for i in range(30):
        d = league.pick(d, name_for_slot(d, PICK_ORDER[i]), TEAMS[i], float(i))
    assert d["status"] == "done"
    assert league.current_slot(d) is None
    with pytest.raises(LeagueError):
        league.pick(d, PLAYERS[0], TEAMS[30], 99.0)
    d = league.undo(d)
    assert d["status"] == "drafting" and len(d["picks"]) == 29


def test_undo_with_no_picks_409():
    with pytest.raises(LeagueError):
        league.undo(drafting())


def test_view_has_rosters_by_name_and_no_hash():
    d = drafting()
    who = name_for_slot(d, PICK_ORDER[0])
    d = league.pick(d, who, "KC", 1.0)
    v = league.view(d)
    assert v["rosters"][who] == ["KC"]
    assert v["current_slot"] == PICK_ORDER[1]
    assert v["current_player"] == name_for_slot(d, PICK_ORDER[1])
    assert v["pick_order"] == PICK_ORDER
    assert "pin_hash" not in v and "pin_salt" not in v


def test_inmemory_store_update_is_atomic_and_returns_new_doc():
    from winspool.store import InMemoryStore
    s = InMemoryStore(fresh())
    out = s.update(lambda d: league.randomize(d, random.Random(3)))
    assert out["status"] == "drafting"
    assert s.get()["status"] == "drafting"


def test_inmemory_store_messages():
    from winspool.store import InMemoryStore
    s = InMemoryStore(fresh())
    m1 = s.add_message("Mitch Fischer", "lol")
    m2 = s.add_message("Nate Robinson", "ok")
    assert [m["text"] for m in s.messages(None)] == ["lol", "ok"]
    assert [m["text"] for m in s.messages(m1["ts"])] == ["ok"]
    assert m2["by"] == "Nate Robinson" and "id" in m2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_league.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'winspool.league'`

- [ ] **Step 3: Implement `league.py`**

```python
# src/winspool/league.py
"""Pure state machine for the live league. Every function takes the league
dict and returns a NEW dict (never mutates), so the store can wrap it in a
transaction and tests never touch Firestore."""
import copy
import hashlib
import secrets

from .draft import PICK_ORDER
from .teams import N_PICKS, N_PLAYERS, TEAMS, resolve


class LeagueError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _hash(pin: str, salt: str) -> str:
    return hashlib.sha256((salt + pin).encode()).hexdigest()


def new_league(players, commissioner, pin):
    players = list(players)
    if len(players) != N_PLAYERS or len(set(players)) != N_PLAYERS:
        raise LeagueError(400, f"need {N_PLAYERS} distinct players")
    if commissioner not in players:
        raise LeagueError(400, "commissioner must be a player")
    salt = secrets.token_hex(8)
    return {
        "players": players,
        "commissioner": commissioner,
        "pin_salt": salt,
        "pin_hash": _hash(pin, salt),
        "slots": None,
        "status": "lobby",
        "picks": [],
        "overrides": {},
        "logged_in": {},
    }


def check_pin(doc, pin) -> bool:
    return secrets.compare_digest(_hash(pin or "", doc["pin_salt"]), doc["pin_hash"])


def current_slot(doc):
    if doc["status"] != "drafting":
        return None
    n = len(doc["picks"])
    return PICK_ORDER[n] if n < N_PICKS else None


def slot_of(doc, name):
    return (doc["slots"] or {}).get(name)


def _name_of_slot(doc, slot):
    for n, s in (doc["slots"] or {}).items():
        if s == slot:
            return n
    return None


def randomize(doc, rng):
    if doc["status"] != "lobby":
        raise LeagueError(409, "draft already started")
    d = copy.deepcopy(doc)
    order = list(range(1, N_PLAYERS + 1))
    rng.shuffle(order)
    d["slots"] = {name: order[i] for i, name in enumerate(d["players"])}
    d["status"] = "drafting"
    return d


def reset(doc):
    if doc["picks"]:
        raise LeagueError(409, "picks already made")
    d = copy.deepcopy(doc)
    d["slots"] = None
    d["status"] = "lobby"
    return d


def pick(doc, name, team, ts):
    if doc["status"] != "drafting":
        raise LeagueError(409, "not drafting")
    code = resolve(team)
    if code is None:
        raise LeagueError(400, f"unknown team {team!r}")
    slot = current_slot(doc)
    if slot is None or slot_of(doc, name) != slot:
        raise LeagueError(409, "not your turn")
    if any(p["team"] == code for p in doc["picks"]):
        raise LeagueError(409, f"{code} already taken")
    d = copy.deepcopy(doc)
    d["picks"].append({"n": len(d["picks"]) + 1, "slot": slot, "team": code,
                       "by": name, "ts": ts})
    if len(d["picks"]) >= N_PICKS:
        d["status"] = "done"
    return d


def undo(doc):
    if not doc["picks"]:
        raise LeagueError(409, "nothing to undo")
    d = copy.deepcopy(doc)
    d["picks"].pop()
    d["status"] = "drafting"
    return d


def view(doc):
    """What clients render. Strips secrets, adds derived fields."""
    rosters = {n: [] for n in doc["players"]}
    for p in doc["picks"]:
        rosters[p["by"]].append(p["team"])
    slot = current_slot(doc)
    return {
        "players": doc["players"],
        "commissioner": doc["commissioner"],
        "slots": doc["slots"],
        "status": doc["status"],
        "picks": doc["picks"],
        "pick_order": PICK_ORDER,
        "rosters": rosters,
        "current_slot": slot,
        "current_player": _name_of_slot(doc, slot) if slot else None,
        "logged_in": doc.get("logged_in", {}),
        "teams": TEAMS,
    }
```

- [ ] **Step 4: Implement `store.py`**

```python
# src/winspool/store.py
"""League persistence. One league document + a messages subcollection.
InMemoryStore for tests/dev; FirestoreStore for prod (STORE=firestore)."""
import os
import threading
import time
import uuid
from typing import Callable, Protocol

LEAGUE_ID = "2026"
MSG_CAP = 200


class Store(Protocol):
    def get(self) -> dict: ...
    def update(self, fn: Callable[[dict], dict]) -> dict: ...
    def add_message(self, by: str, text: str) -> dict: ...
    def messages(self, since: float | None) -> list[dict]: ...


class InMemoryStore:
    def __init__(self, doc: dict | None = None):
        self._doc = doc
        self._msgs: list[dict] = []
        self._lock = threading.Lock()

    def get(self) -> dict:
        if self._doc is None:
            raise LookupError("league not initialized")
        return self._doc

    def put(self, doc: dict) -> None:
        with self._lock:
            self._doc = doc

    def update(self, fn):
        with self._lock:
            self._doc = fn(self.get())
            return self._doc

    def add_message(self, by, text):
        m = {"id": uuid.uuid4().hex, "by": by, "text": text, "ts": time.time()}
        with self._lock:
            self._msgs.append(m)
        return m

    def messages(self, since):
        out = [m for m in self._msgs if since is None or m["ts"] > since]
        return out[-MSG_CAP:]


class FirestoreStore:
    def __init__(self, project: str | None = None):
        from google.cloud import firestore  # imported lazily: prod-only dep
        self._fs = firestore
        self._db = firestore.Client(project=project)
        self._ref = self._db.collection("leagues").document(LEAGUE_ID)

    def get(self):
        snap = self._ref.get()
        if not snap.exists:
            raise LookupError("league not initialized")
        return snap.to_dict()

    def put(self, doc):
        self._ref.set(doc)

    def update(self, fn):
        transaction = self._db.transaction()
        ref = self._ref

        @self._fs.transactional
        def _run(tx):
            snap = ref.get(transaction=tx)
            if not snap.exists:
                raise LookupError("league not initialized")
            new = fn(snap.to_dict())
            tx.set(ref, new)
            return new

        return _run(transaction)

    def add_message(self, by, text):
        m = {"by": by, "text": text, "ts": time.time()}
        _, ref = self._ref.collection("messages").add(m)
        return {"id": ref.id, **m}

    def messages(self, since):
        q = self._ref.collection("messages").order_by("ts")
        if since is not None:
            q = q.where("ts", ">", since)
        docs = list(q.limit_to_last(MSG_CAP).get()) if since is None else list(q.limit(MSG_CAP).get())
        return [{"id": d.id, **d.to_dict()} for d in docs]


_STORE: Store | None = None


def get_store() -> Store:
    global _STORE
    if _STORE is None:
        if os.environ.get("STORE") == "firestore":
            _STORE = FirestoreStore(os.environ.get("GOOGLE_CLOUD_PROJECT"))
        else:
            _STORE = InMemoryStore()
    return _STORE


def set_store(store: Store | None) -> None:
    global _STORE
    _STORE = store
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_league.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/winspool/league.py src/winspool/store.py tests/test_league.py
git commit -m "feat(league): pure draft state machine + Store protocol (in-memory + Firestore)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Auth + league/message endpoints

**Files:**
- Create: `src/winspool/auth.py`
- Create: `src/winspool/api_league.py`
- Modify: `src/winspool/server.py` (include router; dev seed)
- Test: `tests/test_api_league.py`

**Interfaces:**
- Consumes: Task 1 (`league.*`, `store.get_store/set_store/InMemoryStore`).
- Produces: cookie `wp_session`; dependencies `current_user(request) -> str`, `require_commissioner(request) -> str`; router `api_league.router`; `server.seed_dev_league()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api_league.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_league.py -q`
Expected: FAIL (404s on /api/login, etc.)

- [ ] **Step 3: Implement `auth.py`**

```python
# src/winspool/auth.py
import hashlib
import hmac
import os

from fastapi import HTTPException, Request, Response

COOKIE = "wp_session"
MAX_AGE = 7 * 24 * 3600


def _secret() -> bytes:
    s = os.environ.get("SESSION_SECRET")
    if not s:
        raise RuntimeError("SESSION_SECRET not set")
    return s.encode()


def sign(name: str) -> str:
    mac = hmac.new(_secret(), name.encode(), hashlib.sha256).hexdigest()
    return f"{name}|{mac}"


def verify(token: str | None) -> str | None:
    if not token or "|" not in token:
        return None
    name, mac = token.rsplit("|", 1)
    good = hmac.new(_secret(), name.encode(), hashlib.sha256).hexdigest()
    return name if hmac.compare_digest(mac, good) else None


def set_cookie(resp: Response, name: str) -> None:
    resp.set_cookie(COOKIE, sign(name), max_age=MAX_AGE, httponly=True,
                    samesite="lax", secure=os.environ.get("K_SERVICE") is not None)


def current_user(request: Request) -> str:
    name = verify(request.cookies.get(COOKIE))
    if name is None:
        raise HTTPException(401, "login required")
    return name


def require_commissioner(request: Request) -> str:
    from .store import get_store
    name = current_user(request)
    if name != get_store().get()["commissioner"]:
        raise HTTPException(403, "commissioner only")
    return name
```

- [ ] **Step 4: Implement `api_league.py`**

```python
# src/winspool/api_league.py
import random
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from . import league
from .auth import current_user, require_commissioner, set_cookie
from .league import LeagueError
from .store import get_store

router = APIRouter(prefix="/api")


def _run(fn):
    try:
        return league.view(get_store().update(fn))
    except LeagueError as e:
        raise HTTPException(e.status, e.detail)
    except LookupError:
        raise HTTPException(503, "league not initialized")


class LoginReq(BaseModel):
    name: str
    pin: str


@router.post("/login")
def login(req: LoginReq, resp: Response):
    try:
        doc = get_store().get()
    except LookupError:
        raise HTTPException(503, "league not initialized")
    if req.name not in doc["players"] or not league.check_pin(doc, req.pin):
        raise HTTPException(401, "bad name or pin")
    set_cookie(resp, req.name)
    return {"name": req.name}


@router.get("/me")
def me(name: str = Depends(current_user)):
    doc = get_store().get()
    return {"name": name, "is_commissioner": name == doc["commissioner"],
            "slot": league.slot_of(doc, name)}


@router.get("/league")
def get_league(name: str = Depends(current_user)):
    def touch(d):
        d = dict(d)
        d["logged_in"] = {**d.get("logged_in", {}), name: time.time()}
        return d
    return _run(touch)


@router.post("/league/randomize")
def randomize(_: str = Depends(require_commissioner)):
    return _run(lambda d: league.randomize(d, random.SystemRandom()))


@router.post("/league/reset")
def reset(_: str = Depends(require_commissioner)):
    return _run(league.reset)


class PickReq(BaseModel):
    team: str


@router.post("/league/pick")
def pick(req: PickReq, name: str = Depends(current_user)):
    return _run(lambda d: league.pick(d, name, req.team, time.time()))


@router.post("/league/undo")
def undo(_: str = Depends(require_commissioner)):
    return _run(league.undo)


class MsgReq(BaseModel):
    text: str


@router.post("/messages")
def post_message(req: MsgReq, name: str = Depends(current_user)):
    text = req.text.strip()
    if not text or len(text) > 500:
        raise HTTPException(400, "1-500 chars")
    return get_store().add_message(name, text)


@router.get("/messages")
def get_messages(since: float | None = None, _: str = Depends(current_user)):
    return get_store().messages(since)
```

- [ ] **Step 5: Wire into `server.py`**

Add after `app.add_middleware(...)`:

```python
from .api_league import router as league_router
from .auth import require_commissioner
from . import league as _league
from .store import InMemoryStore, get_store, set_store

app.include_router(league_router)

DEV_PLAYERS = ["Nate Robinson", "Evan Goguillon-Bader", "Logan Borgelt",
               "Eric Whitley", "Mitch Fischer"]


def seed_dev_league():
    """Local dev only: STORE unset → in-memory league seeded from env."""
    if os.environ.get("STORE") == "firestore":
        return
    os.environ.setdefault("SESSION_SECRET", "dev-secret")
    store = get_store()
    if isinstance(store, InMemoryStore):
        try:
            store.get()
        except LookupError:
            players = os.environ.get("LEAGUE_PLAYERS", ",".join(DEV_PLAYERS)).split(",")
            store.put(_league.new_league(players,
                                         os.environ.get("LEAGUE_COMMISSIONER", players[0]),
                                         os.environ.get("LEAGUE_PIN", "1234")))
```

Add `import os` at the top if missing. In `_startup()` call `seed_dev_league()` after `_ensure_ready()`.

Gate the optimizer routes by adding a dependency parameter to each: `recommend`, `autosim`, `advance`, `results`, `sample_season`:

```python
@app.post("/api/recommend")
def recommend(req: RecReq, _: str = Depends(require_commissioner)):
```

(and likewise for the other four). Add `from fastapi import Depends` to the existing fastapi import. `/api/teams` stays open.

- [ ] **Step 6: Run all tests**

Run: `uv run pytest -q`
Expected: all PASS. If `tests/test_api_league.py::test_optimizer_routes_commissioner_only` fails with 200, a `Depends` is missing on one route.

- [ ] **Step 7: Commit**

```bash
git add src/winspool/auth.py src/winspool/api_league.py src/winspool/server.py tests/test_api_league.py
git commit -m "feat(api): name+PIN cookie login, live league endpoints, messages; optimizer routes commissioner-only

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Standings

**Files:**
- Create: `src/winspool/standings.py`
- Modify: `src/winspool/api_league.py` (two routes)
- Test: `tests/test_standings.py`

**Interfaces:**
- Produces: `wins_from_schedule(df: pd.DataFrame) -> dict[str, int]`; `fetch_wins(refresh=False) -> tuple[dict[str,int], bool]` (wins, stale); `apply_overrides(wins, overrides) -> dict`; routes `GET /api/standings`, `POST /api/standings/override`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_standings.py
import pandas as pd
from winspool import standings


def df(rows):
    return pd.DataFrame(rows, columns=["game_type", "home_team", "away_team",
                                       "home_score", "away_score"])


def test_wins_count_reg_only_ties_zero_unplayed_ignored():
    d = df([
        ("REG", "KC", "BUF", 27, 20),      # KC win
        ("REG", "DAL", "PHI", 17, 17),     # tie: nobody
        ("REG", "SF", "LA", None, None),   # unplayed
        ("POST", "KC", "BUF", 30, 10),     # playoffs: ignored
        ("REG", "BUF", "KC", 10, 13),      # KC win (away)
    ])
    w = standings.wins_from_schedule(d)
    assert w["KC"] == 2
    assert w["BUF"] == 0 and w["DAL"] == 0 and w["PHI"] == 0
    assert w["SF"] == 0 and w["LA"] == 0
    assert len(w) == 32  # every team present


def test_apply_overrides():
    w = {"KC": 2, "BUF": 0}
    assert standings.apply_overrides(w, {"BUF": 1})["BUF"] == 1
    assert standings.apply_overrides(w, {"BUF": 1})["KC"] == 2


def test_fetch_wins_uses_cache_and_reports_stale(monkeypatch):
    calls = []
    def fake_load():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("network")
        return df([("REG", "KC", "BUF", 27, 20)])
    monkeypatch.setattr(standings, "_load_schedule", fake_load)
    standings._CACHE.clear()
    w, stale = standings.fetch_wins()
    assert w["KC"] == 1 and stale is False
    w, stale = standings.fetch_wins()          # cached, no second call
    assert len(calls) == 1
    w, stale = standings.fetch_wins(refresh=True)  # fails → last good + stale
    assert w["KC"] == 1 and stale is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_standings.py -q`
Expected: FAIL `No module named 'winspool.standings'`

- [ ] **Step 3: Implement**

```python
# src/winspool/standings.py
"""Regular-season wins per team from nfl_data_py, cached one hour."""
import time

import pandas as pd

from .teams import TEAMS

TTL = 3600
_CACHE: dict = {}   # {"wins": dict, "ts": float}


def _load_schedule() -> pd.DataFrame:
    import nfl_data_py as nfl
    return nfl.import_schedules([2026])


def wins_from_schedule(df: pd.DataFrame) -> dict[str, int]:
    wins = {t: 0 for t in TEAMS}
    reg = df[(df["game_type"] == "REG") & df["home_score"].notna() & df["away_score"].notna()]
    for r in reg.itertuples(index=False):
        if r.home_score > r.away_score:
            wins[r.home_team] = wins.get(r.home_team, 0) + 1
        elif r.away_score > r.home_score:
            wins[r.away_team] = wins.get(r.away_team, 0) + 1
    return wins


def fetch_wins(refresh: bool = False) -> tuple[dict[str, int], bool]:
    now = time.time()
    if not refresh and _CACHE and now - _CACHE["ts"] < TTL:
        return _CACHE["wins"], False
    try:
        wins = wins_from_schedule(_load_schedule())
    except Exception:
        if _CACHE:
            return _CACHE["wins"], True
        return {t: 0 for t in TEAMS}, True
    _CACHE.update(wins=wins, ts=now)
    return wins, False


def apply_overrides(wins: dict[str, int], overrides: dict[str, int]) -> dict[str, int]:
    out = dict(wins)
    for team, w in (overrides or {}).items():
        out[team] = int(w)
    return out
```

Add to `api_league.py`:

```python
from . import standings as _standings
from .teams import resolve


@router.get("/standings")
def get_standings(refresh: int = 0, name: str = Depends(current_user)):
    doc = get_store().get()
    if refresh and name != doc["commissioner"]:
        refresh = 0
    wins, stale = _standings.fetch_wins(refresh=bool(refresh))
    wins = _standings.apply_overrides(wins, doc.get("overrides", {}))
    rosters = league.view(doc)["rosters"]
    rows = [{"player": p,
             "teams": [{"code": t, "wins": wins[t]} for t in teams],
             "total": sum(wins[t] for t in teams)}
            for p, teams in rosters.items()]
    rows.sort(key=lambda r: r["total"], reverse=True)
    return {"rows": rows, "stale": stale, "overrides": doc.get("overrides", {})}


class OverrideReq(BaseModel):
    team: str
    wins: int | None   # None clears


@router.post("/standings/override")
def set_override(req: OverrideReq, _: str = Depends(require_commissioner)):
    code = resolve(req.team)
    if code is None:
        raise HTTPException(400, "unknown team")
    def fn(d):
        d = dict(d)
        ov = dict(d.get("overrides", {}))
        if req.wins is None:
            ov.pop(code, None)
        else:
            ov[code] = req.wins
        d["overrides"] = ov
        return d
    _run(fn)
    return {"overrides": get_store().get()["overrides"]}
```

Add to `tests/test_api_league.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/winspool/standings.py src/winspool/api_league.py tests/test_standings.py tests/test_api_league.py
git commit -m "feat(standings): regular-season wins from nfl_data_py with 1h cache + commissioner overrides

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `league-init` CLI + Firestore dependency

**Files:**
- Modify: `src/winspool/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_cli.py` (append)

**Interfaces:**
- Produces: `winspool league-init --players "A,B,C,D,E" --commissioner "A" [--pin X | LEAGUE_PIN] [--force]`. Writes the league doc via `get_store().put(...)`.

- [ ] **Step 1: Failing test**

Append to `tests/test_cli.py`:

```python
def test_league_init_writes_doc_and_refuses_overwrite_with_picks(monkeypatch):
    from winspool import cli, league
    from winspool.store import InMemoryStore, set_store
    s = InMemoryStore()
    set_store(s)
    monkeypatch.setenv("LEAGUE_PIN", "pw")
    players = "Nate Robinson,Evan Goguillon-Bader,Logan Borgelt,Eric Whitley,Mitch Fischer"
    cli.main(["league-init", "--players", players, "--commissioner", "Nate Robinson"])
    d = s.get()
    assert d["status"] == "lobby" and league.check_pin(d, "pw")
    # simulate a pick then refuse re-init without --force
    d["picks"].append({"n": 1, "slot": 1, "team": "KC", "by": "Nate Robinson", "ts": 1})
    s.put(d)
    import pytest
    with pytest.raises(SystemExit):
        cli.main(["league-init", "--players", players, "--commissioner", "Nate Robinson"])
    cli.main(["league-init", "--players", players, "--commissioner", "Nate Robinson", "--force"])
    assert s.get()["picks"] == []
    set_store(None)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli.py -q -k league_init`
Expected: FAIL (argparse error: invalid choice 'league-init')

- [ ] **Step 3: Implement**

In `src/winspool/cli.py`, add a subparser next to the others:

```python
    li = sub.add_parser("league-init")
    li.add_argument("--players", required=True, help="comma-separated, 5 names")
    li.add_argument("--commissioner", required=True)
    li.add_argument("--pin", default=None, help="or set LEAGUE_PIN")
    li.add_argument("--force", action="store_true")
```

And in the dispatch section:

```python
    if args.cmd == "league-init":
        import os, sys
        from . import league
        from .store import get_store
        pin = args.pin or os.environ.get("LEAGUE_PIN")
        if not pin:
            sys.exit("--pin or LEAGUE_PIN required")
        store = get_store()
        try:
            existing = store.get()
        except LookupError:
            existing = None
        if existing and existing.get("picks") and not args.force:
            sys.exit("league has picks; use --force to wipe")
        store.put(league.new_league([p.strip() for p in args.players.split(",")],
                                    args.commissioner, pin))
        print("league initialized")
        return
```

Add `"google-cloud-firestore"` to `dependencies` in `pyproject.toml`, then `uv pip install -e ".[dev]"`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/winspool/cli.py pyproject.toml uv.lock tests/test_cli.py
git commit -m "feat(cli): league-init writes the league doc; add google-cloud-firestore

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Frontend client + Login + Lobby + App routing

**Files:**
- Create: `web/src/league.ts`, `web/src/components/Login.tsx`, `web/src/components/Lobby.tsx`, `web/src/components/Practice.tsx`, `web/src/live.css`
- Modify: `web/src/App.tsx`, `web/src/main.tsx`

**Interfaces:**
- Produces: `league.ts` exports `Me`, `LeagueView`, `Message`, `StandingsResponse`, and functions `login(name, pin)`, `getMe()`, `getLeague()`, `randomize()`, `resetDraft()`, `pickTeam(code)`, `undoPick()`, `getMessages(since?)`, `postMessage(text)`, `getStandings(refresh?)`, `setOverride(team, wins|null)`.
- `Practice.tsx` is the old `App` component body, exported default, unchanged in behavior.

- [ ] **Step 1: Move the old app to `Practice.tsx`**

```bash
cd web/src && cp App.tsx components/Practice.tsx
```

Edit `components/Practice.tsx`: change `export default function App()` to `export default function Practice()`, fix relative imports (`'./api'` → `'../api'`, `'./types'` → `'../types'`, `'./components/X'` → `'./X'`), remove `import './App.css'`.

- [ ] **Step 2: Write `league.ts`**

```ts
// web/src/league.ts
export interface Me { name: string; is_commissioner: boolean; slot: number | null }

export interface Pick { n: number; slot: number; team: string; by: string; ts: number }

export interface LeagueView {
  players: string[];
  commissioner: string;
  slots: Record<string, number> | null;
  status: 'lobby' | 'drafting' | 'done';
  picks: Pick[];
  pick_order: number[];
  rosters: Record<string, string[]>;
  current_slot: number | null;
  current_player: string | null;
  logged_in: Record<string, number>;
  teams: string[];
}

export interface Message { id: string; by: string; text: string; ts: number }

export interface StandingsRow { player: string; teams: { code: string; wins: number }[]; total: number }
export interface StandingsResponse { rows: StandingsRow[]; stale: boolean; overrides: Record<string, number> }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: 'same-origin', ...init });
  if (res.status === 401) throw new Error('401');
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}
const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const login = (name: string, pin: string) => call<{ name: string }>('/api/login', json({ name, pin }));
export const getMe = () => call<Me>('/api/me');
export const getLeague = () => call<LeagueView>('/api/league');
export const randomize = () => call<LeagueView>('/api/league/randomize', { method: 'POST' });
export const resetDraft = () => call<LeagueView>('/api/league/reset', { method: 'POST' });
export const pickTeam = (team: string) => call<LeagueView>('/api/league/pick', json({ team }));
export const undoPick = () => call<LeagueView>('/api/league/undo', { method: 'POST' });
export const getMessages = (since?: number) =>
  call<Message[]>(since ? `/api/messages?since=${since}` : '/api/messages');
export const postMessage = (text: string) => call<Message>('/api/messages', json({ text }));
export const getStandings = (refresh = false) =>
  call<StandingsResponse>(refresh ? '/api/standings?refresh=1' : '/api/standings');
export const setOverride = (team: string, wins: number | null) =>
  call<{ overrides: Record<string, number> }>('/api/standings/override', json({ team, wins }));

/** Public: the five names for the login screen come from /api/teams? No — from a
 *  tiny open endpoint is unnecessary; hard-code to match the league doc. */
export const PLAYERS = [
  'Nate Robinson',
  'Evan Goguillon-Bader',
  'Logan Borgelt',
  'Eric Whitley',
  'Mitch Fischer',
];
```

- [ ] **Step 3: Write `Login.tsx`**

```tsx
// web/src/components/Login.tsx
import { useState } from 'react';
import { login, PLAYERS } from '../league';

export default function Login({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState<string | null>(null);
  const [pin, setPin] = useState('');
  const [bad, setBad] = useState(false);

  async function submit() {
    if (!name) return;
    try {
      await login(name, pin);
      onDone();
    } catch {
      setBad(true);
      setTimeout(() => setBad(false), 600);
    }
  }

  return (
    <div className="login">
      <div className="login-names">
        {PLAYERS.map((p) => (
          <button key={p} className={`login-name ${name === p ? 'on' : ''}`} onClick={() => setName(p)}>
            {p}
          </button>
        ))}
      </div>
      <input
        className={`login-pin ${bad ? 'shake' : ''}`}
        type="password"
        placeholder="PIN"
        value={pin}
        onChange={(e) => setPin(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && submit()}
      />
      <button className="btn primary" disabled={!name || !pin} onClick={submit}>
        Enter
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Write `Lobby.tsx`**

```tsx
// web/src/components/Lobby.tsx
import type { LeagueView, Me } from '../league';
import { randomize } from '../league';

const ONLINE_MS = 30_000;

export default function Lobby({ view, me }: { view: LeagueView; me: Me }) {
  const now = Date.now() / 1000;
  return (
    <div className="lobby">
      <ul className="lobby-list">
        {view.players.map((p) => {
          const seen = view.logged_in[p];
          const on = seen !== undefined && now - seen < ONLINE_MS / 1000;
          return (
            <li key={p}>
              <span className={`dot ${on ? 'on' : ''}`} />
              {p}
            </li>
          );
        })}
      </ul>
      {me.is_commissioner && (
        <button className="btn primary" onClick={() => randomize().catch(() => {})}>
          Randomize order
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Rewrite `App.tsx` as the router**

```tsx
// web/src/App.tsx
import { useCallback, useEffect, useState } from 'react';
import './App.css';
import type { LeagueView, Me } from './league';
import { getLeague, getMe } from './league';
import Login from './components/Login';
import Lobby from './components/Lobby';
import LiveDraft from './components/LiveDraft';
import Standings from './components/Standings';
import Practice from './components/Practice';

type Tab = 'draft' | 'standings' | 'practice';

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined); // undefined = checking
  const [view, setView] = useState<LeagueView | null>(null);
  const [tab, setTab] = useState<Tab>('draft');

  const refreshMe = useCallback(() => {
    getMe().then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(refreshMe, [refreshMe]);

  // Poll league state: 2s while lobby/drafting, 60s when done.
  useEffect(() => {
    if (!me) return;
    let alive = true;
    let timer: number;
    const tick = async () => {
      try {
        const v = await getLeague();
        if (!alive) return;
        setView(v);
        timer = window.setTimeout(tick, v.status === 'done' ? 60_000 : 2_000);
      } catch (e) {
        if ((e as Error).message === '401') { setMe(null); return; }
        timer = window.setTimeout(tick, 5_000);
      }
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [me]);

  if (me === undefined) return null;
  if (me === null) return <Login onDone={refreshMe} />;
  if (!view) return null;

  const tabs: Tab[] = me.is_commissioner ? ['draft', 'standings', 'practice'] : ['draft', 'standings'];

  return (
    <div className="app">
      <nav className="tab-bar">
        {tabs.map((t) => (
          <button key={t} className={`tab-btn ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {t === 'draft' ? 'Draft' : t === 'standings' ? 'Standings' : 'Practice'}
          </button>
        ))}
        <span className="tab-me">{me.name}</span>
      </nav>
      {tab === 'draft' && (view.status === 'lobby' ? <Lobby view={view} me={me} /> : <LiveDraft view={view} me={me} onChange={setView} />)}
      {tab === 'standings' && <Standings me={me} view={view} />}
      {tab === 'practice' && <Practice />}
    </div>
  );
}
```

Create placeholder files so it compiles until Task 6/7 fill them in:

```tsx
// web/src/components/LiveDraft.tsx (temporary)
import type { LeagueView, Me } from '../league';
export default function LiveDraft(_: { view: LeagueView; me: Me; onChange: (v: LeagueView) => void }) { return null; }
```
```tsx
// web/src/components/Standings.tsx (temporary)
import type { LeagueView, Me } from '../league';
export default function Standings(_: { view: LeagueView; me: Me }) { return null; }
```

- [ ] **Step 6: `live.css` and import**

```css
/* web/src/live.css */
.login { max-width: 360px; margin: 15vh auto; display: flex; flex-direction: column; gap: 12px; padding: 0 16px; }
.login-names { display: flex; flex-direction: column; gap: 8px; }
.login-name { padding: 12px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg-panel); color: var(--text); text-align: left; cursor: pointer; }
.login-name.on { border-color: var(--accent); background: var(--accent-bg); }
.login-pin { padding: 12px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg-panel-2); color: var(--text); font-size: 16px; }
.login-pin.shake { animation: shake 0.3s; border-color: var(--red); }
@keyframes shake { 25% { transform: translateX(-6px); } 75% { transform: translateX(6px); } }
.btn { padding: 10px 16px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg-panel-2); color: var(--text); cursor: pointer; }
.btn.primary { background: var(--accent); color: #111; border-color: var(--accent); font-weight: 600; }
.btn:disabled { opacity: 0.4; cursor: default; }
.tab-me { margin-left: auto; color: var(--text-dim); font-size: 13px; align-self: center; padding-right: 8px; }

.lobby { max-width: 360px; margin: 10vh auto; display: flex; flex-direction: column; gap: 20px; padding: 0 16px; }
.lobby-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 10px; font-size: 18px; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: var(--border); margin-right: 12px; }
.dot.on { background: var(--green); }

.live { display: grid; grid-template-columns: 1fr 320px; gap: 16px; padding: 16px; }
@media (max-width: 900px) { .live { grid-template-columns: 1fr; } }
.strip { display: grid; grid-template-columns: repeat(10, 1fr); gap: 4px; padding: 12px 16px 0; }
.strip-cell { border: 1px solid var(--border); border-radius: 6px; padding: 4px 6px; font-size: 12px; min-height: 40px; background: var(--bg-panel); }
.strip-cell .who { color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.strip-cell .team { font-weight: 600; font-size: 14px; }
.strip-cell.now { border-color: var(--accent); background: var(--accent-bg); }
.strip-cell.me .who { color: var(--text); }
.strip-actions { padding: 8px 16px 0; display: flex; gap: 8px; }

.dboard { display: flex; flex-direction: column; gap: 12px; }
.dboard-div { display: grid; grid-template-columns: 90px repeat(4, 1fr); gap: 6px; align-items: stretch; }
.dboard-div h4 { font-size: 12px; color: var(--text-dim); font-weight: 500; align-self: center; }
.tile { border: 1px solid var(--border); border-radius: 8px; padding: 10px 8px; background: var(--bg-panel); color: var(--text); font-weight: 600; font-size: 16px; text-align: left; display: flex; flex-direction: column; gap: 2px; }
.tile .owner { font-size: 11px; font-weight: 400; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tile.open { cursor: pointer; border-color: var(--accent); }
.tile.open:hover { background: var(--accent-bg); }
.tile.taken { opacity: 0.45; }
.tile.mine { opacity: 1; border-color: var(--green); }
.tile:disabled { cursor: default; }

.lrosters { display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; }
.lroster h4 { font-size: 12px; font-weight: 500; color: var(--text-dim); margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lroster.me h4 { color: var(--text); }
.lroster li { list-style: none; font-size: 14px; padding: 2px 0; }
.lroster ul { padding: 0; margin: 0; min-height: 6.6em; }
.lroster.turn h4 { color: var(--accent); }

.feed { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-panel); height: 50vh; }
.feed-list { flex: 1; overflow-y: auto; padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; font-size: 14px; }
.feed-pick { color: var(--text-dim); }
.feed-pick b { color: var(--text); }
.feed-msg .by { color: var(--accent); margin-right: 6px; }
.feed-input { border: 0; border-top: 1px solid var(--border); background: transparent; color: var(--text); padding: 10px; font-size: 15px; }
.feed-input:focus { outline: none; }

.standings { padding: 16px; overflow-x: auto; }
.standings table { border-collapse: collapse; width: 100%; max-width: 900px; }
.standings th, .standings td { padding: 8px 10px; border-bottom: 1px solid var(--border); text-align: left; white-space: nowrap; }
.standings th { color: var(--text-dim); font-weight: 500; font-size: 13px; }
.standings td.num { text-align: right; font-variant-numeric: tabular-nums; }
.standings td.total { font-weight: 700; text-align: right; }
.standings td.ov { text-decoration: underline dotted; cursor: pointer; }
.standings .stale { color: var(--text-dim); font-size: 12px; margin-top: 8px; }
```

In `web/src/main.tsx` add `import './live.css'` after `./index.css`.

- [ ] **Step 7: Build**

Run: `cd web && npm run build`
Expected: builds with no TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add web/src
git commit -m "feat(web): login, lobby, app router; old app becomes commissioner Practice tab

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Live draft screen (strip, board, rosters, feed)

**Files:**
- Create: `web/src/components/PickStrip.tsx`, `DraftBoard.tsx`, `LiveRosters.tsx`, `Feed.tsx`
- Replace: `web/src/components/LiveDraft.tsx`

**Interfaces:**
- Consumes: `LeagueView`, `Me`, `pickTeam`, `undoPick`, `getMessages`, `postMessage` from Task 5; `fetchTeams` from `../api` for division grouping.

- [ ] **Step 1: `PickStrip.tsx`**

```tsx
// web/src/components/PickStrip.tsx
import type { LeagueView } from '../league';

export default function PickStrip({ view, myName }: { view: LeagueView; myName: string }) {
  const nameOf = (slot: number) => Object.entries(view.slots ?? {}).find(([, s]) => s === slot)?.[0] ?? '';
  const short = (n: string) => n.split(' ')[0];
  return (
    <div className="strip">
      {view.pick_order.map((slot, i) => {
        const p = view.picks[i];
        const who = nameOf(slot);
        const cls = ['strip-cell', i === view.picks.length && view.status === 'drafting' ? 'now' : '', who === myName ? 'me' : ''].join(' ');
        return (
          <div key={i} className={cls}>
            <div className="who">{i + 1}. {short(who)}</div>
            <div className="team">{p?.team ?? ''}</div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: `DraftBoard.tsx`**

```tsx
// web/src/components/DraftBoard.tsx
import type { Team } from '../types';

interface Props {
  teams: Team[];
  takenBy: Record<string, string>; // code -> player name
  myName: string;
  canPick: boolean;
  onPick: (code: string) => void;
}

export default function DraftBoard({ teams, takenBy, myName, canPick, onPick }: Props) {
  const divisions = Array.from(new Set(teams.map((t) => t.division)));
  const short = (n: string) => n.split(' ')[0];
  return (
    <div className="dboard">
      {divisions.map((div) => (
        <div key={div} className="dboard-div">
          <h4>{div}</h4>
          {teams
            .filter((t) => t.division === div)
            .sort((a, b) => a.code.localeCompare(b.code))
            .map((t) => {
              const owner = takenBy[t.code];
              const taken = owner !== undefined;
              const cls = ['tile', taken ? 'taken' : canPick ? 'open' : '', owner === myName ? 'mine' : ''].join(' ');
              return (
                <button key={t.code} className={cls} disabled={taken || !canPick} onClick={() => onPick(t.code)} title={t.name}>
                  {t.code}
                  <span className="owner">{taken ? short(owner) : ' '}</span>
                </button>
              );
            })}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: `LiveRosters.tsx`**

```tsx
// web/src/components/LiveRosters.tsx
import type { LeagueView } from '../league';

export default function LiveRosters({ view, myName }: { view: LeagueView; myName: string }) {
  const bySlot = [...view.players].sort((a, b) => (view.slots?.[a] ?? 0) - (view.slots?.[b] ?? 0));
  return (
    <div className="lrosters">
      {bySlot.map((p) => (
        <div key={p} className={['lroster', p === myName ? 'me' : '', p === view.current_player ? 'turn' : ''].join(' ')}>
          <h4>{p}</h4>
          <ul>
            {(view.rosters[p] ?? []).map((c) => <li key={c}>{c}</li>)}
          </ul>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: `Feed.tsx`**

```tsx
// web/src/components/Feed.tsx
import { useEffect, useRef, useState } from 'react';
import type { LeagueView, Message } from '../league';
import { getMessages, postMessage } from '../league';

type Item = { ts: number; kind: 'pick'; by: string; team: string } | { ts: number; kind: 'msg'; by: string; text: string; id: string };

export default function Feed({ view, myName }: { view: LeagueView; myName: string }) {
  const [msgs, setMsgs] = useState<Message[]>([]);
  const [text, setText] = useState('');
  const listRef = useRef<HTMLDivElement>(null);
  const lastTs = useRef<number | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    let timer: number;
    const tick = async () => {
      try {
        const m = await getMessages(lastTs.current);
        if (!alive) return;
        if (m.length) {
          lastTs.current = m[m.length - 1].ts;
          setMsgs((prev) => [...prev, ...m]);
        }
      } catch { /* retry next tick */ }
      timer = window.setTimeout(tick, 2000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);

  const items: Item[] = [
    ...view.picks.map((p) => ({ ts: p.ts, kind: 'pick' as const, by: p.by, team: p.team })),
    ...msgs.map((m) => ({ ts: m.ts, kind: 'msg' as const, by: m.by, text: m.text, id: m.id })),
  ].sort((a, b) => a.ts - b.ts);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [items.length]);

  async function send() {
    const t = text.trim();
    if (!t) return;
    setText('');
    try {
      const m = await postMessage(t);
      lastTs.current = Math.max(lastTs.current ?? 0, m.ts);
      setMsgs((prev) => [...prev, m]);
    } catch { setText(t); }
  }

  return (
    <div className="feed">
      <div className="feed-list" ref={listRef}>
        {items.map((it) =>
          it.kind === 'pick' ? (
            <div key={`p${it.ts}`} className="feed-pick">{it.by} — <b>{it.team}</b></div>
          ) : (
            <div key={it.id} className="feed-msg"><span className="by">{it.by}</span>{it.text}</div>
          )
        )}
      </div>
      <input
        className="feed-input"
        placeholder={myName}
        value={text}
        maxLength={500}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && send()}
      />
    </div>
  );
}
```

- [ ] **Step 5: `LiveDraft.tsx`**

```tsx
// web/src/components/LiveDraft.tsx
import { useEffect, useMemo, useState } from 'react';
import { fetchTeams } from '../api';
import type { Team } from '../types';
import type { LeagueView, Me } from '../league';
import { pickTeam, resetDraft, undoPick } from '../league';
import PickStrip from './PickStrip';
import DraftBoard from './DraftBoard';
import LiveRosters from './LiveRosters';
import Feed from './Feed';
import Recommendations from './Recommendations';
import Forecast from './Forecast';
import { fetchRecommend } from '../api';
import type { RecommendResponse } from '../types';

interface Props { view: LeagueView; me: Me; onChange: (v: LeagueView) => void }

export default function LiveDraft({ view, me, onChange }: Props) {
  const [teams, setTeams] = useState<Team[]>([]);
  useEffect(() => { fetchTeams().then((t) => setTeams(t.teams)).catch(() => {}); }, []);

  const takenBy = useMemo(() => Object.fromEntries(view.picks.map((p) => [p.team, p.by])), [view.picks]);
  const myTurn = view.status === 'drafting' && view.current_player === me.name;
  const taken = view.picks.map((p) => p.team);

  // Commissioner-only optimizer panel, driven by the live board.
  const [rec, setRec] = useState<RecommendResponse | null>(null);
  const [recLoading, setRecLoading] = useState(false);
  useEffect(() => {
    if (!me.is_commissioner || me.slot == null || view.status !== 'drafting') return;
    let cancelled = false;
    setRecLoading(true);
    fetchRecommend(me.slot, taken).then((r) => { if (!cancelled) setRec(r); }).catch(() => {}).finally(() => { if (!cancelled) setRecLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me.is_commissioner, me.slot, view.status, taken.join(',')]);

  const teamNames = useMemo(() => Object.fromEntries(teams.map((t) => [t.code, t.name])), [teams]);

  async function act(fn: () => Promise<LeagueView>) {
    try { onChange(await fn()); } catch { /* poll will correct */ }
  }

  return (
    <>
      <PickStrip view={view} myName={me.name} />
      {me.is_commissioner && (
        <div className="strip-actions">
          <button className="btn" disabled={view.picks.length === 0} onClick={() => act(undoPick)}>Undo</button>
          {view.picks.length === 0 && <button className="btn" onClick={() => act(resetDraft)}>Re-randomize</button>}
        </div>
      )}
      <div className="live">
        <div>
          <DraftBoard teams={teams} takenBy={takenBy} myName={me.name} canPick={myTurn} onPick={(c) => act(() => pickTeam(c))} />
          {me.is_commissioner && view.status === 'drafting' && (
            <>
              <Recommendations recommend={rec} loading={recLoading} teamNames={teamNames} />
              <Forecast forecast={rec?.forecast ?? []} done={false} />
            </>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <LiveRosters view={view} myName={me.name} />
          <Feed view={view} myName={me.name} />
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 6: Build and smoke locally**

```bash
cd web && npm run build && cd ..
uv run winspool-serve &
```

Open http://127.0.0.1:8000 in two browser profiles (or one normal + one private window). Log in as Nate Robinson (PIN 1234) and as another player. Randomize. Confirm: strip highlights current pick, only the current player's tiles are clickable, a pick appears in both windows within 2s, feed shows the pick and typed messages, Undo works for Nate only, Recommendations panel is visible only in Nate's window.

Kill the server when done.

- [ ] **Step 7: Text-justification pass**

List every literal string in Login, Lobby, PickStrip, DraftBoard, LiveRosters, Feed, LiveDraft. Allowed: `PIN`, `Enter`, `Randomize order`, `Undo`, `Re-randomize`, `Draft`, `Standings`, `Practice`, division names, team codes, player names, pick numbers. Anything else gets deleted.

- [ ] **Step 8: Commit**

```bash
git add web/src
git commit -m "feat(web): live draft screen — pick strip, board, rosters, feed; optimizer panel commissioner-only

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Standings screen

**Files:**
- Replace: `web/src/components/Standings.tsx`

- [ ] **Step 1: Implement**

```tsx
// web/src/components/Standings.tsx
import { useEffect, useState } from 'react';
import type { LeagueView, Me, StandingsResponse } from '../league';
import { getStandings, setOverride } from '../league';
import Feed from './Feed';

export default function Standings({ me, view }: { me: Me; view: LeagueView }) {
  const [data, setData] = useState<StandingsResponse | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: number;
    const tick = async () => {
      try { const d = await getStandings(); if (alive) setData(d); } catch { /* keep last */ }
      timer = window.setTimeout(tick, 60_000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);

  async function edit(code: string, current: number) {
    const v = window.prompt(code, String(current));
    if (v === null) return;
    const n = v.trim() === '' ? null : Number(v);
    if (n !== null && !Number.isInteger(n)) return;
    await setOverride(code, n).catch(() => {});
    setData(await getStandings());
  }

  if (!data) return null;
  const width = 6;
  return (
    <div className="standings">
      <table>
        <thead>
          <tr>
            <th></th>
            {Array.from({ length: width }, (_, i) => <th key={i}></th>)}
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.player}>
              <td>{r.player}</td>
              {Array.from({ length: width }, (_, i) => {
                const t = r.teams[i];
                if (!t) return <td key={i} />;
                return (
                  <td key={t.code} className={`num ${me.is_commissioner ? 'ov' : ''}`} onClick={() => me.is_commissioner && edit(t.code, t.wins)}>
                    {t.code} {t.wins}
                  </td>
                );
              })}
              <td className="total">{r.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.stale && <div className="stale">stale</div>}
      <div style={{ marginTop: 16, maxWidth: 900 }}>
        <Feed view={view} myName={me.name} />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build, smoke, commit**

`cd web && npm run build`. Serve, log in, draft one pick, open Standings: one row per player, team codes with `0`, totals `0`. As Nate, click a number, enter `3`, table updates.

```bash
git add web/src/components/Standings.tsx
git commit -m "feat(web): standings table with commissioner override + season feed

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Dockerfile + Cloud Run deploy + prod init + mock draft

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `scripts/deploy.sh`
- Modify: `README.md` (deploy section)

- [ ] **Step 1: Dockerfile**

```dockerfile
# Dockerfile
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv pip install --system --no-cache .
COPY data/cache/ ./data/cache/
COPY --from=web /web/dist ./web/dist
ENV PORT=8080 STORE=firestore PYTHONUNBUFFERED=1
CMD ["sh", "-c", "winspool-serve --host 0.0.0.0 --port ${PORT}"]
```

```
# .dockerignore
venv/
.venv/
web/node_modules/
web/dist/
.git/
data/history/
tests/
docs/
**/__pycache__/
```

Check `data/cache/sim_matrix.npz` exists and is fresh before building; if not, run `uv run winspool-serve` once locally and stop it.

- [ ] **Step 2: Deploy script**

```bash
# scripts/deploy.sh
#!/usr/bin/env bash
set -euo pipefail
PROJECT=snowpack-pika
REGION=us-west1
SERVICE=pika
: "${SESSION_SECRET:?set SESSION_SECRET}"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" --region "$REGION" --source . \
  --allow-unauthenticated \
  --min-instances 1 --max-instances 1 --memory 2Gi --cpu 2 \
  --set-env-vars "STORE=firestore,GOOGLE_CLOUD_PROJECT=$PROJECT,SESSION_SECRET=$SESSION_SECRET"
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)'
```

`chmod +x scripts/deploy.sh`.

- [ ] **Step 3: Deploy**

```bash
export SESSION_SECRET="$(openssl rand -hex 32)"
echo "$SESSION_SECRET" > "$SCRATCHPAD/session_secret.txt"   # keep for redeploys; never commit
./scripts/deploy.sh
```

Expected: Cloud Build succeeds; a `https://pika-....run.app` URL prints. First build takes 5–8 minutes. If it fails on `google-cloud-firestore`, check `uv.lock` was regenerated in Task 4.

- [ ] **Step 4: Initialize the prod league**

The Cloud Run service account needs Firestore access (default compute SA has Editor on a fresh project, so this works). Run init locally against Firestore using your user creds:

```bash
gcloud auth application-default login   # once, if not already
STORE=firestore GOOGLE_CLOUD_PROJECT=snowpack-pika LEAGUE_PIN=awardwinninglisteners \
  uv run winspool league-init \
  --players "Nate Robinson,Evan Goguillon-Bader,Logan Borgelt,Eric Whitley,Mitch Fischer" \
  --commissioner "Nate Robinson"
```

Expected: `league initialized`. Verify: `curl -s -X POST $URL/api/login -H 'content-type: application/json' -d '{"name":"Nate Robinson","pin":"awardwinninglisteners"}'` → `{"name":"Nate Robinson"}`.

- [ ] **Step 5: Mock draft on the live URL**

Open the URL in five browser profiles (or one per player via private windows). Log in as each. As Nate: Randomize. Draft all 30 picks, rotating windows. Undo once mid-draft and re-pick. Type a message from two players. Open Standings: 30 zeros. Then wipe for tonight:

```bash
STORE=firestore GOOGLE_CLOUD_PROJECT=snowpack-pika LEAGUE_PIN=awardwinninglisteners \
  uv run winspool league-init --force \
  --players "Nate Robinson,Evan Goguillon-Bader,Logan Borgelt,Eric Whitley,Mitch Fischer" \
  --commissioner "Nate Robinson"
```

Note: `--force` wipes picks but not messages. Delete test messages in the Firestore console (`leagues/2026/messages`) or leave them.

- [ ] **Step 6: README + commit**

Add a "Deploy" section to README.md: the `scripts/deploy.sh` invocation, the `league-init` command, and the note that `SESSION_SECRET` must stay stable across redeploys or everyone is logged out. Fix the stale "6-player" line to "5-player".

```bash
git add Dockerfile .dockerignore scripts/deploy.sh README.md
git commit -m "deploy: Cloud Run Dockerfile + deploy script; README deploy + league-init

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Do NOT push to main. Push `live-draft` and open a PR when the user says so.

---

## Self-review

**Spec coverage:** login/PIN (T2), lobby + randomize/reset (T1/T2/T5), fixed pick order + turn enforcement + transaction (T1/T2 via `Store.update`), undo (T1/T2), messages (T1/T2/T6), standings + overrides + stale (T3/T7), optimizer commissioner-only (T2), Practice tab (T5), text pass (T6 step 7), Dockerfile/Cloud Run/Firestore/league-init (T4/T8), 2s/60s polling (T5/T7), error handling: 401 shake (T5), 409 corrected by poll (T6 `act`), stale standings (T3/T7), 503 when uninitialized (T2).

**Type consistency:** `LeagueView` fields match `league.view()` keys. `StandingsResponse.rows[].teams[].{code,wins}` matches `get_standings`. `Message.{id,by,text,ts}` matches both stores. `pickTeam` posts `{team}` matching `PickReq`.

**Known trade-offs:** `PLAYERS` is duplicated in `league.ts` for the login screen (the server is the source of truth; if names change, update both). Firestore `messages(since=None)` uses `limit_to_last` to return the newest 200; with `since` it returns the oldest 200 after `since`, which is fine at this volume.
