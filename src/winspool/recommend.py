import numpy as np
from .data import load_schedule, schedule_matchups, load_win_totals
from .ratings import strength_from_totals
from .sim import simulate
from .draft import player_totals, pwin, PICK_ORDER, greedy_pick

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

def playout(state, wins, self_policy, opp_policy, rng):
    st = state.copy()
    while not st.done and st.board():
        player = st.current_player
        pol = self_policy if player == st.my_player else opp_policy
        st.apply_pick(pol(st, player, rng))
    return st

def survival_probs(state, wins, self_policy, opp_policy, *, n_rollouts, rng):
    """Fraction of rollouts in which each available team is still on the board at
    my next pick (opponents pick via opp_policy in between). 1.0 for every team
    when it is already my turn."""
    me = state.my_player
    board = state.board()
    until = state.picks_until_my_next()
    survive = {t: 0 for t in board}
    for _ in range(n_rollouts):
        st = state.copy()
        steps = 0
        while steps < until and not st.done and st.board():
            player = st.current_player
            pol = self_policy if player == me else opp_policy
            st.apply_pick(pol(st, player, rng))
            steps += 1
        still_up = set(st.board())
        for t in board:
            if t in still_up:
                survive[t] += 1
    return {t: survive[t] / n_rollouts for t in board}


def pwin_after_playout(state, wins, self_policy, opp_policy, *, n_rollouts, rng):
    """Honest P(I win) given the board so far: play the rest of the draft out
    (me via self_policy, opponents via opp_policy) and average my P(win)."""
    me = state.my_player
    scores = [pwin(playout(state, wins, self_policy, opp_policy, rng).rosters(), wins, me)
              for _ in range(n_rollouts)]
    return float(np.mean(scores)) if scores else None


def rollout_recommend(state, wins, self_policy, opp_policy, *, n_rollouts=300, rng,
                      candidates=None):
    """Rank draft picks by my resulting P(win). Must be my turn (guarded).
    `candidates` limits which available teams are evaluated (e.g. a naive
    prescreen of the top N) to keep it fast; defaults to the whole board."""
    me = state.my_player
    if state.current_player != me:
        raise ValueError("rollout_recommend requires it to be my turn "
                         f"(on the clock: player {state.current_player}, me: {me})")
    board = state.board()
    cand = [t for t in (candidates if candidates is not None else board) if t in board]
    survive = survival_probs(state, wins, self_policy, opp_policy,
                             n_rollouts=n_rollouts, rng=rng)
    out = []
    for t in cand:
        scores = []
        for _ in range(n_rollouts):
            st = state.copy()
            st.apply_pick(t)  # take candidate now (as me)
            final = playout(st, wins, self_policy, opp_policy, rng)
            scores.append(pwin(final.rosters(), wins, me))
        out.append({"team": t, "pwin": float(np.mean(scores)),
                    "survival": survive.get(t, 1.0)})
    out.sort(key=lambda r: r["pwin"], reverse=True)
    return out
