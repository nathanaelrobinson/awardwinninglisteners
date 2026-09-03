import numpy as np
from .draft import DraftState, pwin
from .teams import N_PLAYERS

def auto_draft(wins, policies, my_player, rng):
    st = DraftState(my_player=my_player)
    while not st.done and st.board():
        player = st.current_player
        st.apply_pick(policies[player](st, player, rng))
    return st

def positional_study(wins, self_policy, opp_policy, *, k=200, rng):
    results = {}
    for slot in range(1, N_PLAYERS + 1):
        pols = {p: opp_policy for p in range(1, N_PLAYERS + 1)}
        pols[slot] = self_policy
        total = 0.0
        for _ in range(k):
            final = auto_draft(wins, pols, my_player=slot, rng=rng)
            total += pwin(final.rosters(), wins, slot)
        results[slot] = total / k
    return results
