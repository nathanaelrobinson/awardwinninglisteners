# Ratings on a schedule, in the database

Design, 2026-09-10. Phase 1 of three. Phase 2 feeds this into the Monte Carlo;
phase 3 is calibration and an in-season rating of our own.

## Why

`data/cache/sources_meta.json` says every rating source was last fetched
**2026-09-03** — a week before kickoff, and never since. `make refresh-ratings`
exists but its own help text says "run weekly from a laptop", and it has not
been run.

This matters more than it sounds. Several of these sources already learn from
results: ESPN FPI and PFF publish weekly, nfelo publishes weekly, and EPA is
computed from nflverse play-by-play by our own code. The projection is not
failing to learn because nobody wrote a learner — it is running on a snapshot
taken before a single game was played.

The worst instance is Kalshi. `kalshi_distributions.csv` is the `KXNFLWINS`
season win-total market, and it does double duty: a forecast voice in the
ensemble *and* the calibration target for per-team season variance. It is a live
market that absorbs every result, injury and trade, reachable over plain HTTP by
a client we already have — and the simulator is reading a week-one snapshot of
it.

The organising principle, from the project owner: **the Monte Carlo's estimate of
who wins the pool should always be our best available estimate.** Every decision
below serves that.

## Scope

In scope:

1. Fetch every source that still changes, on a schedule, on the Pi.
2. Store ratings as structured rows in SQLite, not as CSV files in a cache
   directory.
3. Make partial failure loud instead of silent.
4. A commissioner-only admin panel showing what ran, when, and whether it worked.

Out of scope, deliberately: changing how the ensemble weights sources (phase 3,
after calibration has something to say), and any rating of our own.

**Not needed:** Kalshi per-game (`KXNFLGAME`) is already snapshotted hourly by
`oddslog.refresh_odds` and feeds the Week tab's sparkline. Only the season market
`KXNFLWINS` is missing.

## What gets fetched, and how often

| Source | Cadence | Why | Mechanism |
| --- | --- | --- | --- |
| Kalshi `KXNFLWINS` | daily | live market, absorbs every result; also the sigma calibration target | plain HTTP, existing client |
| EPA | weekly, Tue | our own computation over nflverse play-by-play | `nfl_data_py.import_pbp_data`, memory-heavy |
| ESPN FPI | weekly, Tue | publishes weekly | plain HTTP |
| PFF | weekly, Tue | publishes weekly | plain HTTP |

Tuesday morning is after Monday night football and matches when the rating
services publish.

**Not fetched:** Clay (a preseason PDF that will never change again), covers and
betmgm (preseason win totals), and **nfelo** — dropped by the project owner
because it is the only source needing a headless browser, and putting playwright
and chromium on the Pi is not worth one weekly rating. No browser dependency
ships to the Pi at all.

### The consequence: half the ensemble is frozen

Dropping nfelo leaves four voices that update — FPI, PFF, EPA, Kalshi — and
three that never will: Clay, the covers/betmgm win totals, and nfelo's last
September value. They are weighted equally, so every week that passes the frozen
half drags the projection back toward preseason beliefs, and the fresher the
other half becomes the worse that distortion gets.

The codebase already contains the answer. `vegas_share` fades preseason win
totals from full weight at week 1 to nothing from week 9, on the explicit grounds
that stale information should lose to fresh information. That reasoning applies
identically to Clay and to a frozen nfelo — they are the same kind of thing.

**So the fade generalises from "vegas" to "any preseason-only source".** The
weight of a source that cannot update decays on the existing schedule; sources
that do update keep full weight. This is in scope for phase 1 precisely because
it is a direct consequence of not fetching nfelo, not a weight-tuning exercise —
tuning the weights of *live* sources remains phase 3, after calibration has
something to say.

Concretely: `live.vegas_share(week)` becomes `stale_share(week)` applied to the
set `{vegas, clay, nfelo}`, and `source_matrix_for_week` scales those weights
rather than only vegas's. The behaviour for `vegas` is unchanged, so week-1
output is identical and the existing tests still pin it.

## Storage

Ratings move out of `data/cache/*.csv` and into SQLite, structured and
versioned. Three concerns get three shapes:

```sql
CREATE TABLE ratings (
  id         TEXT PRIMARY KEY,   -- source:fetched_at
  source     TEXT NOT NULL,      -- 'espn_fpi', 'nfelo', 'pff', 'epa', 'kalshi', 'vegas'
  kind       TEXT NOT NULL,      -- 'power' | 'totals' | 'distribution'
  fetched_at REAL NOT NULL,
  ok         INTEGER NOT NULL,   -- 0 when the fetch failed; doc holds the error
  doc        TEXT NOT NULL       -- {team: value} for power/totals; {team: [pmf]} for distribution
);
CREATE INDEX ratings_source_time ON ratings (source, fetched_at);
```

Append-only, exactly like the odds log, and for the same reason: a record of what
each source said and when is what phase 3's calibration consumes. A failed fetch
still writes a row with `ok = 0` and its error — an absent row and a failed fetch
must be distinguishable.

**The current view** is "the newest `ok` row per source". That is what the model
reads. A source that has not fetched successfully in weeks keeps contributing its
last good value rather than silently vanishing from the ensemble — but its age is
recorded and surfaced (see *Loudness*).

`data/cache/` keeps only genuinely derived artifacts: `schedule_2026.csv` and
`sim_matrix.npz`. The three ratings CSVs and `sources_meta.json` are deleted from
the repo once the store is populated.

## The loader boundary, and the property that must hold

Thirty-nine call sites thread `totals_path`, `power_path` and `kalshi_dist_path`
through `live.py`, `recommend.py`, `simmodel.py`, `server.py` and `cli.py`. But
only one place actually loads them: `recommend._assemble_sources`, via
`data.load_win_totals` and `data.load_power_ratings`.

So the refactor is contained. `data.py` gains store-backed loaders returning the
same shapes the file loaders return today. The path arguments become optional
overrides — a file, when given, still wins, which keeps the CLI usable on a
laptop with no store and keeps every existing test working unchanged.

**The property that must hold, and the main risk of this whole phase:** these
inputs feed the number five people use to settle a season-long bet. The
store-backed path must produce *identical* team strengths to the file-backed path
given the same data. That gets a golden test — load today's CSVs, write them into
a store, assemble sources both ways, assert the strength vectors match exactly,
not approximately. If that test cannot be made to pass, the refactor is wrong and
stops.

## Loudness

Five silent failures were found and fixed on this codebase in a single session.
Every one was invisible rather than complicated. This design assumes a sixth is
waiting and tries to make it announce itself.

- **Partial failure never rewrites the ensemble's composition.** Today
  `pipeline.refresh` writes one CSV column per source that *succeeded*, and
  `ratings.power_strength` averages whatever columns it finds — so a failed
  scraper silently changes what the model is. Per-source rows remove that class
  of bug entirely: a failed fetch leaves the previous good row in place.
- **A stale source fails the health check.** Each source carries a maximum age
  (daily sources: 48h; weekly: 10 days). `POST /internal/refresh-ratings`
  returns 503 if any enabled source exceeds its limit, so the systemd unit goes
  red rather than reporting success while the model quietly ages.
- **The UI shows the age.** The live document already carries
  `ratings_fetched_at` and nothing renders it. The root cause of this entire
  phase is that nothing displayed a timestamp for a week.

## Admin panel

A commissioner-only tab, gated by the existing `require_commissioner` dependency
and the `is_commissioner` flag already on `Me`. It answers one question: is the
data pipeline healthy?

Per scheduled job — odds, standings, live, ratings — show the last run, whether
it succeeded, and its error if not. Per rating source, show its last successful
fetch, its age, and whether that age is within its limit.

This is an operator view, not a player view, so the tab's terse-copy rule is
relaxed: labels here should be unambiguous rather than minimal. It is exempt from
the game-board allow-list.

New endpoint `GET /api/admin/health`, commissioner-only, assembling that from the
`ratings` table and the store's existing timestamps.

## Testing

- The golden equivalence test above. It is the one that matters.
- Store round-trip for `ratings`: append-only, newest-ok-per-source, a failed
  fetch recorded distinctly from an absent one.
- Staleness: a source past its limit makes the refresh endpoint 503; one within
  it does not.
- Parsers are already fixture-tested in `tests/test_scrapers.py` and are not
  re-tested here.
- Live smoke tests for the fetchers stay marked `live` and out of CI.

**Budget: at most 8 new test functions across the phase.** This project is under
a standing test-reduction order; the suite is 353 and should not balloon.

## Known limitations

**Three voices are now permanently frozen** and fade rather than update. By week
9 the ensemble is effectively FPI, PFF, EPA and Kalshi. That is a smaller
ensemble than it looks on paper, and phase 3's calibration should be asked
whether four voices with real information beat seven where three are stale — it
is not obvious that adding a frozen prior helps at all.

**EPA is memory-heavy.** `import_pbp_data` over a season is the largest thing the
Pi will do. 4GB free is enough today; if it becomes a problem the fix is to
compute it incrementally by week rather than reloading the season.

**Sources are still equal voices.** Nothing here measures which of them is any
good — that is phase 3, and this phase's stored history is its input.
