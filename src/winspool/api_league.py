import random
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from . import league
from . import standings as _standings
from .auth import current_user, require_commissioner, set_cookie
from .league import LeagueError
from .store import get_store
from .teams import resolve

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
    try:
        doc = get_store().get()
    except LookupError:
        raise HTTPException(503, "league not initialized")
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
    try:
        get_store().get()
    except LookupError:
        raise HTTPException(503, "league not initialized")
    text = req.text.strip()
    if not text or len(text) > 500:
        raise HTTPException(400, "1-500 chars")
    return get_store().add_message(name, text)


@router.get("/messages")
def get_messages(since: float | None = None, _: str = Depends(current_user)):
    try:
        get_store().get()
    except LookupError:
        raise HTTPException(503, "league not initialized")
    return get_store().messages(since)


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
