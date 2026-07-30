import argparse
import numpy as np
from .teams import TEAMS, TEAM_INDEX
from .draft import DraftState, PICK_ORDER
from .recommend import build_wins, naive_recommend, rollout_recommend
from .opponents import entropy, greedy_self
from .mock import positional_study

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
    rec.add_argument("--rollouts", type=int, default=0)
    rec.add_argument("--temp", type=float, default=8.0)

    ana = sub.add_parser("analyze")
    ana.add_argument("--schedule", default="data/cache/schedule_2026.csv")
    ana.add_argument("--totals", default="data/cache/win_totals.csv")
    ana.add_argument("--power", default=None)
    ana.add_argument("--n", type=int, default=20000)
    ana.add_argument("--seed", type=int, default=0)

    pos = sub.add_parser("positional")
    pos.add_argument("--schedule", default="data/cache/schedule_2026.csv")
    pos.add_argument("--totals", default="data/cache/win_totals.csv")
    pos.add_argument("--power", default=None)
    pos.add_argument("--n", type=int, default=20000)
    pos.add_argument("--seed", type=int, default=0)
    pos.add_argument("--k", type=int, default=200)
    pos.add_argument("--temp", type=float, default=8.0)

    fet = sub.add_parser("fetch")
    fet.add_argument("--config", default="data/cache/sources.json")
    fet.add_argument("--cache", default="data/cache")

    args = parser.parse_args(argv)

    if args.cmd == "fetch":
        import datetime
        import json
        import os

        from .fetch.pipeline import refresh
        from .fetch.registry import default_sources
        config = {}
        if os.path.exists(args.config):
            with open(args.config) as f:
                config = json.load(f)
        sources = default_sources(config)
        if not sources:
            print("No sources configured. See src/winspool/fetch/registry.py.")
            return 1
        print(f"fetching {len(sources)} sources (nfelo renders headless, ~slow)…")
        now = datetime.datetime.now().isoformat(timespec="seconds")
        meta = refresh(sources, args.cache, now=now)
        for m in meta:
            print(f"{m['name']:<12}{m['kind']:<8}{m['n_teams']} teams  @ {m['fetched_at']}")
        return 0

    if args.cmd == "analyze":
        from .analysis import team_attributes
        wins, _ = build_wins(args.schedule, args.totals, args.n, args.seed,
                              power_path=args.power)
        attrs = sorted(team_attributes(wins), key=lambda a: a["mean"], reverse=True)
        print(f"{'team':<5}{'mean':>7}{'sd':>7}{'ceil':>7}{'floor':>7}")
        for a in attrs:
            print(f"{TEAMS[a['team']]:<5}{a['mean']:>7.2f}{a['sd']:>7.2f}"
                  f"{a['ceiling']:>7.3f}{a['floor']:>7.3f}")
        return 0

    if args.cmd == "recommend":
        wins, strengths = build_wins(args.schedule, args.totals, args.n, args.seed)
        state = DraftState(my_player=args.slot)
        _apply_taken(state, args.taken)
        on_clock = state.current_player
        print(f"Slot {args.slot} | on the clock: player {on_clock} | "
              f"your next pick in {state.picks_until_my_next()} picks")
        if args.rollouts > 0:
            opp_policy = entropy(strengths, temperature=args.temp)
            self_policy = greedy_self(wins)
            recs = rollout_recommend(state, wins, self_policy, opp_policy,
                                      n_rollouts=args.rollouts,
                                      rng=np.random.default_rng(args.seed))
            print(f"{'team':<5}{'pwin':>8}{'survival':>10}")
            for r in recs[:15]:
                print(f"{TEAMS[r['team']]:<5}{r['pwin']:>8.3f}{r['survival']:>10.3f}")
        else:
            recs = naive_recommend(state, wins)
            print(f"{'team':<5}{'pwin':>8}{'dWins':>8}")
            for r in recs[:15]:
                print(f"{TEAMS[r['team']]:<5}{r['pwin']:>8.3f}{r['delta_wins']:>8.2f}")
        return 0

    if args.cmd == "positional":
        wins, strengths = build_wins(args.schedule, args.totals, args.n, args.seed,
                                      power_path=args.power)
        res = positional_study(wins, greedy_self(wins), entropy(strengths, args.temp),
                                k=args.k, rng=np.random.default_rng(args.seed))
        print(f"{'slot':<6}{'pwin':>8}")
        for slot, p in sorted(res.items(), key=lambda kv: kv[1], reverse=True):
            print(f"{slot:<6}{p:>8.3f}")
        return 0
    return 1
