"""FastAPI backend for the live-draft UI + auto-sim.

Precomputes the season sim once at startup, then serves team metadata,
draft-state-aware pick recommendations, an honest P(I win), and Monte-Carlo
auto-draft simulations. The built React front end (web/dist) mounts at /.

Run: uv run winspool-serve
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
from .mock import auto_draft
from .opponents import chalk_power, entropy, greedy_self
from .recommend import (build_wins, naive_recommend, pwin_after_playout,
                        rollout_recommend, survival_probs)
from .teams import DIVISION, N_PLAYERS, TEAM_INDEX, TEAM_NAMES, TEAMS

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE = REPO_ROOT / "data" / "cache"
SCHEDULE = CACHE / "schedule_2026.csv"
TOTALS = CACHE / "win_totals.csv"
POWER = CACHE / "power_ratings.csv"

N_SEASONS = 8000     # served matrix depth
FAST_ROWS = 5000     # subsample used for the per-request rollouts (speed)
TOP_K = 14           # rollout only the top-K naive candidates
ROLLOUTS = 40        # rollouts per request

app = FastAPI(title="winspool")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_STATE: dict = {}


def _ensure_ready():
    if _STATE:
        return
    power_path = str(POWER) if POWER.exists() else None
    wins, strengths = build_wins(str(SCHEDULE), str(TOTALS), n_seasons=N_SEASONS,
                                 seed=0, power_path=power_path)
    _STATE["wins"] = wins
    _STATE["wins_fast"] = wins[:FAST_ROWS]
    _STATE["strengths"] = strengths
    _STATE["totals"] = load_win_totals(str(TOTALS))
    _STATE["attrs"] = {a["team"]: a for a in team_attributes(wins)}


def _state_from(slot, taken):
    st = DraftState(my_player=slot)
    for code in taken:
        st.apply_pick(TEAM_INDEX[code.strip().upper()])
    return st


def _strategy_policy(name):
    """Map a strategy name to an opponent/self pick policy."""
    strengths, totals, wins = _STATE["strengths"], _STATE["totals"], _STATE["wins_fast"]
    if name == "market":       # always take the highest posted win total
        return chalk_power(totals)
    if name == "power":        # highest blended power rating
        return chalk_power(strengths)
    if name == "random":       # chaotic, mild lean to good teams
        return entropy(strengths, temperature=20.0)
    if name == "optimal":      # greedy by marginal P(win)
        return greedy_self(wins)
    raise ValueError(f"unknown strategy: {name}")


@app.get("/api/teams")
def teams():
    _ensure_ready()
    attrs, totals, strengths = _STATE["attrs"], _STATE["totals"], _STATE["strengths"]
    out = []
    for i, code in enumerate(TEAMS):
        a = attrs[i]
        out.append({
            "code": code, "name": TEAM_NAMES[code], "division": DIVISION[code],
            "win_total": round(float(totals[i]), 1), "strength": round(float(strengths[i]), 2),
            "mean": round(a["mean"], 2), "sd": round(a["sd"], 2),
            "ceiling": round(a["ceiling"], 3), "floor": round(a["floor"], 3),
        })
    return {"teams": out, "pick_order": PICK_ORDER, "n_players": N_PLAYERS}


class RecReq(BaseModel):
    slot: int
    taken: list[str] = []
    mode: str = "rollout"   # "rollout" (opponent-aware) | "naive" (instant)
    seed: int = 0


@app.post("/api/recommend")
def recommend(req: RecReq):
    _ensure_ready()
    wins, wins_fast, strengths = _STATE["wins"], _STATE["wins_fast"], _STATE["strengths"]
    state = _state_from(req.slot, req.taken)
    rng = np.random.default_rng(req.seed)
    # Symmetric fill: model every remaining pick (mine and opponents') with the
    # same high-entropy policy, so P(win) reflects the edge from picks already
    # made rather than a rigged self-advantage. Candidate ranking still works
    # because only the tentatively-taken team differs between candidates.
    opp = entropy(strengths, temperature=8.0)
    self_fast = opp

    rosters = state.rosters()
    my_turn = (not state.done) and state.current_player == req.slot

    # Honest P(I win): play the remaining draft out and average my P(win).
    p_win_me = None if state.done else round(
        pwin_after_playout(state, wins_fast, self_fast, opp,
                           n_rollouts=ROLLOUTS, rng=rng), 3)

    naive = naive_recommend(state, wins)
    naive_by = {r["team"]: r for r in naive}
    surv = ({} if state.done else
            survival_probs(state, wins_fast, self_fast, opp, n_rollouts=ROLLOUTS, rng=rng))

    recs = []
    if not state.done:
        if my_turn and req.mode == "rollout":
            top = [r["team"] for r in naive[:TOP_K]]
            roll = rollout_recommend(state, wins_fast, self_fast, opp,
                                     n_rollouts=ROLLOUTS, rng=rng, candidates=top)
            recs = [{"code": TEAMS[r["team"]], "pwin": round(r["pwin"], 4),
                     "survival": round(surv.get(r["team"], 1.0), 3),
                     "delta_wins": round(naive_by[r["team"]]["delta_wins"], 2)}
                    for r in roll]
        else:
            # Targets watchlist (also the "quick"/naive view): rank by value,
            # annotate how likely each is to still be there at my next pick.
            recs = [{"code": TEAMS[r["team"]], "pwin": round(r["pwin"], 4),
                     "survival": round(surv.get(r["team"], 1.0), 3),
                     "delta_wins": round(r["delta_wins"], 2)}
                    for r in naive[:20]]

    return {
        "current_player": state.current_player,
        "my_turn": my_turn,
        "my_next_in": state.picks_until_my_next(),
        "done": state.done,
        "p_win_me": p_win_me,
        "rosters": {p: [TEAMS[t] for t in ts] for p, ts in rosters.items()},
        "recommendations": recs,
    }


class SimReq(BaseModel):
    slot: int
    my_strategy: str = "optimal"
    opp_strategy: str = "market"
    # Optional per-seat strategies, e.g. {"1":"market","2":"random",...}. When
    # given, each seat uses its own strategy (my_strategy/opp_strategy are the
    # fallback for any seat not listed).
    strategies: dict[str, str] | None = None
    n_sims: int = 150
    seed: int = 0


@app.post("/api/autosim")
def autosim(req: SimReq):
    _ensure_ready()
    wins_fast = _STATE["wins_fast"]
    rng = np.random.default_rng(req.seed)
    policies = {}
    for p in range(1, N_PLAYERS + 1):
        if req.strategies and str(p) in req.strategies:
            name = req.strategies[str(p)]
        else:
            name = req.my_strategy if p == req.slot else req.opp_strategy
        policies[p] = _strategy_policy(name)

    pwins = []
    for _ in range(req.n_sims):
        final = auto_draft(wins_fast, policies, my_player=req.slot, rng=rng)
        pwins.append(pwin(final.rosters(), wins_fast, req.slot))
    arr = np.array(pwins)
    # "win share" against a field of 5 = mean P(win); 0.20 would be neutral.
    return {
        "slot": req.slot, "my_strategy": req.my_strategy, "opp_strategy": req.opp_strategy,
        "n_sims": req.n_sims,
        "win_pct": round(float(arr.mean()) * 100, 1),
        "p10": round(float(np.percentile(arr, 10)) * 100, 1),
        "p90": round(float(np.percentile(arr, 90)) * 100, 1),
        "fair_share": round(100 / N_PLAYERS, 1),
    }


class AdvanceReq(BaseModel):
    slot: int
    taken: list[str] = []
    opp_strategy: str = "market"
    seed: int = 0


@app.post("/api/advance")
def advance(req: AdvanceReq):
    """Auto-pick for the other seats (via opp_strategy) until it is my turn or
    the draft is complete. Returns the extended taken list."""
    _ensure_ready()
    rng = np.random.default_rng(req.seed)
    pol = _strategy_policy(req.opp_strategy)
    st = _state_from(req.slot, req.taken)
    while not st.done and st.board() and st.current_player != req.slot:
        st.apply_pick(pol(st, st.current_player, rng))
    return {
        "taken": [TEAMS[t] for _, t in st.picks],
        "current_player": st.current_player,
        "my_turn": (not st.done) and st.current_player == req.slot,
        "done": st.done,
    }


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
