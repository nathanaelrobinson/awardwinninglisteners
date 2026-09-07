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
    from google.api_core import exceptions as gexc

    from .store import get_store
    name = current_user(request)
    try:
        doc = get_store().get()
    except LookupError:
        raise HTTPException(503, "league not initialized")
    except (gexc.GoogleAPICallError, gexc.RetryError):
        raise HTTPException(503, "busy")
    if name != doc["commissioner"]:
        raise HTTPException(403, "commissioner only")
    return name
