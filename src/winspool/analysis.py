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
