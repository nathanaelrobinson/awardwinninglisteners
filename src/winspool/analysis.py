import numpy as np

def team_attributes(wins, ceiling_at=12, floor_at=6):
    n_teams = wins.shape[1]
    out = []
    for t in range(n_teams):
        col = wins[:, t]
        out.append({
            "team": t,
            "mean": float(col.mean()),
            "sd": float(col.std()),
            "ceiling": float(np.mean(col >= ceiling_at)),
            "floor": float(np.mean(col <= floor_at)),
        })
    return out

def roster_ceiling(wins, roster_idx, q=0.90):
    """Upper-tail MEAN of a roster's COMBINED win total — the average outcome in
    its best (1-q) fraction of seasons, i.e. how high the roster realistically
    spikes. Unlike a team's standalone ceiling, this is roster-aware: teams that
    cannibalize each other (head-to-head games cap their combined total) get a
    thinner upper tail and score LOWER than independent teams of equal mean. It
    captures both level and upside, and — unlike a raw quantile of an integer
    win-total — is continuous, so it actually resolves near-ties. This is the
    right winner-take-all tiebreak among near-equal P(win) picks: you have to
    spike to win the pool, and a division rival's solo upside is illusory once
    you hold its rival."""
    roster_idx = list(roster_idx)
    if not roster_idx:
        return 0.0
    total = wins[:, roster_idx].sum(axis=1)
    tail = total[total >= np.quantile(total, q)]
    return float(tail.mean()) if tail.size else float(total.max())

def win_correlation(wins):
    return np.corrcoef(wins.T)

def strength_of_schedule(strengths, home_idx, away_idx):
    strengths = np.asarray(strengths, dtype=float)
    n_teams = strengths.size
    opp_sum = np.zeros(n_teams)
    opp_cnt = np.zeros(n_teams)
    for h, a in zip(home_idx, away_idx):
        opp_sum[h] += strengths[a]; opp_cnt[h] += 1
        opp_sum[a] += strengths[h]; opp_cnt[a] += 1
    with np.errstate(invalid="ignore"):
        return np.where(opp_cnt > 0, opp_sum / opp_cnt, 0.0)
