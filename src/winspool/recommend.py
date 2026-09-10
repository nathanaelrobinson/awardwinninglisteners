import os
import numpy as np
from .data import load_schedule, schedule_matchups, load_win_totals
from .ratings import strength_from_totals
from .sim import simulate, simulate_mixture
from .draft import player_totals, pwin, PICK_ORDER, greedy_pick

def _assemble_sources(totals_path, power_path, home, away, kalshi_dist_path,
                      store=None):
    """Build the {name: strength} source dict for the mixture, plus a per-team
    Kalshi target-SD array (NaN where the market has no data). Adds a distinct
    'kalshi' voice (backed out of the implied line) when the dist file exists.
    When `store` is given the ratings come from it and the paths are ignored."""
    from .data import load_power_ratings
    from .ratings import backout_market
    from .game import HFA, SCALE
    from .teams import TEAM_INDEX, N_TEAMS
    if store is not None:
        from .data import sources_from_store
        raw, target_sd = sources_from_store(store)
        sources = {}
        for name, val in raw.items():
            # the loader defers backout_market to here, the only place that
            # knows the schedule; the marker goes no further than this loop
            if isinstance(val, tuple) and val[0] == "__totals__":
                sources[name] = backout_market(val[1], home, away, hfa=HFA, scale=SCALE)
            else:
                sources[name] = val
        return sources, target_sd
    totals = load_win_totals(totals_path)
    sources = {"vegas": backout_market(totals, home, away, hfa=HFA, scale=SCALE)}
    if power_path:
        pdf = load_power_ratings(power_path)
        for col in pdf.columns:
            arr = np.zeros(N_TEAMS)
            for code, val in pdf[col].items():
                arr[TEAM_INDEX[code]] = float(val)
            sources[col] = arr
    target_sd = np.full(N_TEAMS, np.nan)
    if kalshi_dist_path and os.path.exists(kalshi_dist_path):
        from .market import load_distributions
        from .fetch.kalshi import pmf_line, pmf_sd
        codes, mat = load_distributions(kalshi_dist_path)
        line = np.full(N_TEAMS, np.nan)
        for code, row in zip(codes, mat):
            if code in TEAM_INDEX:
                line[TEAM_INDEX[code]] = pmf_line(row)
                target_sd[TEAM_INDEX[code]] = pmf_sd(row)
        line[np.isnan(line)] = np.nanmean(line)          # mirror load_win_totals
        sources["kalshi"] = backout_market(line, home, away, hfa=HFA, scale=SCALE)
    return sources, target_sd


def build_wins(schedule_path, totals_path, n_seasons=20000, seed=0,
               power_path=None, tie_base=0.003, base_sigma=4.5, spread_k=2.0,
               kalshi_dist_path="data/cache/kalshi_distributions.csv"):
    """Ensemble every available source into the season sim WITHOUT anchoring on
    any one. Vegas (covers, backed out of the O/U), Kalshi (its own voice), and
    each power column vote equally. The mixture samples which world is real; the
    per-team season variance is calibrated to Kalshi's implied SD when available
    (see ratings.calibrate_sigma), else a flat base_sigma."""
    from .ratings import ensemble, to_common_scale, calibrate_sigma
    df = load_schedule(schedule_path)
    home, away = schedule_matchups(df)
    sources, target_sd = _assemble_sources(totals_path, power_path, home, away,
                                           kalshi_dist_path)
    strengths, _ = ensemble(sources, base_sigma=base_sigma, spread_k=spread_k)
    rng = np.random.default_rng(seed)
    if len(sources) > 1:
        sigma = base_sigma
        if np.any(~np.isnan(target_sd)):
            sigma = calibrate_sigma(strengths, home, away, target_sd,
                                    sigma_ref=base_sigma, tie_base=tie_base, seed=seed)
        wins = simulate_mixture(to_common_scale(sources), home, away, n_seasons,
                                base_sigma=sigma, tie_base=tie_base, rng=rng)
    else:
        _, sigma = ensemble(sources, base_sigma=base_sigma, spread_k=spread_k)
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
    """Fraction of rollouts in which each available team is still on the board
    when I NEXT pick. If it's my turn right now, this looks a full round-trip
    ahead — "if I pass now, will it come back to me at my next pick?" — which is
    the actual take-now-or-wait question (a plain 'to my next pick' would be 0
    steps on my turn and report 100% for everything)."""
    me = state.my_player
    board = state.board()
    n = len(PICK_ORDER)
    i = len(state.picks)
    until = 0
    if i < n and PICK_ORDER[i] == me:      # my turn: consume this pick first
        i += 1
        until += 1
    while i < n and PICK_ORDER[i] != me:   # then count opponents to my next turn
        i += 1
        until += 1
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
    # Common random numbers: evaluate EVERY candidate against the same set of
    # random draft continuations (re-seed a fresh generator per candidate from
    # one base seed). The only thing that differs between candidates is the team
    # they take now, so the pwin comparison is paired — far lower variance than
    # independent draws, which otherwise let a worse team randomly rank #1.
    base = int(rng.integers(2**63))
    out = []
    for t in cand:
        crng = np.random.default_rng(base)
        scores = []
        for _ in range(n_rollouts):
            st = state.copy()
            st.apply_pick(t)  # take candidate now (as me)
            final = playout(st, wins, self_policy, opp_policy, crng)
            scores.append(pwin(final.rosters(), wins, me))
        out.append({"team": t, "pwin": float(np.mean(scores)),
                    "survival": survive.get(t, 1.0)})
    out.sort(key=lambda r: r["pwin"], reverse=True)
    return out
