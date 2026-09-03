import numpy as np
from .draft import greedy_pick

def chalk_power(strengths):
    strengths = np.asarray(strengths, dtype=float)
    def policy(state, player, rng):
        board = state.board()
        return max(board, key=lambda t: strengths[t])
    return policy

def entropy(strengths, temperature=8.0):
    strengths = np.asarray(strengths, dtype=float)
    def policy(state, player, rng):
        board = np.array(state.board())
        z = strengths[board] / temperature
        z -= z.max()
        p = np.exp(z); p /= p.sum()
        return int(rng.choice(board, p=p))
    return policy

def greedy_self(wins):
    def policy(state, player, rng):
        return greedy_pick(state, wins, player)
    return policy
