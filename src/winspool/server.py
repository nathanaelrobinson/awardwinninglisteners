"""FastAPI backend for the live-draft UI.

Precomputes the season sim once at startup, then serves team metadata and
draft-state-aware pick recommendations. The React front end (web/dist) is
mounted at / when it has been built.

Run: uv run winspool-serve   (or: uv run uvicorn winspool.server:app)
"""
import argparse
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analysis import team_attributes
from .data import load_win_totals
from .draft import DraftState, PICK_ORDER, pwin
from .opponents import entropy, greedy_self
from .recommend import build_wins, naive_recommend, rollout_recommend
from .teams import DIVISION, N_PLAYERS, TEAM_INDEX, TEAM_NAMES, TEAMS

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE = REPO_ROOT / "data" / "cache"
SCHEDULE = CACHE / "schedule_2026.csv"
TOTALS = CACHE / "win_totals.csv"

# How many simulated seasons back the served matrix. Kept modest so startup is
# quick and naive recommendations are instant; rollout is opt-in per request.
N_SEASONS = 8000

app = FastAPI(title="winspool")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_STATE: dict = {}


POWER = CACHE / "power_ratings.csv"


def _ensure_ready():
    if _STATE:
        return
    power_path = str(POWER) if POWER.exists() else None
    wins, strengths = build_wins(str(SCHEDULE), str(TOTALS), n_seasons=N_SEASONS,
                                 seed=0, power_path=power_path)
    _STATE["wins"] = wins
    _STATE["strengths"] = strengths
    _STATE["attrs"] = {a["team"]: a for a in team_attributes(wins)}
    _STATE["totals"] = load_win_totals(str(TOTALS))


@app.get("/api/teams")
def teams():
    _ensure_ready()
    attrs, totals, strengths = _STATE["attrs"], _STATE["totals"], _STATE["strengths"]
    out = []
    for i, code in enumerate(TEAMS):
        a = attrs[i]
        out.append({
            "code": code,
            "name": TEAM_NAMES[code],
            "division": DIVISION[code],
            "win_total": round(float(totals[i]), 1),
            "strength": round(float(strengths[i]), 2),
            "mean": round(a["mean"], 2),
            "sd": round(a["sd"], 2),
            "ceiling": round(a["ceiling"], 3),
            "floor": round(a["floor"], 3),
        })
    return {"teams": out, "pick_order": PICK_ORDER, "n_players": N_PLAYERS}


class RecReq(BaseModel):
    slot: int
    taken: list[str] = []
    mode: str = "naive"        # "naive" (instant) | "rollout" (opponent-aware)
    rollouts: int = 60
    temp: float = 8.0
    seed: int = 0


@app.post("/api/recommend")
def recommend(req: RecReq):
    _ensure_ready()
    wins, strengths = _STATE["wins"], _STATE["strengths"]
    state = DraftState(my_player=req.slot)
    for code in req.taken:
        state.apply_pick(TEAM_INDEX[code.strip().upper()])

    rosters = state.rosters()
    has_picks = any(rosters.values())
    p_win_me = round(pwin(rosters, wins, req.slot), 3) if has_picks else None

    recs = []
    my_turn = (not state.done) and state.current_player == req.slot
    if my_turn:
        if req.mode == "rollout":
            rng = np.random.default_rng(req.seed)
            recs = rollout_recommend(
                state, wins, greedy_self(wins), entropy(strengths, req.temp),
                n_rollouts=req.rollouts, rng=rng,
            )
        else:
            recs = naive_recommend(state, wins)

    def as_code(rec):
        out = {"code": TEAMS[rec["team"]]}
        for k, v in rec.items():
            if k != "team":
                out[k] = round(float(v), 4)
        return out

    return {
        "current_player": state.current_player,
        "my_turn": my_turn,
        "my_next_in": state.picks_until_my_next(),
        "done": state.done,
        "p_win_me": p_win_me,
        "rosters": {p: [TEAMS[t] for t in ts] for p, ts in rosters.items()},
        "recommendations": [as_code(r) for r in recs],
    }


# Serve the built front end at / when present (single-command experience).
_DIST = REPO_ROOT / "web" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="static")


def main():
    import uvicorn
    ap = argparse.ArgumentParser(prog="winspool-serve")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
