"""The weekly view: chalk, the week-win distribution, and the game board.

Assembles the tab's payload from three things that already exist — the live
doc's per-game swings, the odds log, and the schedule frame. Nothing here
simulates anything; the season projection has already paid that cost.
"""
from .gameodds import GameOdds, market_prob, to_prob
from .live import split_schedule
from .teams import resolve


def poisson_binomial(ps) -> list[float]:
    """Exact distribution over the number of successes in independent trials.

    A linear recurrence over at most six games — exact, instant, and with no
    seed, which is why the week distribution is not simulated."""
    dist = [1.0]
    for p in ps:
        p = float(p)
        nxt = [0.0] * (len(dist) + 1)
        for i, d in enumerate(dist):
            nxt[i] += d * (1.0 - p)
            nxt[i + 1] += d * p
        dist = nxt
    return dist


def _kickoff(row) -> str | None:
    day = getattr(row, "gameday", None)
    clock = getattr(row, "gametime", None)
    if not day:
        return None
    return f"{day}T{clock}" if clock else str(day)


def _odds_by_game(odds_rows) -> dict:
    """(home, away) -> {source: GameOdds}, newest row per source winning."""
    out: dict[tuple, dict] = {}
    for row in sorted(odds_rows, key=lambda r: float(r.get("fetched_at") or 0.0)):
        source = row["source"]
        for g in row.get("games") or []:
            key = (g["home"], g["away"])
            out.setdefault(key, {})[source] = GameOdds(
                source=source, home=g["home"], away=g["away"],
                fetched_at=float(row.get("fetched_at") or 0.0),
                spread=g.get("spread"), total=g.get("total"),
                ml_home=g.get("ml_home"), ml_away=g.get("ml_away"),
                yes_home=g.get("yes_home"), yes_away=g.get("yes_away"),
                p_home=g.get("p_home"))
    return out


def _history_by_game(odds_rows) -> dict:
    """(home, away) -> [[fetched_at, p], ...], oldest first, one entry per
    cycle that priced the game.

    Every source in an hourly `refresh_odds` run shares one `fetched_at`, so
    grouping by it recovers the cycles; `market_prob` is then re-run over each
    cycle's raw quotes, never over a stored probability, so a later change to
    the consensus rule replays over history for free.
    """
    cycles: dict[float, dict[tuple, list]] = {}
    for row in odds_rows:
        fetched_at = float(row.get("fetched_at") or 0.0)
        source = row["source"]
        for g in row.get("games") or []:
            key = (g["home"], g["away"])
            cycles.setdefault(fetched_at, {}).setdefault(key, []).append(GameOdds(
                source=source, home=g["home"], away=g["away"], fetched_at=fetched_at,
                spread=g.get("spread"), total=g.get("total"),
                ml_home=g.get("ml_home"), ml_away=g.get("ml_away"),
                yes_home=g.get("yes_home"), yes_away=g.get("yes_away"),
                p_home=g.get("p_home")))

    out: dict[tuple, list] = {}
    for fetched_at in sorted(cycles):
        for key, odds in cycles[fetched_at].items():
            p = market_prob(odds)
            if p is not None:
                out.setdefault(key, []).append([fetched_at, round(p, 4)])
    return out


def build_week(live_doc: dict, rosters: dict, sched_df, week: int,
               odds_rows: list) -> dict:
    """Everything the Week tab renders, in one document."""
    played, remaining = split_schedule(sched_df)
    played = played[played["week"] == week]
    remaining = remaining[remaining["week"] == week]
    odds = _odds_by_game(odds_rows)
    history = _history_by_game(odds_rows)
    swings = {(g["home"], g["away"]): g for g in live_doc.get("games") or []}

    games = []
    for row in remaining.itertuples(index=False):
        home, away = resolve(row.home_team), resolve(row.away_team)
        live_game = swings.get((home, away), {})
        per_source = odds.get((home, away), {})
        book = per_source.get("book")
        kalshi = per_source.get("kalshi")
        baseline = per_source.get("nflverse")
        line = book or baseline
        games.append({
            "home": home, "away": away, "kickoff": _kickoff(row), "state": "pre",
            "spread": None if line is None else line.spread,
            "total": None if line is None else line.total,
            "p_model": live_game.get("p_model"),
            "p_used": live_game.get("p_used"),
            "p_book": None if book is None else to_prob(book),
            "p_kalshi": None if kalshi is None else to_prob(kalshi),
            "home_score": None, "away_score": None,
            "swing": live_game.get("swing") or {},
            "history": history.get((home, away), []),
        })

    for row in played.itertuples(index=False):
        home, away = resolve(row.home_team), resolve(row.away_team)
        per_source = odds.get((home, away), {})
        book = per_source.get("book")
        model = per_source.get("model")
        baseline = per_source.get("nflverse")
        line = book or baseline
        games.append({
            "home": home, "away": away, "kickoff": _kickoff(row), "state": "final",
            "spread": None if line is None else line.spread,
            "total": None if line is None else line.total,
            "p_model": None if model is None else to_prob(model),
            "p_used": None if book is None else to_prob(book),
            "p_book": None if book is None else to_prob(book),
            "p_kalshi": None,
            "home_score": int(row.home_score), "away_score": int(row.away_score),
            "swing": {},
            "history": history.get((home, away), []),
        })

    games.sort(key=lambda g: (g["state"] == "final",
                              -max([abs(v) for v in g["swing"].values()] or [0.0]),
                              g["kickoff"] or ""))

    final = len(remaining) == 0
    pwin = {r["player"]: r.get("pwin") for r in live_doc.get("rows") or []}
    players = []
    for name, codes in rosters.items():
        mine = set(codes)
        ps, locks, banked, actual = [], 0, 0, 0
        for g in games:
            h, a = g["home"] in mine, g["away"] in mine
            if not h and not a:
                continue
            if g["state"] == "final":
                won = (g["home_score"] > g["away_score"]) if h else (
                    g["away_score"] > g["home_score"])
                banked += 1 if (h and a) else int(won)
                actual += 1 if (h and a) else int(won)
                continue
            if h and a:
                locks += 1
                continue
            p = g["p_used"]
            if p is None:
                continue
            ps.append(p if h else 1.0 - p)
        players.append({
            "name": name, "teams": list(codes), "locks": locks, "banked": banked,
            "chalk": round(sum(ps) + locks + banked, 2),
            "dist": [round(d, 4) for d in poisson_binomial(ps)],
            "actual": (actual + locks) if final else None,
            # The board's swing tooltip states both branches as absolute pool
            # odds, so it needs the unconditional number to add the swing to.
            "pwin": pwin.get(name),
        })

    return {"week": int(week), "state": "final" if final else "live",
            "games": games, "players": players}
