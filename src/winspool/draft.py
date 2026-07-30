import numpy as np
from .teams import N_TEAMS, N_PLAYERS, N_PICKS

# Fixed "optimized" order: player picking at each of the 30 picks (1-indexed players).
PICK_ORDER = [1, 2, 3, 4, 5, 6, 5, 6, 4, 6, 3, 1, 4, 2, 5,
              2, 3, 5, 3, 1, 6, 2, 1, 4, 3, 2, 4, 5, 6, 1]
assert len(PICK_ORDER) == N_PICKS

class DraftState:
    def __init__(self, my_player, picks=None, n_teams=N_TEAMS):
        self.my_player = my_player
        self.n_teams = n_teams
        self.picks = list(picks) if picks else []  # list[(player, team_idx)]

    def drafted(self):
        return {t for _, t in self.picks}

    def board(self):
        drafted = self.drafted()
        return [i for i in range(self.n_teams) if i not in drafted]

    def rosters(self):
        r = {p: [] for p in range(1, N_PLAYERS + 1)}
        for p, t in self.picks:
            r[p].append(t)
        return r

    @property
    def done(self):
        return len(self.picks) >= N_PICKS

    @property
    def current_player(self):
        return None if self.done else PICK_ORDER[len(self.picks)]

    def apply_pick(self, team_idx):
        if self.done:
            raise RuntimeError("draft is complete")
        self.picks.append((self.current_player, team_idx))

    def copy(self):
        return DraftState(self.my_player, self.picks, self.n_teams)

    def picks_until_my_next(self):
        count = 0
        for i in range(len(self.picks), N_PICKS):
            if PICK_ORDER[i] == self.my_player:
                return count
            count += 1
        return count  # no more picks

def player_totals(rosters, wins):
    n = wins.shape[0]
    totals = np.zeros((n, N_PLAYERS))
    for p, teams in rosters.items():
        if teams:
            totals[:, p - 1] = wins[:, teams].sum(axis=1)
    return totals

def pwin(rosters, wins, player):
    totals = player_totals(rosters, wins)
    rowmax = totals.max(axis=1)
    return float(np.mean(totals[:, player - 1] >= rowmax))

def greedy_pick(state, wins, player):
    # Rank by P(win); break ties by marginal expected wins. Early in a draft
    # most rosters are empty, so many candidates tie on P(win) (everyone is a
    # co-leader under the >= rule) — the marginal-wins tiebreak keeps the choice
    # meaningful and order-independent instead of falling to iteration order.
    best_team, best_key = None, None
    rosters = state.rosters()
    for t in state.board():
        rosters[player].append(t)
        totals = player_totals(rosters, wins)
        col = totals[:, player - 1]
        score = float(np.mean(col >= totals.max(axis=1)))
        mean_wins = float(col.mean())
        rosters[player].pop()
        key = (score, mean_wins)
        if best_key is None or key > best_key:
            best_key, best_team = key, t
    return best_team
