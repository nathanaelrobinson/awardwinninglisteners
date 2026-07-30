import numpy as np
from .data import load_schedule, schedule_matchups, load_win_totals
from .ratings import strength_from_totals
from .sim import simulate
from .draft import player_totals, pwin

def build_wins(schedule_path, totals_path, n_seasons=20000, seed=0):
    df = load_schedule(schedule_path)
    home, away = schedule_matchups(df)
    totals = load_win_totals(totals_path)
    strengths = strength_from_totals(totals)
    sigma = np.full(strengths.size, 6.0)  # MVP: flat preseason uncertainty
    rng = np.random.default_rng(seed)
    wins = simulate(strengths, sigma, home, away, n_seasons, rng=rng)
    return wins, strengths

def naive_recommend(state, wins):
    rosters = state.rosters()
    me = state.my_player
    base_total = player_totals(rosters, wins)[:, me - 1].mean()
    out = []
    for t in state.board():
        rosters[me].append(t)
        score = pwin(rosters, wins, me)
        added = player_totals(rosters, wins)[:, me - 1].mean() - base_total
        rosters[me].pop()
        out.append({"team": t, "pwin": score, "delta_wins": added})
    out.sort(key=lambda r: (r["pwin"], r["delta_wins"]), reverse=True)
    return out
