import argparse
from .teams import TEAMS, TEAM_INDEX
from .draft import DraftState, PICK_ORDER
from .recommend import build_wins, naive_recommend

def _apply_taken(state, taken):
    """taken: comma-separated team codes in pick order."""
    if not taken:
        return
    for code in taken.split(","):
        code = code.strip().upper()
        if code:
            state.apply_pick(TEAM_INDEX[code])

def main(argv=None):
    parser = argparse.ArgumentParser(prog="winspool")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("recommend")
    rec.add_argument("--slot", type=int, required=True)
    rec.add_argument("--taken", default="")
    rec.add_argument("--schedule", default="data/cache/schedule_2026.csv")
    rec.add_argument("--totals", default="data/cache/win_totals.csv")
    rec.add_argument("--n", type=int, default=20000)
    rec.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    if args.cmd == "recommend":
        wins, _ = build_wins(args.schedule, args.totals, args.n, args.seed)
        state = DraftState(my_player=args.slot)
        _apply_taken(state, args.taken)
        recs = naive_recommend(state, wins)
        on_clock = state.current_player
        print(f"Slot {args.slot} | on the clock: player {on_clock} | "
              f"your next pick in {state.picks_until_my_next()} picks")
        print(f"{'team':<5}{'pwin':>8}{'dWins':>8}")
        for r in recs[:15]:
            print(f"{TEAMS[r['team']]:<5}{r['pwin']:>8.3f}{r['delta_wins']:>8.2f}")
        return 0
    return 1
