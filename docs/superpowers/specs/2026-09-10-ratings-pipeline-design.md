# Ratings on a schedule, in the database

Design, 2026-09-10. Phase 1 of three. Phase 2 feeds this into the Monte Carlo;
phase 3 is calibration and an in-season rating of our own.

## Why

`data/cache/sources_meta.json` says every rating source was last fetched
**2026-09-03** — a week before kickoff, and never since. `make refresh-ratings`
exists but its own help text says "run weekly from a laptop", and it has not
been run.

This matters more than it sounds. Several of these sources already learn from
results: ESPN FPI publishes weekly from a live API, and EPA is computed from
nflverse play-by-play by our own code. (Auditing the rest turned up that several
"sources" cannot update at all — see *What gets fetched*.) The projection is not
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

**The rule, from the project owner: now that the season has started, anything
static is thrown out. Only sources that can be kept current predict outcomes.**

Applying that rule required auditing what each source actually is, and most of
them are not what their names suggest:

| Source | What it actually is | Live? |
| --- | --- | --- |
| ESPN FPI | `site.web.api.espn.com/apis/fitt/v3/…`, a live API | **yes**, weekly |
| Kalshi `KXNFLWINS` | a live prediction market | **yes**, continuously |
| covers | `covers.com/nfl/nfl-odds-win-totals`, a live odds page | **yes** — season-wins futures keep trading |
| PFF | `pff.com/news/bet-nfl-betting-2026-…`, a preseason news article | no — frozen forever |
| Clay | `g.espncdn.com/…/ffldraftkit/26/….pdf`, a preseason PDF | no |
| betmgm | a blog article, and already failing with HTTP 520 | no |
| nfelo | a live page, but needs a headless browser | dropped |
| EPA | `EPA_SEASONS = (2025, 2024)` — LAST season's play-by-play | no, as configured |

So the surviving ensemble is:

| Source | Cadence | Why | Mechanism |
| --- | --- | --- | --- |
| Kalshi `KXNFLWINS` | daily | live market, absorbs every result; also the sigma calibration target | plain HTTP, existing client |
| ESPN FPI | weekly, Tue | live API, publishes weekly | plain HTTP |
| covers win totals | daily | live futures market | plain HTTP |
| Adjusted EPA | weekly, Tue | opponent-adjusted efficiency, computed by us | `nfl_data_py.import_pbp_data` |
| Market strength | weekly, Tue | team strengths inverted from every closing spread to date | the odds log we already keep |

Tuesday morning is after Monday night football and matches when the rating
services publish.

**Removed from the ensemble entirely:** PFF, Clay and betmgm. All three are
preseason artifacts that cannot change, and under the owner's rule a source that
cannot be kept current does not get to predict. **nfelo** is also dropped — it is
the only source needing a headless browser, and playwright plus chromium on the
Pi is not worth one weekly rating. No browser dependency ships to the Pi at all.

This is a deletion, not a fade. The previous revision of this design proposed
generalising `vegas_share` to decay stale sources toward zero; the owner's rule
supersedes that. A source that is removed cannot drift back in, and there is no
decay curve to argue about. `vegas_share` itself stays exactly as it is for the
covers win totals, which are a live market but a season-long one.

### DVOA, and why we compute it rather than fetch it

DVOA is the obvious candidate for an opponent-adjusted voice, and it is not
available. `footballoutsiders.com` no longer resolves since the FTN acquisition.
FTN's DVOA page returns HTTP 200 but contains zero `<table>` elements, zero
percentage values and no `__NEXT_DATA__` — the numbers are client-rendered — and
the page carries `Subscribe`, `Log In`, `Upgrade` and `Premium`. It would need
the headless browser we just removed, and behind that it is paid. We do not build
scrapers against paywalls.

What DVOA contributes over raw EPA is opponent adjustment, and that is a
computation, not a data source. Computing it ourselves is strictly better than
scraping would have been: free, live, no browser, no subscription, immune to a
page redesign, and genuinely ours — which is the point of a rule that only
sources we can keep current get to predict.

### Making EPA live, opponent-adjusted, and shrunk

The three surviving external sources are one model (FPI) and two markets (Kalshi,
covers) — and the two markets are highly correlated, so it is closer to two
independent signals than three. That is thin.

EPA fixes it. It is the only independent, non-market signal we can compute
ourselves, it is free, and the code already exists — it is simply pointed at the
wrong season. `EPA_SEASONS = (2025, 2024)` returns the first season that yields
data, so it reports last year's efficiency and will do so forever.

Pointing it at 2026 makes it live, and reintroduces the problem that presumably
caused the original choice: as of week 1 the season holds **166 plays across one
game**, and net EPA/play over that is close to noise.

**It also becomes opponent-adjusted.** The current calculation is a plain mean of
offensive EPA minus defensive EPA allowed, which flatters a team that has faced
weak opponents — precisely the flaw DVOA exists to correct. Replace the group-by
means with a ridge regression of play-level EPA on offence-team and defence-team
indicators plus home field. The fitted coefficients are opponent-adjusted
offensive and defensive strengths; net offence minus defence, mean-centered and
scaled by `EPA_POINTS_SCALE`, produces the same shape the source returns today.

At roughly 40,000 plays against 64 indicator columns this is a trivial
least-squares solve — numpy, no new dependency, and fast enough that it is
dwarfed by the play-by-play download preceding it. The ridge penalty also handles
the early-season case where a team has faced one or two opponents and the system
is near-singular.

So it is shrunk toward the prior season by how much of this season exists:

```
w = plays_2026 / (plays_2026 + K)
epa = w * epa_2026 + (1 - w) * epa_2025
```

`K` is the half-weight point in plays — the volume at which this season and last
count equally. Set `K = 8000`, roughly a third of a season's plays for a team's
opponents-adjusted sample: week 1 is ~2% this season, by week 8 it is ~55%, by
season's end ~75%. That is a deliberate choice to move slowly, on the grounds
that an unstable voice is worse than a lagging one when four voices are all we
have. `K` is a module constant with this reasoning attached, and is exactly the
kind of parameter phase 3's calibration should be asked to justify or change.

Note this makes EPA a hybrid rather than a purely live source, and that is
intended: the prior-season term is not a stale *forecast* being kept past its
usefulness, it is regularisation on a small sample. The distinction matters —
what the owner's rule throws out is stale opinion, not statistical shrinkage.

## Market strength, inverted from the spreads we already keep

Per-game odds currently do one job: set the win probability for the current
week's games. Everything from next week onward runs on season-level strengths. So
the sharpest data in the system is spent on sixteen games and then discarded,
while more of it accumulates hourly in the odds log.

Every closing spread directly measures the difference between two teams:

```
spread ≈ s_home − s_away + HFA
```

One week gives 16 equations over 32 unknowns; four weeks gives 64 and the system
is well determined. A least-squares solve over every game played to date yields a
market-implied strength vector that updates weekly.

This is not a duplicate of the season futures markets. Kalshi and covers win
totals bake in remaining schedule and games already banked; a spread is a clean
read on how good a team is *right now*. It is also opponent-adjusted by
construction — it is nothing but a system of relative comparisons — reaching the
same property the adjusted-EPA work buys, but from market prices rather than
play-by-play.

**Recency.** Strength drifts across a season, so a week-1 spread should not count
as much as last week's. Games are weighted by exponential decay on age,
`w = 0.5 ** (weeks_ago / HALF_LIFE_WEEKS)` with `HALF_LIFE_WEEKS = 4`. Like the
EPA shrinkage constant this is a judgement call chosen to move deliberately
rather than fitted, and phase 3's calibration should own it.

**Source of truth** is the odds log's closing read per game — the last snapshot
before that game's own kickoff, which the retention pass already preserves
precisely because it must never be thinned away. Prefer the `book` source,
falling back to `nflverse`, then to the Kalshi per-game price converted to a
spread. Games with no usable read are dropped from the system, never imputed.

## Storage

Ratings move out of `data/cache/*.csv` and into SQLite, structured and
versioned. Three concerns get three shapes:

```sql
CREATE TABLE ratings (
  id         TEXT PRIMARY KEY,   -- source:fetched_at
  source     TEXT NOT NULL,      -- 'espn_fpi', 'kalshi', 'covers', 'epa_adj', 'market_strength'
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

**The ensemble drops from seven voices to four**, and two of the four are
correlated markets. That is a real reduction in diversity, taken deliberately:
three of the removed voices could not change, and a forecast that cannot change
is not evidence about a season in progress. Whether four live voices beat seven
mostly-frozen ones is exactly the question phase 3's calibration is built to
answer — and the stored history this phase produces is what will answer it.

**Two unvalidated constants.** `K = 8000` in the EPA shrinkage and
`HALF_LIFE_WEEKS = 4` in the market-strength decay were both chosen to move
deliberately rather than fitted to anything. If `K` is wrong, EPA is too jumpy in
September or too anchored in December; if the half-life is wrong, market strength
either chases noise or lags real change. Both are module constants carrying their
reasoning, and both are exactly what phase 3 exists to settle.

**Market strength is thin in September.** Through week 3 the spread system has
fewer equations than teams and leans on its ridge term. It is honest but
low-information early, and improves every week — the opposite of the sources it
replaces.

**EPA is memory-heavy.** `import_pbp_data` over a season is the largest thing the
Pi will do. 4GB free is enough today; if it becomes a problem the fix is to
compute it incrementally by week rather than reloading the season.

**Sources are still equal voices.** Nothing here measures which of them is any
good — that is phase 3, and this phase's stored history is its input.
