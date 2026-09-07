import hmac
import os
import random
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from google.api_core import exceptions as gexc
from pydantic import BaseModel

from . import league
from . import standings as _standings
from .auth import current_user, require_commissioner, set_cookie
from .league import LeagueError
from .store import get_store
from .teams import resolve

router = APIRouter()

TOUCH_EVERY = 20.0  # seconds; Lobby considers a player online if seen within 30s


def _doc():
    try:
        return get_store().get()
    except LookupError:
        raise HTTPException(503, "league not initialized")
    except (gexc.GoogleAPICallError, gexc.RetryError):
        raise HTTPException(503, "busy")


def _run(fn):
    try:
        return league.view(get_store().update(fn))
    except LeagueError as e:
        raise HTTPException(e.status, e.detail)
    except LookupError:
        raise HTTPException(503, "league not initialized")
    except (gexc.Aborted, gexc.GoogleAPICallError, gexc.RetryError):
        raise HTTPException(503, "busy")
    except ValueError as e:
        if "Failed to commit transaction" in str(e):
            raise HTTPException(503, "busy")
        raise


class LoginReq(BaseModel):
    name: str
    pin: str


@router.post("/api/login")
def login(req: LoginReq, resp: Response):
    doc = _doc()
    if req.name not in doc["players"] or not league.check_pin(doc, req.name, req.pin):
        raise HTTPException(401, "bad name or pin")
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
def get_league(name: str = Depends(current_user)):
    doc = _doc()
    last = (doc.get("logged_in") or {}).get(name) or 0
    if doc["status"] != "lobby" or time.time() - last < TOUCH_EVERY:
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


class PickReq(BaseModel):
    team: str


@router.post("/api/league/pick")
def pick(req: PickReq, name: str = Depends(current_user)):
    return _run(lambda d: league.pick(d, name, req.team, time.time()))


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
def get_messages(since: float | None = None, _: str = Depends(current_user)):
    _doc()
    return get_store().messages(since)


STANDINGS_STALE_AFTER = 6 * 3600


@router.get("/api/standings")
def get_standings(refresh: int = 0, name: str = Depends(current_user)):
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


@router.post("/internal/refresh-standings", include_in_schema=False)
def internal_refresh_standings(x_refresh_token: str | None = Header(default=None)):
    expected = os.environ.get("REFRESH_TOKEN")
    if not expected:
        raise HTTPException(503, "refresh token not configured")
    if not x_refresh_token or not hmac.compare_digest(x_refresh_token, expected):
        raise HTTPException(403, "forbidden")
    doc = _standings.refresh_standings(get_store())
    if not doc["ok"]:
        return JSONResponse(status_code=503, content={
            "ok": False, "fetched_at": doc["fetched_at"], "error": doc["error"]})
    return {"ok": True, "fetched_at": doc["fetched_at"],
            "teams_with_wins": sum(1 for w in doc["wins"].values() if w > 0)}
