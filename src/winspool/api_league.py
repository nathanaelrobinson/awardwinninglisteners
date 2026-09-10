import hmac
import math
import os
import random
import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from google.api_core import exceptions as gexc
from pydantic import BaseModel, Field

from . import league
from . import live as _live
from . import oddslog as _oddslog
from . import simmodel as _simmodel
from . import standings as _standings
from . import week as _week
from .auth import current_user, require_commissioner, set_cookie, viewer
from .league import LeagueError
from .store import get_store
from .teams import resolve
from .throttle import Throttle

router = APIRouter()

TOUCH_EVERY = 20.0  # seconds; Lobby considers a player online if seen within 30s

_LOGIN_THROTTLE = Throttle()

# In-season live projection. Same cache dir the sim reads; overridable for tests.
LIVE_CACHE_DIR = os.environ.get("WINSPOOL_DATA_DIR") or str(
    Path(__file__).resolve().parents[2] / "data" / "cache")
LIVE_N_SEASONS = 5000
SEASON = int(os.environ.get("WINSPOOL_SEASON", "2026"))


def _doc():
    try:
        return get_store().get()
    except LookupError:
        raise HTTPException(503, "league not initialized")
    except (gexc.GoogleAPICallError, gexc.RetryError, sqlite3.OperationalError):
        raise HTTPException(503, "busy")


def _store_read(fn):
    try:
        return fn()
    except LookupError:
        raise HTTPException(503, "league not initialized")
    except (gexc.GoogleAPICallError, gexc.RetryError, sqlite3.OperationalError):
        raise HTTPException(503, "busy")


def _run_read(fn):
    """_store_read for a call that also writes back to the store."""
    return _store_read(fn)


def _run(fn):
    try:
        return league.view(get_store().update(fn))
    except LeagueError as e:
        raise HTTPException(e.status, e.detail)
    except LookupError:
        raise HTTPException(503, "league not initialized")
    except (gexc.Aborted, gexc.GoogleAPICallError, gexc.RetryError,
            sqlite3.OperationalError):
        raise HTTPException(503, "busy")
    except ValueError as e:
        if "Failed to commit transaction" in str(e):
            raise HTTPException(503, "busy")
        raise


def _snapshot(store, reason: str) -> str:
    doc = store.get()
    v = league.view(doc)
    snapshot = {
        "taken_at": time.time(),
        "reason": reason,
        "league": v,
        "messages": store.messages(None),
        "n_picks": len(doc["picks"]),
        "status": doc["status"],
    }
    return store.add_snapshot(snapshot)


class LoginReq(BaseModel):
    # Bounded because the name is used as a throttle-table key.
    name: str = Field(max_length=100)
    pin: str = Field(max_length=100)


@router.post("/api/login")
def login(req: LoginReq, resp: Response):
    """PINs are four digits and the player names are public, so the whole
    keyspace is 10k guesses; without a penalty that is a couple of minutes of
    scripted requests. Back off per name after a few misses.

    The penalty is checked before the PIN is, so a guesser inside the window
    cannot tell a right PIN from a wrong one.
    """
    doc = _doc()
    now = time.time()
    wait = _LOGIN_THROTTLE.retry_after(req.name, now)
    if wait > 0:
        raise HTTPException(429, "too many attempts",
                            headers={"Retry-After": str(math.ceil(wait))})
    if req.name not in doc["players"] or not league.check_pin(doc, req.name, req.pin):
        _LOGIN_THROTTLE.fail(req.name, now)
        raise HTTPException(401, "bad name or pin")
    _LOGIN_THROTTLE.succeed(req.name)
    set_cookie(resp, req.name)
    return {"name": req.name}


@router.get("/api/me")
def me(name: str = Depends(current_user)):
    doc = _doc()
    return {"name": name, "is_commissioner": name == doc["commissioner"],
            "slot": league.slot_of(doc, name)}


def _touch(name):
    def touch(d):
        d = dict(d)
        d["logged_in"] = {**d.get("logged_in", {}), name: time.time()}
        return d
    return touch


@router.get("/api/league")
def get_league(name: str | None = Depends(viewer)):
    doc = _doc()
    last = (doc.get("logged_in") or {}).get(name) or 0
    if name is None or doc["status"] != "lobby" or time.time() - last < TOUCH_EVERY:
        return league.view(doc)
    try:
        return _run(_touch(name))
    except HTTPException as e:
        if e.status_code == 503:
            return league.view(doc)
        raise


@router.post("/api/league/randomize")
def randomize(_: str = Depends(require_commissioner)):
    return _run(lambda d: league.randomize(d, random.SystemRandom()))


@router.post("/api/league/reset")
def reset(_: str = Depends(require_commissioner)):
    return _run(league.reset)


@router.post("/api/league/restart")
def restart(_: str = Depends(require_commissioner)):
    store = get_store()
    _snapshot(store, "restart")
    view = _run(league.restart)
    store.clear_messages()
    return view


@router.get("/api/league/snapshots")
def get_snapshots(_: str = Depends(require_commissioner)):
    return get_store().list_snapshots()


class PickReq(BaseModel):
    team: str


@router.post("/api/league/pick")
def pick(req: PickReq, name: str = Depends(current_user)):
    view = _run(lambda d: league.pick(d, name, req.team, time.time()))
    if view["status"] == "done":
        try:
            _snapshot(get_store(), "complete")
        except Exception:
            pass
    return view


@router.post("/api/league/undo")
def undo(_: str = Depends(require_commissioner)):
    return _run(league.undo)


class MsgReq(BaseModel):
    text: str


@router.post("/api/messages")
def post_message(req: MsgReq, name: str = Depends(current_user)):
    _doc()
    text = req.text.strip()
    if not text or len(text) > 500:
        raise HTTPException(400, "1-500 chars")
    return get_store().add_message(name, text)


@router.get("/api/messages")
def get_messages(since: float | None = None, _: str | None = Depends(viewer)):
    _doc()
    return get_store().messages(since)


STANDINGS_STALE_AFTER = 6 * 3600


@router.get("/api/standings")
def get_standings(refresh: int = 0, name: str | None = Depends(viewer)):
    doc = _doc()
    store = get_store()
    if refresh and name != doc["commissioner"]:
        refresh = 0
    if refresh:
        sdoc = _standings.refresh_standings(store)
    else:
        sdoc = store.get_standings()
        if sdoc is None:
            sdoc = _standings.refresh_standings(store)
    wins = _standings.apply_overrides(sdoc["wins"], doc.get("overrides", {}))
    rosters = league.view(doc)["rosters"]
    rows = [{"player": p,
             "teams": [{"code": t, "wins": wins[t]} for t in teams],
             "total": sum(wins[t] for t in teams)}
            for p, teams in rosters.items()]
    rows.sort(key=lambda r: r["total"], reverse=True)
    stale = (not sdoc["ok"]) or (time.time() - sdoc["fetched_at"] > STANDINGS_STALE_AFTER)
    return {"rows": rows, "stale": stale, "overrides": doc.get("overrides", {}),
            "fetched_at": sdoc["fetched_at"]}


class OverrideReq(BaseModel):
    team: str
    wins: int | None   # None clears


@router.post("/api/standings/override")
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
    return {"overrides": _doc()["overrides"]}


@router.get("/api/league/sim-model")
def get_sim_model(_: str | None = Depends(viewer)):
    """The ensemble itself, so the browser can roll its own seasons.

    Served from the store, where the live refresh leaves it. Building it means
    pulling the season schedule from nfl_data_py and calibrating the mixture,
    about two seconds; doing that per request put a visible stall in front of
    the Simulations tab. The on-demand build below is the first-run path only.
    """
    doc = _store_read(get_store().get_sim_model)
    if doc is None:
        doc = _run_read(lambda: _simmodel.refresh_model(get_store(), LIVE_CACHE_DIR))
    return doc


@router.get("/api/league/live")
def get_live(_: str | None = Depends(viewer)):
    doc = _store_read(get_store().get_live)
    if doc is None:
        raise HTTPException(404, "no live projection yet")
    return doc


@router.get("/api/week")
def get_week(week: int | None = None, _: str | None = Depends(viewer)):
    if week is not None and not 1 <= week <= 18:
        raise HTTPException(422, "week out of range")
    store = get_store()
    live_doc = store.get_live()
    if live_doc is None:
        raise HTTPException(503, "projection not ready")
    target = live_doc["week"] if week is None else week

    # A past week is served from what we recorded at the time. Recomputing it
    # with today's information would be a lie about what we knew.
    source_doc = live_doc
    if target != live_doc["week"]:
        stored = next((w for w in store.list_weeks() if w["week"] == target), None)
        if stored is None:
            raise HTTPException(404, "no record for that week")
        source_doc = stored

    rosters = league.view(_doc())["rosters"]
    df = _live._load_schedule_cached()
    out = _week.build_week(source_doc, rosters, df, target,
                           store.odds_for_week(SEASON, target))
    return {"season": SEASON, **out}


@router.get("/api/league/weeks")
def get_weeks(_: str | None = Depends(viewer)):
    weeks = _store_read(get_store().list_weeks)
    def slim(rows):
        return [{"player": r["player"], "pwin": r["pwin"], "exp_wins": r["exp_wins"]} for r in rows]
    return [{"week": w["week"], "rows": slim(w["rows"]),
             "views": {name: slim(rows) for name, rows in (w.get("views") or {}).items()}}
            for w in weeks]


def _check_refresh_token(x_refresh_token: str | None) -> None:
    expected = os.environ.get("REFRESH_TOKEN")
    if not expected:
        raise HTTPException(503, "refresh token not configured")
    if not x_refresh_token or not hmac.compare_digest(x_refresh_token, expected):
        raise HTTPException(403, "forbidden")


@router.post("/internal/refresh-live", include_in_schema=False)
def internal_refresh_live(x_refresh_token: str | None = Header(default=None)):
    _check_refresh_token(x_refresh_token)
    doc = _doc()
    if doc["status"] != "done":
        raise HTTPException(409, "draft not finished")
    try:
        out = _live.refresh_live(get_store(), LIVE_CACHE_DIR, n_seasons=LIVE_N_SEASONS)
    except Exception as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(e)[:200]})
    return {"ok": True, "week": out["week"], "computed_at": out["computed_at"]}


@router.post("/internal/refresh-standings", include_in_schema=False)
def internal_refresh_standings(x_refresh_token: str | None = Header(default=None)):
    _check_refresh_token(x_refresh_token)
    doc = _standings.refresh_standings(get_store())
    if not doc["ok"]:
        return JSONResponse(status_code=503, content={
            "ok": False, "fetched_at": doc["fetched_at"], "error": doc["error"]})
    return {"ok": True, "fetched_at": doc["fetched_at"],
            "teams_with_wins": sum(1 for w in doc["wins"].values() if w > 0)}


@router.post("/internal/refresh-odds", include_in_schema=False)
def internal_refresh_odds(x_refresh_token: str | None = Header(default=None)):
    _check_refresh_token(x_refresh_token)
    try:
        df = _live._load_schedule_cached()
        out = _oddslog.refresh_odds(get_store(), df, SEASON)
    except Exception as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(e)[:200]})
    return {"ok": True, **out}
