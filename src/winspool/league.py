"""Pure state machine for the live league. Every function takes the league
dict and returns a NEW dict (never mutates), so the store can wrap it in a
transaction and tests never touch a real store."""
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


def new_league(players, commissioner, pins: dict[str, str]):
    players = list(players)
    if len(players) != N_PLAYERS or len(set(players)) != N_PLAYERS:
        raise LeagueError(400, f"need {N_PLAYERS} distinct players")
    if commissioner not in players:
        raise LeagueError(400, "commissioner must be a player")
    for name in players:
        if not pins.get(name):
            raise LeagueError(400, f"missing pin for {name!r}")
    stored_pins = {}
    for name in players:
        salt = secrets.token_hex(8)
        stored_pins[name] = {"salt": salt, "hash": _hash(pins[name], salt)}
    return {
        "players": players,
        "commissioner": commissioner,
        "pins": stored_pins,
        "slots": None,
        "status": "lobby",
        "picks": [],
        "overrides": {},
        "logged_in": {},
    }


def check_pin(doc, name, pin) -> bool:
    entry = doc["pins"].get(name)
    if entry is None:
        # Still do a compare so unknown-name lookups aren't a timing oracle.
        secrets.compare_digest(_hash(pin or "", "x"), "x")
        return False
    return secrets.compare_digest(_hash(pin or "", entry["salt"]), entry["hash"])


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


def restart(doc):
    """Return to lobby from any state, keeping players/commissioner/pins/
    overrides/logged_in but clearing picks and slots."""
    d = copy.deepcopy(doc)
    d["picks"] = []
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
