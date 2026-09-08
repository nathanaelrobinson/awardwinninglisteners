import hashlib
import hmac
import os

from fastapi import HTTPException, Request, Response

COOKIE = "wp_session"
MAX_AGE = 200 * 24 * 3600


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


def _secure_cookie() -> bool:
    """Mark the cookie HTTPS-only whenever the browser actually sees HTTPS:
    Cloud Run (K_SERVICE), or behind the Cloudflare tunnel on the Pi
    (WINSPOOL_BEHIND_PROXY=1). Plain http://localhost dev stays non-secure."""
    return (os.environ.get("K_SERVICE") is not None
            or os.environ.get("WINSPOOL_BEHIND_PROXY") == "1")


def set_cookie(resp: Response, name: str) -> None:
    resp.set_cookie(COOKIE, sign(name), max_age=MAX_AGE, httponly=True,
                    samesite="lax", secure=_secure_cookie())


def current_user(request: Request) -> str:
    name = verify(request.cookies.get(COOKIE))
    if name is None:
        raise HTTPException(401, "login required")
    return name


def viewer(request: Request) -> str | None:
    """Read-only access: any logged-in player, or anyone at all once the draft
    is done (post-draft standings and projections are shared with friends).
    Returns the player name, or None for an anonymous viewer."""
    import sqlite3

    from google.api_core import exceptions as gexc

    from .store import get_store
    name = verify(request.cookies.get(COOKIE))
    if name is not None:
        return name
    try:
        doc = get_store().get()
    except LookupError:
        raise HTTPException(503, "league not initialized")
    except (gexc.GoogleAPICallError, gexc.RetryError, sqlite3.OperationalError):
        raise HTTPException(503, "busy")
    if doc["status"] != "done":
        raise HTTPException(401, "login required")
    return None


def require_commissioner(request: Request) -> str:
    import sqlite3

    from google.api_core import exceptions as gexc

    from .store import get_store
    name = current_user(request)
    try:
        doc = get_store().get()
    except LookupError:
        raise HTTPException(503, "league not initialized")
    except (gexc.GoogleAPICallError, gexc.RetryError, sqlite3.OperationalError):
        raise HTTPException(503, "busy")
    if name != doc["commissioner"]:
        raise HTTPException(403, "commissioner only")
    return name
