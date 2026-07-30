import numpy as np
from .data import load_schedule, schedule_matchups, load_win_totals
from .ratings import strength_from_totals
from .sim import simulate
from .draft import player_totals, pwin

def build_wins(schedule_path, totals_path, n_seasons=20000, seed=0,
               power_path=None, w=0.65, tie_base=0.003):
    from .data import load_power_ratings
    from .ratings import (backout_market, power_strength, blend, team_sigma,
                          strength_from_totals)
    from .game import HFA, SCALE
    df = load_schedule(schedule_path)
    home, away = schedule_matchups(df)
    totals = load_win_totals(totals_path)
    market = backout_market(totals, home, away, hfa=HFA, scale=SCALE)
    if power_path:
        pdf = load_power_ratings(power_path)
        strengths = blend(market, power_strength(pdf), w=w)
        sigma = team_sigma(pdf)
    else:
        strengths = market
        sigma = np.full(strengths.size, 6.0)
    rng = np.random.default_rng(seed)
    wins = simulate(strengths, sigma, home, away, n_seasons, tie_base=tie_base, rng=rng)
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
