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

from .analysis import team_attributes, roster_ceiling
from .data import load_schedule, load_win_totals, schedule_matchups
from .draft import DraftState, PICK_ORDER, player_totals, pwin
from .mock import auto_draft
from .opponents import chalk_power, entropy, greedy_self
from .recommend import (build_wins, naive_recommend, pwin_after_playout,
                        rollout_recommend, survival_probs)
from .teams import DIVISION, N_PLAYERS, N_TEAMS, TEAM_INDEX, TEAM_NAMES, TEAMS

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE = REPO_ROOT / "data" / "cache"
SCHEDULE = CACHE / "schedule_2026.csv"
TOTALS = CACHE / "win_totals.csv"
POWER = CACHE / "power_ratings.csv"
KALSHI = CACHE / "kalshi_distributions.csv"

N_SEASONS = 8000     # served matrix depth
FAST_ROWS = 5000     # subsample used for the per-request rollouts (speed)
TOP_K = 14           # rollout only the top-K naive candidates
ROLLOUTS = 150       # rollouts per request (with common-random-numbers below)

app = FastAPI(title="winspool")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_STATE: dict = {}


MATRIX_CACHE = CACHE / "sim_matrix.npz"


def _cache_key():
    """Signature of the inputs the sim depends on — rebuild when any changes."""
    parts = [str(N_SEASONS)]
    for f in (SCHEDULE, TOTALS, POWER, KALSHI):
        parts.append(str(f.stat().st_mtime_ns) if f.exists() else "0")
    return "|".join(parts)


def _plays_matrix():
    """plays[i][j] = number of scheduled 2026 games between teams i and j."""
    home, away = schedule_matchups(load_schedule(str(SCHEDULE)))
    m = np.zeros((N_TEAMS, N_TEAMS), dtype=int)
    for h, a in zip(home, away):
        m[h][a] += 1
        m[a][h] += 1
    return m


def _populate(wins, strengths):
    _STATE["wins"] = wins
    _STATE["wins_fast"] = wins[:FAST_ROWS]
    _STATE["strengths"] = strengths
    _STATE["totals"] = load_win_totals(str(TOTALS))
    _STATE["attrs"] = {a["team"]: a for a in team_attributes(wins)}
    _STATE["plays"] = _plays_matrix()


def _ensure_ready():
    if _STATE:
        return
    key = _cache_key()
    if MATRIX_CACHE.exists():
        try:
            z = np.load(MATRIX_CACHE, allow_pickle=False)
            if str(z["key"]) == key:
                _populate(z["wins"], z["strengths"])
                return
        except Exception:
            pass  # stale/corrupt cache -> rebuild
    power_path = str(POWER) if POWER.exists() else None
    kalshi_path = str(KALSHI) if KALSHI.exists() else None
    wins, strengths = build_wins(str(SCHEDULE), str(TOTALS), n_seasons=N_SEASONS,
                                 seed=0, power_path=power_path,
                                 kalshi_dist_path=kalshi_path)
    try:
        np.savez(MATRIX_CACHE, wins=wins, strengths=strengths, key=np.array(key))
    except Exception:
        pass
    _populate(wins, strengths)


@app.on_event("startup")
def _startup():
    # Build (or load cached) the sim during boot so the first page load is instant.
    _ensure_ready()


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


def _recommend_policies(opp_model):
    """(opponent, self) pick policies used in the recommender's rollouts.
    Opponents draft per the chosen field model (chalky, with some noise so
    survival is a real probability); I draft chalky by our ensemble strength."""
    strengths, totals = _STATE["strengths"], _STATE["totals"]
    if opp_model == "power":
        opp = entropy(strengths, temperature=3.0)
    elif opp_model == "random":
        opp = entropy(strengths, temperature=20.0)
    else:  # "market" (default): the field drafts chalky by Vegas O/U
        opp = entropy(totals, temperature=2.0)
    me = entropy(strengths, temperature=2.5)
    return opp, me


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
    mode: str = "rollout"       # "rollout" (opponent-aware) | "naive" (instant)
    opp_model: str = "market"   # how the field drafts: market | power | random
    seed: int = 0


@app.post("/api/recommend")
def recommend(req: RecReq):
    _ensure_ready()
    wins, wins_fast, strengths = _STATE["wins"], _STATE["wins_fast"], _STATE["strengths"]
    state = _state_from(req.slot, req.taken)
    rng = np.random.default_rng(req.seed)
    # Opponent model (draft-mechanics exploit): assume the field drafts the way
    # you say they do — "market" = chalky by Vegas O/U (the default, since your
    # league drafts off the number). This drives survival ("will it fall to
    # me?") and the rollout, so the tool grabs scarce teams and lets value come
    # back. I draft chalky by OUR ensemble view, so where the ensemble and the
    # market disagree, the recommender exploits what the field lets slide.
    opp, self_fast = _recommend_policies(req.opp_model)

    rosters = state.rosters()
    my_turn = (not state.done) and state.current_player == req.slot
    plays = _STATE["plays"]
    my_idx = rosters[req.slot]
    # cannibalization: games among my own teams (each caps combined ceiling by 1)
    my_intra = int(sum(plays[my_idx[i]][my_idx[j]]
                       for i in range(len(my_idx)) for j in range(i + 1, len(my_idx))))

    def conflict(ti):  # games team ti plays against my current roster
        return int(sum(plays[ti][r] for r in my_idx))

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
            attrs = _STATE["attrs"]
            recs = [{"code": TEAMS[r["team"]], "pwin": round(r["pwin"], 4),
                     "survival": round(surv.get(r["team"], 1.0), 3),
                     "delta_wins": round(naive_by[r["team"]]["delta_wins"], 2),
                     "ceiling": round(attrs[r["team"]]["ceiling"], 3),
                     "roster_ceiling": round(roster_ceiling(wins, my_idx + [r["team"]]), 2),
                     "conflict": conflict(r["team"])}
                    for r in roll]
            # Winner-take-all tie-break: among candidates whose P(win) are within
            # ~1 pt (i.e. inside the estimator's noise), prefer the higher ROSTER
            # ceiling — the upper tail of MY combined total with this team added,
            # i.e. how high my roster realistically spikes. It's the right upside
            # measure for a winner-take-all tie (you have to spike to win) because
            # it scores my actual roster, not a team in isolation. Early in the
            # draft P(win) is degenerate (a small roster co-leads most seasons),
            # so this tiebreak carries the ranking. (Roster correlation — e.g. two
            # of my teams playing — is priced in automatically, at the small
            # magnitude it actually deserves; it is not a special-cased penalty.)
            recs.sort(key=lambda r: (round(r["pwin"], 2), r["roster_ceiling"]), reverse=True)
        else:
            # Targets watchlist (also the "quick"/naive view): rank by value,
            # annotate how likely each is to still be there at my next pick.
            recs = [{"code": TEAMS[r["team"]], "pwin": round(r["pwin"], 4),
                     "survival": round(surv.get(r["team"], 1.0), 3),
                     "delta_wins": round(r["delta_wins"], 2),
                     "conflict": conflict(r["team"])}
                    for r in naive[:20]]

    # Opponents' projected ("ideal") picks between now and my next turn, so the
    # board can show what's likely to fall to me. Uses the field model's best
    # available pick per seat (deterministic chalk on the model's key).
    forecast = []
    if not state.done:
        key = _STATE["totals"] if req.opp_model == "market" else strengths
        fs = state.copy()
        guard = 0
        while (not fs.done and fs.current_player != req.slot and guard < 16):
            b = fs.board()
            t = max(b, key=lambda i: key[i])
            forecast.append({"pick": len(fs.picks) + 1,
                             "player": fs.current_player, "code": TEAMS[t]})
            fs.apply_pick(t)
            guard += 1

    return {
        "current_player": state.current_player,
        "my_turn": my_turn,
        "my_next_in": state.picks_until_my_next(),
        "done": state.done,
        "p_win_me": p_win_me,
        "rosters": {p: [TEAMS[t] for t in ts] for p, ts in rosters.items()},
        "recommendations": recs,
        "survival_all": {TEAMS[t]: round(p, 3) for t, p in surv.items()},
        "forecast": forecast,
        "my_intra_games": my_intra,
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


class ResultsReq(BaseModel):
    slot: int
    taken: list[str] = []


@app.post("/api/results")
def results(req: ResultsReq):
    """Final standings from the joint season sim: each player's projected
    combined wins, P(win the pool), and a 10th–90th pct range."""
    _ensure_ready()
    wins = _STATE["wins"]
    rosters = _state_from(req.slot, req.taken).rosters()
    totals = player_totals(rosters, wins)          # (N, N_PLAYERS)
    rowmax = totals.max(axis=1)
    lo, hi = int(totals.min()), int(totals.max())
    xs = list(range(lo, hi + 1))
    out = []
    for p in range(1, N_PLAYERS + 1):
        col = totals[:, p - 1]
        counts = np.bincount((col - lo).astype(int), minlength=len(xs))
        out.append({
            "player": p,
            "is_me": p == req.slot,
            "teams": [TEAMS[t] for t in rosters[p]],
            "exp_wins": round(float(col.mean()), 1),
            "pwin": round(float((col >= rowmax).mean()), 3),
            "p10": int(np.percentile(col, 10)),
            "p90": int(np.percentile(col, 90)),
            "dist": (counts / counts.sum()).round(5).tolist(),  # prob per x in xs
        })
    out.sort(key=lambda r: r["exp_wins"], reverse=True)
    return {"standings": out, "x": xs, "n_sims": int(wins.shape[0])}


class SampleReq(BaseModel):
    slot: int
    taken: list[str] = []
    seed: int = 0


@app.post("/api/sample_season")
def sample_season(req: SampleReq):
    """Play out ONE concrete season sampled from the joint distribution (so the
    correlated, teams-play-each-other structure shows up in a single outcome)."""
    _ensure_ready()
    wins = _STATE["wins"]
    rng = np.random.default_rng(req.seed)
    row = int(rng.integers(0, wins.shape[0]))
    season = wins[row]
    rosters = _state_from(req.slot, req.taken).rosters()
    out = []
    for p in range(1, N_PLAYERS + 1):
        teams = [{"code": TEAMS[t], "wins": int(season[t])} for t in rosters[p]]
        out.append({
            "player": p, "is_me": p == req.slot,
            "teams": sorted(teams, key=lambda x: x["wins"], reverse=True),
            "total_wins": int(sum(t["wins"] for t in teams)),
        })
    out.sort(key=lambda r: r["total_wins"], reverse=True)
    top = out[0]["total_wins"] if out else 0
    return {"standings": out, "winners": [r["player"] for r in out if r["total_wins"] == top]}


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
