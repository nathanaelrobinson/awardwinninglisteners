"""In-season live projection: banked wins plus a remaining-season Monte Carlo.

Pure functions over the nfl_data_py schedule frame (columns week, game_type,
home_team, away_team, home_score, away_score) and the ratings, which come from
the store in production and from CSV paths on a laptop with no store.
No network access except in refresh_live()."""
import os
import sys
import time
from datetime import datetime, timezone
from typing import NamedTuple

import numpy as np
import pandas as pd

from .game import win_prob, HFA, SCALE
from .market import load_distributions, sample_independent
from .ratings import calibrate_sigma, ensemble, to_common_scale
from .sim import simulate_mixture
from .teams import N_TEAMS, TEAM_INDEX, TEAMS

REG_COLS = ["week", "game_type", "home_team", "away_team", "home_score", "away_score"]
FINAL_WEEK = 18
SEASON = int(os.environ.get("WINSPOOL_SEASON", "2026"))


def _reg(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["game_type"].str.upper() == "REG"].reset_index(drop=True)


def split_schedule(df: pd.DataFrame):
    """(played, remaining) regular-season frames. A game is played when both
    scores are present."""
    reg = _reg(df)
    final = reg["home_score"].notna() & reg["away_score"].notna()
    return reg[final].reset_index(drop=True), reg[~final].reset_index(drop=True)


def banked_wins(played: pd.DataFrame) -> np.ndarray:
    """Real wins so far per team index. An NFL tie is 0 wins for both."""
    b = np.zeros(N_TEAMS)
    for r in played.itertuples(index=False):
        h, a = TEAM_INDEX[r.home_team], TEAM_INDEX[r.away_team]
        if r.home_score > r.away_score:
            b[h] += 1
        elif r.away_score > r.home_score:
            b[a] += 1
    return b


def played_outcomes(played: pd.DataFrame):
    """Decisive completed games as (home_idx, away_idx, home_won). Ties omitted."""
    if played.empty:
        return (np.array([], dtype=int), np.array([], dtype=int),
                np.array([], dtype=bool))
    decisive = played["home_score"] != played["away_score"]
    sl = played.loc[decisive]
    home = sl["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    away = sl["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    won = (sl["home_score"] > sl["away_score"]).to_numpy(dtype=bool)
    return home, away, won


def week_of(df: pd.DataFrame) -> int:
    """Smallest regular-season week with an unplayed game; FINAL_WEEK + 1 if none."""
    _, remaining = split_schedule(df)
    if remaining.empty:
        return FINAL_WEEK + 1
    return int(remaining["week"].min())


def remaining_matchups(remaining: pd.DataFrame):
    home = remaining["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    away = remaining["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    return home, away


def games_in_week(remaining: pd.DataFrame, week: int) -> pd.DataFrame:
    return remaining[remaining["week"] == week].reset_index(drop=True)


def remaining_games_per_team(remaining: pd.DataFrame) -> np.ndarray:
    home, away = remaining_matchups(remaining)
    per = np.zeros(N_TEAMS, dtype=int)
    np.add.at(per, home, 1)
    np.add.at(per, away, 1)
    return per


def week_home_p(matrix, weights, wh, wa, market=None):
    """Home-win P for this week's remaining games: market quote else blend.

    These are the same coins `compute_live` uses for the current week. Returns
    `(p, source)` aligned with `wh`/`wa`; source[i] is 'market' or 'model'.
    """
    n = len(wh)
    source = ["model"] * n
    if n == 0:
        return np.zeros(0), source
    strength = consensus(matrix, weights)
    p = np.asarray(win_prob(strength[wh], strength[wa]), dtype=float)
    if market:
        for g in range(n):
            mp = market.get((TEAMS[wh[g]], TEAMS[wa[g]]))
            if mp is not None:
                p[g] = float(mp)
                source[g] = "market"
    return p, source


BASE_SIGMA = 4.5
SPREAD_K = 2.0
TIE_BASE = 0.003


_ENSEMBLE_CACHE: dict = {}


def _mtime(path):
    return os.path.getmtime(path) if path and os.path.exists(path) else None


def ratings_stamp(store) -> float | None:
    """Newest fetched_at across the store's current rating sources, or None.

    A ratings refresh is the only thing that changes what the model reads, so
    this is both the cache key below and the doc's ratings_fetched_at."""
    stamps = [float(r["fetched_at"]) for r in store.latest_ratings().values()]
    return max(stamps) if stamps else None


class Ensemble(NamedTuple):
    """What the blend is built from. `sigma_calibrated` says whether
    calibrate_sigma actually ran; the market's target SDs and that flag are
    bookkeeping the projection itself never needs, but the operator view does —
    and reading them back from here is the only way it cannot disagree with
    what the model did."""
    sources: dict
    sigma: np.ndarray
    target_sd: np.ndarray
    sigma_calibrated: bool


def _ensemble(totals_path, power_path, kalshi_dist_path, home, away, seed=0,
              store=None, banked=None, cal_home=None, cal_away=None) -> Ensemble:
    """The same voices and the same Kalshi-calibrated per-team season sigma that
    Draft Review's pre-season build uses (recommend.build_wins), so the live
    model agrees with it before kickoff.
    Memoised on the ratings' freshness — the backouts and the calibration each
    take seconds, and only a refresh should invalidate them.

    `home`/`away` are the invert slate (remaining games in season). Sigma is
    still calibrated on the full season (`cal_home`/`cal_away`) because Kalshi
    target SDs are season-total SDs.
    """
    cal_home = home if cal_home is None else cal_home
    cal_away = away if cal_away is None else cal_away
    key = ((ratings_stamp(store),) if store is not None
           else (_mtime(totals_path), _mtime(power_path), _mtime(kalshi_dist_path)))
    banked_key = None if banked is None else tuple(float(x) for x in banked)
    key = (*key, tuple(int(x) for x in home), tuple(int(x) for x in away), banked_key)
    if key not in _ENSEMBLE_CACHE:
        from .recommend import _assemble_sources
        power = power_path if power_path and os.path.exists(power_path) else None
        sources, target_sd = _assemble_sources(totals_path, power, home, away,
                                               kalshi_dist_path, store=store,
                                               banked=banked)
        strengths, _ = ensemble(sources, base_sigma=BASE_SIGMA, spread_k=SPREAD_K)
        sigma = np.full(N_TEAMS, BASE_SIGMA)
        calibrated = len(sources) > 1 and bool(np.any(~np.isnan(target_sd)))
        if calibrated:
            sigma = np.asarray(calibrate_sigma(strengths, cal_home, cal_away, target_sd,
                                               sigma_ref=BASE_SIGMA, tie_base=TIE_BASE,
                                               seed=seed), dtype=float)
        _ENSEMBLE_CACHE[key] = Ensemble(sources, sigma, target_sd, calibrated)
    return _ENSEMBLE_CACHE[key]


def prior_weights(names) -> np.ndarray:
    """Dirichlet-mean prior over voices before any 2026 games are observed.

    If `market_strength` is present and it is not the only voice, it gets
    weight equal to the sum of the others (half the mixture). File-path
    / preseason builds have no `market_strength` and stay equal-weight.
    """
    names = list(names)
    w = np.ones(len(names))
    if "market_strength" in names and len(names) > 1:
        w[names.index("market_strength")] = len(names) - 1
    return w / w.sum()


def bma_loglik(matrix, home_idx, away_idx, home_won) -> np.ndarray:
    """Log P(completed games | voice) for each row of `matrix`.

    Empty games is a zero vector: the likelihood is 1 and does not move
    the prior.
    """
    matrix = np.asarray(matrix, dtype=float)
    n = matrix.shape[0]
    if len(home_idx) == 0:
        return np.zeros(n)
    y = np.asarray(home_won, dtype=float)
    ll = np.zeros(n)
    for k in range(n):
        p = np.clip(win_prob(matrix[k, home_idx], matrix[k, away_idx]), 1e-12, 1 - 1e-12)
        ll[k] = float(np.sum(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))
    return ll


def bma_weights(matrix, prior, home_idx, away_idx, home_won) -> np.ndarray:
    """Posterior mean over voices: P(k | games) ∝ prior_k * P(games | s_k).

    Each completed game is a Bernoulli observation under that voice's
    probit. No games leaves the prior unchanged. Weights always sum to 1.
    """
    prior = np.asarray(prior, dtype=float)
    if prior.size == 0:
        raise ValueError("bma_weights requires a prior")
    prior = prior / prior.sum()
    ll = bma_loglik(matrix, home_idx, away_idx, home_won)
    logw = np.log(np.clip(prior, 1e-12, 1.0)) + ll
    logw -= logw.max()
    w = np.exp(logw)
    return w / w.sum()


def posterior_strength(matrix, weights, home_idx, away_idx, home_won, *,
                       n_teams=None, prior_sd=8.0, voice_tau=None, hfa=None,
                       scale=None):
    """Gaussian posterior for team strengths given voices and completed games.

    Starts from N(0, prior_sd^2 I), treats each voice as an observation of
    s with noise voice_tau (scalar or per-voice), then extended-Kalman
    updates for each decisive game. Returns (mean, sd) on the 32-team
    (or n_teams) scale, mean-centred so the all-ones direction stays pinned.
    """
    from scipy.stats import norm as _norm
    matrix = np.asarray(matrix, dtype=float)
    n_src, n_obs = matrix.shape
    n_teams = n_obs if n_teams is None else int(n_teams)
    if n_obs != n_teams:
        raise ValueError(f"matrix has {n_obs} teams, n_teams={n_teams}")
    hfa = HFA if hfa is None else hfa
    scale = SCALE if scale is None else scale
    if scale == 0:
        raise ValueError("scale is 0")
    mu = np.zeros(n_teams)
    P = np.eye(n_teams) * (prior_sd ** 2)
    if voice_tau is None:
        cons = consensus(matrix, weights)
        resid = matrix - cons
        tau = resid.std() if n_src > 1 else 3.0
        tau = float(tau) if tau > 0.1 else 3.0
        taus = np.full(n_src, tau)
    else:
        taus = np.broadcast_to(np.asarray(voice_tau, dtype=float), (n_src,))

    eye = np.eye(n_teams)
    for k in range(n_src):
        K = P @ np.linalg.inv(P + (taus[k] ** 2) * eye)
        mu = mu + K @ (matrix[k] - mu)
        P = (eye - K) @ P

    pdf = _norm.pdf
    cdf = _norm.cdf
    for h, a, won in zip(home_idx, away_idx, home_won):
        z = (mu[h] - mu[a] + hfa) / scale
        hx = float(cdf(z))
        H = np.zeros(n_teams)
        dens = float(pdf(z)) / scale
        H[h] = dens
        H[a] = -dens
        S = float(H @ P @ H + max(hx * (1.0 - hx), 1e-4))
        Kvec = (P @ H) / S
        y = 1.0 if won else 0.0
        mu = mu + Kvec * (y - hx)
        P = (eye - np.outer(Kvec, H)) @ P

    mu = mu - mu.mean()
    sd = np.sqrt(np.clip(np.diag(P), 1e-8, None))
    return mu, sd


def source_matrix(totals_path, power_path, kalshi_dist_path, home, away,
                  store=None, banked=None, cal_home=None, cal_away=None,
                  played_home=None, played_away=None, played_won=None):
    """(matrix, weights, names, sigma_full).

    Live callers pass remaining `home`/`away` and `banked` so totals invert
    against games still to play. `cal_home`/`cal_away` stay the full season
    for Kalshi SD calibration.

    Weights start at `prior_weights` (market_strength half the mixture when
    present) and, when completed games are passed, become the BMA posterior
    over voices.
    """
    ens = _ensemble(totals_path, power_path, kalshi_dist_path,
                    home, away, store=store, banked=banked,
                    cal_home=cal_home, cal_away=cal_away)
    sources, sigma_full = ens.sources, ens.sigma
    names = list(sources)
    matrix = to_common_scale(sources)
    w = prior_weights(names)
    if played_home is not None:
        w = bma_weights(matrix, w, played_home, played_away, played_won)
    return matrix, w, names, sigma_full


def season_sigma(remaining_per_team, base_sigma=4.5) -> np.ndarray:
    """Season noise shrinks with games left: fewer games, less room for a team
    to be 'different from its rating' this year."""
    per = np.asarray(remaining_per_team, dtype=float)
    return base_sigma * np.sqrt(per / 17.0)


def consensus(matrix, weights) -> np.ndarray:
    return np.asarray(weights, dtype=float) @ np.asarray(matrix, dtype=float)


def pool_pwin(totals: dict) -> dict:
    """P(win pool) per player with ties counting for everyone tied (>= rule)."""
    names = list(totals)
    stack = np.stack([np.asarray(totals[n], dtype=float) for n in names], axis=1)
    rowmax = stack.max(axis=1)
    return {n: float((stack[:, i] >= rowmax).mean()) for i, n in enumerate(names)}


def _player_totals(rosters: dict, team_wins: np.ndarray) -> dict:
    """{player: (N,) array} from a (N, 32) per-team wins matrix."""
    out = {}
    for p, codes in rosters.items():
        idx = [TEAM_INDEX[c] for c in codes]
        out[p] = team_wins[:, idx].sum(axis=1) if idx else np.zeros(team_wins.shape[0])
    return out


def _dist(col, lo, n_bins):
    """Histogram of totals over the integer grid starting at lo. Half-integer
    totals (a team with a tie) round up, so distinct totals stay distinct."""
    idx = np.floor(np.asarray(col, dtype=float) - lo + 0.5).astype(int)
    counts = np.bincount(np.clip(idx, 0, n_bins - 1), minlength=n_bins)
    return (counts / max(counts.sum(), 1)).round(5).tolist()


def _market_distributions(kalshi_dist_path, store=None):
    """(codes, pmf matrix) from the store's newest distribution row, or from the
    CSV when there is no store. None when neither has one."""
    if store is not None:
        rows = [r for r in store.latest_ratings().values() if r["kind"] == "distribution"]
        if not rows:
            return None
        doc = max(rows, key=lambda r: float(r["fetched_at"]))["doc"]
        from .data import _valid_pmf
        good = {c: p for c in sorted(doc) if (p := _valid_pmf(doc[c])) is not None}
        bad = sorted(set(doc) - set(good))
        if bad:
            # Per team, not per source: a ragged ladder drops that team from the
            # market comparison rather than passing a bad row into rng.choice,
            # where it would surface as a numpy error naming neither.
            print(f"  WARNING: kalshi: skipping malformed win distribution for "
                  f"{', '.join(bad)}", file=sys.stderr)
        if not good:
            return None
        codes = sorted(good)
        return codes, np.asarray([good[c] for c in codes], dtype=float)
    if not kalshi_dist_path or not os.path.exists(kalshi_dist_path):
        return None
    return load_distributions(kalshi_dist_path)


def market_pwin(rosters: dict, kalshi_dist_path, n_sims: int, rng, store=None):
    """Kalshi-implied P(win pool): draw each team's season total from its market
    PMF independently (as `winspool market` does) and apply the >= rule.
    None when there are no distributions or any roster team has no
    market distribution."""
    dists = _market_distributions(kalshi_dist_path, store)
    if dists is None:
        return None
    codes, mat = dists
    col = {c: i for i, c in enumerate(codes)}
    if any(t not in col for teams in rosters.values() for t in teams):
        return None
    draws = sample_independent(mat, n_sims, rng)              # (N, n_codes)
    totals = {}
    for p, teams in rosters.items():
        idx = [col[t] for t in teams]
        totals[p] = draws[:, idx].sum(axis=1) if idx else np.zeros(n_sims)
    return {p: round(v, 3) for p, v in pool_pwin(totals).items()}


def market_probs(odds_rows: list[dict]) -> dict:
    """(home, away) -> consensus market probability, from a week's snapshots.

    Takes the latest row per source as `store.latest_odds` returns them and
    collapses them per game. The model's own voice is excluded: it is the thing
    the market is replacing, not part of the consensus."""
    from .gameodds import GameOdds, market_prob
    by_game: dict[tuple, list] = {}
    for row in odds_rows:
        source = row["source"]
        if source == "model":
            continue
        for g in row.get("games") or []:
            key = (g["home"], g["away"])
            by_game.setdefault(key, []).append(GameOdds(
                source=source, home=g["home"], away=g["away"],
                fetched_at=float(row.get("fetched_at") or 0.0),
                spread=g.get("spread"), total=g.get("total"),
                ml_home=g.get("ml_home"), ml_away=g.get("ml_away"),
                yes_home=g.get("yes_home"), yes_away=g.get("yes_away")))
    out = {}
    for key, odds in by_game.items():
        p = market_prob(odds)
        if p is None:
            continue
        p = float(p)
        if not 0.0 <= p <= 1.0:   # a parse regression, not a probability
            continue
        out[key] = p
    return out


def market_lines(odds_rows: list[dict]) -> dict:
    """(home, away) -> {spread, ml_home, ml_away} from the posted book, else nflverse.

    Same source preference the Week tab uses for the line column.
    """
    from .gameodds import GameOdds
    by_game: dict[tuple, dict] = {}
    for row in sorted(odds_rows, key=lambda r: float(r.get("fetched_at") or 0.0)):
        source = row["source"]
        if source == "model":
            continue
        for g in row.get("games") or []:
            key = (g["home"], g["away"])
            by_game.setdefault(key, {})[source] = GameOdds(
                source=source, home=g["home"], away=g["away"],
                fetched_at=float(row.get("fetched_at") or 0.0),
                spread=g.get("spread"), total=g.get("total"),
                ml_home=g.get("ml_home"), ml_away=g.get("ml_away"),
                yes_home=g.get("yes_home"), yes_away=g.get("yes_away"))
    out = {}
    for key, srcs in by_game.items():
        line = srcs.get("book") or srcs.get("nflverse")
        if line is None:
            continue
        out[key] = {
            "spread": line.spread,
            "ml_home": line.ml_home,
            "ml_away": line.ml_away,
        }
    return out


def _project(rosters, banked, matrix, weights, sigma, rest, wh, wa, n_seasons, rng,
             p_override=None):
    """One season projection under one set of source weights.

    Returns (rows, team_totals, totals, future_rest, p_home, week_outcomes).
    This week's games are drawn explicitly (so a single game can be forced for
    leverage); the rest of the season goes through the mixture sim."""
    strength = consensus(matrix, weights)
    if len(rest):
        rh, ra = remaining_matchups(rest)
        future_rest = simulate_mixture(matrix, rh, ra, n_seasons, base_sigma=sigma,
                                       tie_base=TIE_BASE, weights=weights, rng=rng).astype(float)
    else:
        future_rest = np.zeros((n_seasons, N_TEAMS))
    p_home = win_prob(strength[wh], strength[wa]) if len(wh) else np.zeros(0)
    if p_override is not None and len(wh):
        p_home = np.where(np.isnan(p_override), p_home, p_override)
    week_outcomes = rng.random((n_seasons, len(wh))) < p_home[None, :]   # True = home wins
    team_totals = banked[None, :] + future_rest + _week_wins(week_outcomes, wh, wa, n_seasons)
    totals = _player_totals(rosters, team_totals)
    pwin = pool_pwin(totals)
    rows = []
    for p, col in totals.items():
        teams = [{"code": c, "banked": float(banked[TEAM_INDEX[c]]),
                  "exp_wins": round(float(team_totals[:, TEAM_INDEX[c]].mean()), 1)}
                 for c in rosters[p]]
        teams.sort(key=lambda t: t["exp_wins"], reverse=True)
        rows.append({
            "player": p, "teams": teams,
            "banked": float(sum(t["banked"] for t in teams)),
            "exp_wins": round(float(col.mean()), 1),
            "pwin": round(pwin[p], 3),
            "p10": int(round(float(np.percentile(col, 10)))),
            "p90": int(round(float(np.percentile(col, 90)))),
        })
    rows.sort(key=lambda r: (r["pwin"], r["exp_wins"]), reverse=True)
    return rows, team_totals, totals, future_rest, p_home, week_outcomes


def _week_wins(outcomes, wh, wa, n_seasons):
    w = np.zeros((n_seasons, N_TEAMS))
    for g in range(outcomes.shape[1]):
        w[:, wh[g]] += outcomes[:, g]
        w[:, wa[g]] += ~outcomes[:, g]
    return w


def _voice_snapshot(matrix, names, sigma, ens) -> dict:
    """Per-voice strengths and Kalshi-calibration flags the Model tab reads
    back. Written once at compute_live so GET /api/league/model does not
    re-fetch the schedule or re-run the ensemble."""
    return {
        "voice_strength": {
            n: [round(float(matrix[j][i]), 3) for i in range(N_TEAMS)]
            for j, n in enumerate(names)
        },
        "sigma": [round(float(x), 3) for x in np.asarray(sigma, dtype=float)],
        "target_sd": [
            None if np.isnan(float(x)) else round(float(x), 3)
            for x in ens.target_sd
        ],
        "sigma_calibrated": bool(ens.sigma_calibrated),
    }


def compute_live(rosters: dict, sched_df: pd.DataFrame, *, totals_path=None, power_path=None,
                 kalshi_dist_path=None, ratings_fetched_at=None, market: dict | None = None,
                 lines: dict | None = None,
                 n_seasons=5000, seed=0, now=None, store=None) -> dict:
    """The live projection document. See the spec for the field list."""
    rng = np.random.default_rng(seed)
    played, remaining = split_schedule(sched_df)
    week = week_of(sched_df)
    banked = banked_wins(played)
    ph, pa, pw = played_outcomes(played)
    reg = _reg(sched_df)
    full_home = reg["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    full_away = reg["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    rem_home, rem_away = remaining_matchups(remaining)
    matrix, weights, _names, sigma_full = source_matrix(
        totals_path, power_path, kalshi_dist_path, rem_home, rem_away, store=store,
        banked=banked, cal_home=full_home, cal_away=full_away,
        played_home=ph, played_away=pa, played_won=pw)
    ens = _ensemble(totals_path, power_path, kalshi_dist_path, rem_home, rem_away,
                    store=store, banked=banked, cal_home=full_home, cal_away=full_away)
    snap = _voice_snapshot(matrix, _names, sigma_full, ens)
    post_mean, post_sd = posterior_strength(matrix, weights, ph, pa, pw)
    this_week = games_in_week(remaining, week)
    rest = remaining[remaining["week"] != week].reset_index(drop=True)
    sigma = season_sigma(remaining_games_per_team(rest), base_sigma=post_sd)
    wh, wa = remaining_matchups(this_week)

    # Current-week games are simulated from the market where we have one:
    # fresher information wins. Blend uses the posterior mean as the model.
    post_matrix = post_mean[None, :]
    post_w = np.array([1.0])
    override, game_source = week_home_p(post_matrix, post_w, wh, wa, market)

    blend, _team_totals, totals, future_rest, p_home, week_outcomes = _project(
        rosters, banked, post_matrix, post_w, sigma, rest, wh, wa, n_seasons, rng,
        p_override=override)

    # One extra view per source, that voice at 100%: the "score lens" on the
    # Standings card. Same method as the blend so the numbers are comparable.
    views = {"blend": blend}
    voice_sigma = season_sigma(remaining_games_per_team(rest), base_sigma=sigma_full)
    for i, name in enumerate(_names):
        one_hot = np.zeros(len(_names))
        one_hot[i] = 1.0
        views[name] = _project(rosters, banked, matrix, one_hot, voice_sigma, rest, wh, wa,
                               n_seasons, rng, p_override=override)[0]

    def totals_for(outcomes):
        return banked[None, :] + future_rest + _week_wins(outcomes, wh, wa, n_seasons)

    stack = np.stack(list(totals.values()), axis=1)
    lo, hi = int(np.floor(stack.min())), int(np.ceil(stack.max()))
    xs = list(range(lo, hi + 1))
    mkt = market_pwin(rosters, kalshi_dist_path, n_seasons, rng, store=store)
    rows = [{**r, "market_pwin": None if mkt is None else mkt.get(r["player"]),
             "dist": _dist(totals[r["player"]], lo, len(xs))} for r in blend]

    # Each game, forced both ways once: every player's swing comes off the same
    # pair of runs, so a game costs two projections however many owners it has.
    strength_blend = post_mean
    p_model_only = win_prob(strength_blend[wh], strength_blend[wa]) if len(wh) else np.zeros(0)
    p_by_voice = {
        name: (win_prob(matrix[j, wh], matrix[j, wa]) if len(wh) else np.zeros(0))
        for j, name in enumerate(_names)
    }
    prior = prior_weights(_names)
    p_prior_arr = (
        win_prob(consensus(matrix, prior)[wh], consensus(matrix, prior)[wa])
        if len(wh) else np.zeros(0)
    )
    games_out = []
    for g in range(len(wh)):
        forced = week_outcomes.copy()
        forced[:, g] = True
        win_pw = pool_pwin(_player_totals(rosters, totals_for(forced)))
        forced[:, g] = False
        los_pw = pool_pwin(_player_totals(rosters, totals_for(forced)))
        key = (TEAMS[wh[g]], TEAMS[wa[g]])
        line = (lines or {}).get(key) or {}
        mp = None if not market else market.get(key)
        games_out.append({
            "home": key[0], "away": key[1],
            "p_model": round(float(p_model_only[g]), 4),
            "p_used": round(float(p_home[g]), 4),
            "source": game_source[g],
            "p_voices": {n: round(float(p_by_voice[n][g]), 4) for n in _names},
            "p_prior": round(float(p_prior_arr[g]), 4),
            "p_market": None if mp is None else round(float(mp), 4),
            "spread": line.get("spread"),
            "ml_home": line.get("ml_home"),
            "ml_away": line.get("ml_away"),
            "swing": {p: round(win_pw[p] - los_pw[p], 4) for p in rosters},
        })

    # Leverage: for each of my games this week, |pwin if we win - pwin if we lose|.
    tw_rows = []
    for p, codes in rosters.items():
        mine = set(codes)
        games, lev, exp_week, locks = [], 0.0, 0.0, 0
        for g in range(len(wh)):
            hcode, acode = TEAMS[wh[g]], TEAMS[wa[g]]
            if hcode not in mine and acode not in mine:
                continue
            lev += abs(games_out[g]["swing"][p])
            if hcode in mine and acode in mine:
                # Both sides are mine: exactly one win, nothing to sweat.
                games.append({"team": hcode, "opp": acode, "home": True, "p": 1.0, "lock": True})
                exp_week += 1.0
                locks += 1
                continue
            for team, opp, home, p_win in ((hcode, acode, True, float(p_home[g])),
                                           (acode, hcode, False, float(1 - p_home[g]))):
                if team not in mine:
                    continue
                games.append({"team": team, "opp": opp, "home": home,
                              "p": round(p_win, 3), "lock": False})
                exp_week += p_win
        tw_rows.append({"player": p, "leverage": round(lev, 3), "games": games,
                        "exp_wins": round(exp_week, 1), "min_wins": locks,
                        "max_wins": len(games)})
    tw_rows.sort(key=lambda r: r["leverage"], reverse=True)

    computed_at = float(now if now is not None else time.time())
    brier = None
    if len(ph):
        pp = np.clip(win_prob(post_mean[ph], post_mean[pa]), 0.0, 1.0)
        brier = round(float(np.mean((pp - pw.astype(float)) ** 2)), 4)
    ll = bma_loglik(matrix, ph, pa, pw)
    return {"week": week, "computed_at": computed_at,
            "ratings_fetched_at": ratings_fetched_at,
            "rows": rows, "x": xs, "n_sims": int(n_seasons), "this_week": tw_rows,
            "games": games_out, "views": views,
            "weights": {n: round(float(w), 6) for n, w in zip(_names, weights)},
            "prior": {n: round(float(w), 6) for n, w in zip(_names, prior)},
            "loglik": {n: round(float(ll[j]), 4) for j, n in enumerate(_names)},
            "n_played": int(len(ph)),
            "hfa": HFA, "scale": SCALE,
            "posterior": {
                "mean": [round(float(v), 4) for v in post_mean],
                "sd": [round(float(v), 4) for v in post_sd],
            },
            "brier": brier,
            "ticks": [{"at": computed_at, "week": week,
                       "rows": [{"player": r["player"], "pwin": r["pwin"]} for r in rows]}],
            **snap,
            }


_LAST_SCHEDULE: pd.DataFrame | None = None
_LAST_SCHEDULE_AT: float | None = None

# Scores only move on winspool-scores.timer (every 15 min on game days), so a
# 2-minute window is already tighter than anything downstream needs it to be
# — while still collapsing five clients' 60s polling to at most one fetch
# per window instead of one per request.
_SCHEDULE_TTL_S = 120


def _load_schedule_cached() -> pd.DataFrame:
    """Live schedule from nfl_data_py, refetched at most once per
    _SCHEDULE_TTL_S; on a failed refetch, the last frame that worked.
    Raises if there has never been a good fetch in this process."""
    global _LAST_SCHEDULE, _LAST_SCHEDULE_AT
    from . import standings
    now = time.time()
    if (_LAST_SCHEDULE is not None and _LAST_SCHEDULE_AT is not None
            and now - _LAST_SCHEDULE_AT < _SCHEDULE_TTL_S):
        return _LAST_SCHEDULE
    try:
        df = standings._load_schedule()
        _LAST_SCHEDULE = df
        _LAST_SCHEDULE_AT = now
        return df
    except Exception:
        if _LAST_SCHEDULE is None:
            raise
        return _LAST_SCHEDULE


def ratings_fetched_at(store) -> str | None:
    """When the ensemble the doc was built from was last refreshed, as the
    ISO-8601 string the front end's staleness check parses."""
    stamp = ratings_stamp(store)
    if stamp is None:
        return None
    return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat()


def refresh_live(store, *, n_seasons=5000) -> dict:
    """Recompute the live doc from the league's final rosters and the current
    schedule + ratings cache; store it; snapshot the week if not yet snapshotted."""
    from . import league as _league
    rosters = _league.view(store.get())["rosters"]
    df = _load_schedule_cached()
    try:
        odds_rows = store.latest_odds(SEASON, week_of(df))
        market = market_probs(odds_rows)
        lines = market_lines(odds_rows)
    except Exception as e:        # noqa: BLE001 - logged, not raised
        # Non-fatal: model-only still projects. But silently reverting to the
        # model for the rest of the season is invisible in the UI, so say so.
        market = {}
        lines = {}
        print(f"  WARNING: market odds unavailable, using model only: {e}",
              file=sys.stderr)
    doc = compute_live(rosters, df, store=store,
                       ratings_fetched_at=ratings_fetched_at(store),
                       market=market, lines=lines, n_seasons=n_seasons)
    prev = store.get_live() or {}
    ticks = [t for t in (prev.get("ticks") or []) if t.get("week") == doc["week"]]
    ticks.extend(doc["ticks"])
    doc["ticks"] = ticks[-64:]
    store.put_live(doc)
    # The model's own voice, logged alongside the market's, so a completed week
    # can score the two against each other. Imported here: oddslog imports us.
    try:
        from .gameodds import GameOdds
        from .oddslog import snapshot
        model_odds = [GameOdds(source="model", home=g["home"], away=g["away"],
                               fetched_at=doc["computed_at"], p_home=g["p_model"])
                      for g in doc["games"]]
        store.add_odds(snapshot("model", SEASON, doc["week"], model_odds,
                                now=doc["computed_at"]))
    except Exception as e:        # noqa: BLE001 - logged, not raised
        # Non-fatal: the log is a record, not a dependency. But a silent failure
        # here is a permanently empty model log, so say so.
        print(f"  WARNING: model odds snapshot failed, skipping: {e}", file=sys.stderr)
    # The Simulations tab needs the ensemble itself, not this summary of it.
    # Build it here off the schedule we already have: on its own it would refetch
    # the season from nfl_data_py, which costs ~2s a request.
    from . import simmodel as _simmodel
    try:
        _simmodel.refresh_model(store, sched_df=df, market=market)
    except Exception as e:        # noqa: BLE001 - logged, not raised
        # Non-fatal: a stale model beats failing the live refresh. But serving
        # the Simulations tab a frozen model forever with nothing said is the
        # exact failure this branch exists to remove, so say so.
        print(f"  WARNING: simulation model refresh failed, serving the "
              f"previous one: {e}", file=sys.stderr)
    if not any(w["week"] == doc["week"] for w in store.list_weeks()):
        store.put_week(doc["week"], doc)
    return doc
