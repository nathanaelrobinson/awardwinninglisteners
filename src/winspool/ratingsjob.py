"""Fetch every live rating source and append what it said.

A source that fails leaves its last good row in place rather than dropping out
of the ensemble — the old CSV pipeline wrote one column per source that
succeeded, so a dead scraper silently changed what the model was. Per-source
rows remove that class of bug. Staleness is surfaced instead, and makes the
health check fail rather than the model quietly age.
"""
import math
import time

from .teams import N_TEAMS

DAY = 86400.0

# A power/totals/distribution doc covering fewer teams than this is recorded as
# a FAILURE, not a partial success. A partial parse is worse than no parse:
# `data.sources_from_store` fills the missing teams with 0.0 (league average)
# and `ratings.to_common_scale` then z-scores the source, so its standard
# deviation SHRINKS and the surviving teams' votes are INFLATED. The ensemble
# silently over-weights whatever ESPN happened to still name correctly. Two
# teams of slack absorbs a single rebranded club without red-lighting the box.
MIN_TEAM_COVERAGE = 30

WINS_PMF_LEN = 18                 # wins 0..17 inclusive

# A source past this age has not merely blipped — something is wrong and the
# ensemble is drifting on stale information. These make the endpoint 503.
MAX_AGE_S = {
    "espn_fpi": 10 * DAY,        # weekly
    "kalshi": 2 * DAY,           # daily
    "covers": 2 * DAY,           # daily
    "epa_adj": 10 * DAY,         # weekly
    "market_strength": 10 * DAY,  # weekly
}

KIND = {"espn_fpi": "power", "kalshi": "distribution", "covers": "totals",
        "epa_adj": "power", "market_strength": "power"}


def default_sources(store) -> dict:
    """{name: (kind, fn(season, week) -> {team: value})}. Kept as a function so
    a caller — or a test — can substitute one without touching the others."""
    from .fetch.scrapers import covers_totals, epa_ratings, espn_fpi
    from .fetch.kalshi import kalshi_distributions
    from .marketstrength import closing_spreads, strength_from_spreads

    def _market(season, week):
        # Include the current week: a posted-but-not-yet-closed line is still a
        # valid market estimate, and it's the freshest one we have. Restricting
        # to completed weeks would make this source fail every week 1, for a
        # cold start that including the current week removes entirely.
        games = closing_spreads(store, season, range(1, week + 1))
        return strength_from_spreads(games, current_week=week)

    return {
        "espn_fpi": ("power", lambda s, w: espn_fpi()),
        "covers": ("totals", lambda s, w: covers_totals()),
        "kalshi": ("distribution", lambda s, w: kalshi_distributions()),
        "epa_adj": ("power", lambda s, w: epa_ratings(w)),
        "market_strength": ("power", _market),
    }


def team_entries(doc: dict) -> dict:
    """The team-keyed part of a stored doc. Sources may attach `__meta__`
    (epa_adj records its play count and shrink weight); those keys are
    bookkeeping and must never be counted as coverage."""
    return {k: v for k, v in doc.items() if not str(k).startswith("__")}


def _coverage_error(doc: dict) -> str | None:
    n = len(team_entries(doc))
    if n < MIN_TEAM_COVERAGE:
        return (f"partial parse: {n}/{N_TEAMS} teams "
                f"(need {MIN_TEAM_COVERAGE}); a partial source inflates the "
                "teams it did cover, so it is refused outright")
    return None


def _pmf_error(doc: dict) -> str | None:
    """A malformed win-distribution row surfaces late and unhelpfully — deep
    inside `rng.choice` during a live refresh, in a numpy message naming
    neither the team nor the source. Catch it here, where the source's name is
    still known."""
    bad = []
    for code, pmf in team_entries(doc).items():
        try:
            vals = [float(x) for x in pmf]
        except (TypeError, ValueError):
            bad.append(code)
            continue
        if (len(vals) != WINS_PMF_LEN
                or not all(math.isfinite(v) for v in vals)
                or sum(vals) <= 0.0):
            bad.append(code)
    if bad:
        return f"malformed win distribution for {', '.join(sorted(bad))}"
    return None


class _Refused(Exception):
    """A source rejected by validation. Carries an already-worded reason, so it
    is reported verbatim rather than as `_Refused: ...`."""


def _record_failure(store, name, kind, stamp, reason, errors) -> None:
    """Note the failure in the returned report, and try to persist it.

    If the store itself is what is broken, the failure row cannot be written
    either. That is not a reason to retry, and not a reason to raise: the
    report is the authority the endpoint reads, and a source recorded there is
    a source the endpoint turns into a 503. Say in the message that the row is
    missing, so the Admin health box's silence is explained rather than
    mysterious, then carry on to the next source."""
    errors[name] = reason
    try:
        store.add_rating({"source": name, "kind": kind, "fetched_at": stamp,
                          "ok": False, "doc": {"error": reason}})
    except Exception as e:                        # noqa: BLE001 - reported, not raised
        errors[name] = (f"{reason} [and the failure row could not be stored: "
                        f"{type(e).__name__}: {e}]")[:400]


def refresh_ratings(store, *, season: int, week: int, sources=None,
                    now: float | None = None) -> dict:
    """Fetch, validate and store every source. Each source is wrapped whole —
    fetch, validation AND store write — so that one source's failure of any
    kind costs only that source. A store write that blows up used to escape the
    handler and abort the loop, which silently cost every source after it: no
    row at all, not even a failure row. Three voices exist so that one being
    down is survivable; that only holds if the boundary covers the write too."""
    stamp = now if now is not None else time.time()
    src = default_sources(store) if sources is None else sources
    written, errors = {}, {}
    for name, (kind, fn) in src.items():
        try:
            doc = fn(season, week)
            bad = "empty result" if not doc else _coverage_error(doc)
            if not bad and kind == "distribution":
                bad = _pmf_error(doc)
            if bad:
                raise _Refused(bad)
            store.add_rating({"source": name, "kind": kind, "fetched_at": stamp,
                              "ok": True, "doc": doc})
        except _Refused as e:
            _record_failure(store, name, kind, stamp, str(e), errors)
        except Exception as e:                    # noqa: BLE001 - recorded, not raised
            _record_failure(store, name, kind, stamp,
                            f"{type(e).__name__}: {e}"[:200], errors)
        else:
            written[name] = len(team_entries(doc))
    return {"season": int(season), "week": int(week),
            "written": written, "errors": errors}


def stale(store, now: float | None = None) -> dict:
    """{source: age_seconds} for every source whose last SUCCESS is past its
    limit. A source that has never succeeded counts as infinitely stale."""
    stamp = now if now is not None else time.time()
    latest = store.latest_ratings()
    out = {}
    for name, limit in MAX_AGE_S.items():
        row = latest.get(name)
        age = float("inf") if row is None else stamp - float(row["fetched_at"])
        if age > limit:
            out[name] = age
    return out
