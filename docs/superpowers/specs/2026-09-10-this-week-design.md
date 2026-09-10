# This Week — game-level odds, an immutable snapshot log, and a weekly tab

Design, 2026-09-10. Mockup: `docs/mockups/this-week-v2.html` (real rosters, real
Week 1 lines, swings from the live season model).

## Why

The live projection reasons entirely in season-long team strengths. Every voice
in the ensemble — Vegas totals, FPI, nfelo, Clay, PFF, EPA, Kalshi — is a
season-level number backed out to a per-team strength, and per-game win
probabilities fall out of that. Nothing in the system has ever looked at a point
spread for an individual game, which is the single most accurate per-game
forecast available and is free.

Separately, `compute_live` already computes leverage — how much each remaining
game moves each player's odds of winning the pool — and throws almost all of it
away, keeping one summed scalar per player for ordering the `ThisWeek` strip.
The most interesting number in the system is computed and discarded.

This design adds a game-level odds layer, records what every voice said before
each kickoff, and spends both on a This Week tab.

## Scope

In scope:

1. A game-odds fetch layer with three sources.
2. An append-only snapshot log of what each source said, hourly.
3. A This Week tab: player strip, game board, week picker, completed-week view.

Out of scope, deliberately: skill-based source weighting (needs logged history
first) and an in-season rating of our own (wants the calibration work first).
Both are unblocked by the snapshot log this design builds. The `live` ensemble's
weights do not change here — game odds are shown alongside the model, not
blended into it.

## Sources

| Source | Where | Cadence | Gives |
| --- | --- | --- | --- |
| nflverse | `nfl_data_py.import_schedules`, already fetched | ~daily | `spread_line`, `total_line`, moneylines |
| Book | ESPN scoreboard, `site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard` | live | DraftKings spread, over/under, moneyline |
| Kalshi | `KXNFLGAME` series on the existing public endpoint | live | per-side market price |

All three verified live on 2026-09-10: ESPN returned 16 events with DraftKings
odds; Kalshi matched all 15 unplayed Week 1 games. No API key, no auth, on any
of them.

Each source becomes a module under `src/winspool/fetch/` behind one adapter
signature, registered in `fetch/registry.py` alongside the existing entries:

```python
def fetch(season: int, week: int) -> list[GameOdds]
```

`GameOdds` is a frozen dataclass: `home`, `away`, `spread` (home-favoured
negative, matching ESPN), `total`, `p_home`, `source`, `fetched_at`. Team codes
are normalised through `teams.resolve` at the adapter boundary, so nothing
downstream ever sees `LAR`, `WSH` or `JAC`.

The registry is the reason The Odds API is not in this design. If ESPN's
undocumented shape breaks, adding a paid adapter is a new module and a key, not
a rewrite. We are not paying for that until ESPN actually fails.

### Converting to a probability

- **Spread.** `norm.cdf(spread / SCALE)` with the existing `game.SCALE`, so a
  spread-derived probability is on the same footing as the model's own.
- **Moneyline.** American odds to implied probability per side, then normalise
  the pair to sum to 1. This removes the vig by the proportional method — crude,
  and it biases favourites slightly, but the alternatives need a shape parameter
  we have no data to fit yet. Revisit once the log has a season in it.
- **Kalshi.** Mid of yes-bid and yes-ask per side, then normalise the pair, the
  same treatment `fetch/kalshi.py` already gives the season ladder.

## The snapshot log

An append-only record of what every source said about every game, written
hourly. It exists because the sources are not archived anywhere: nobody
publishes what DraftKings hung in week 3 once week 4 is up, and the same is true
of Kalshi's book. A record not taken before kickoff is gone. This is why the log
ships in the first project rather than with the calibration work that consumes
it.

New `Store` methods, implemented across all three stores:

```python
def add_odds(self, snapshot: dict) -> str: ...
def odds_for_week(self, season: int, week: int) -> list[dict]: ...
def latest_odds(self, season: int, week: int) -> list[dict]: ...
```

A snapshot document is one source's full read of one week:

```json
{"season": 2026, "week": 1, "source": "book", "fetched_at": 1789...,
 "games": [{"home": "KC", "away": "DEN", "spread": -2.5, "total": 43.5,
            "p_home": 0.5721}]}
```

Whole-week rather than per-game documents: it keeps writes to three per hour
instead of ~48, makes "what did the book think at 9am Sunday" one read, and
gives a natural unit for retention.

**Immutability.** Rows are only ever appended. There is no update path and no
delete path outside retention. A correction is a new snapshot with a later
`fetched_at`, never an edit — the point of the log is what we believed at a
time, including when we were wrong.

**Retention.** Full hourly resolution for the current week. Once a week's last
game is final, thin it per source to the opening snapshot plus, for each game,
the last snapshot before that game's own kickoff. That closing read is what
calibration scores against and is never thinned away. Roughly 200KB a season on
SQLite.

**SQLite schema** (mirrors the existing `snapshots` table pattern):

```sql
CREATE TABLE odds (
  id TEXT PRIMARY KEY,          -- season:week:source:fetched_at
  season INTEGER NOT NULL,
  week INTEGER NOT NULL,
  source TEXT NOT NULL,
  fetched_at REAL NOT NULL,
  doc TEXT NOT NULL
);
CREATE INDEX odds_week ON odds (season, week, source, fetched_at);
```

Firestore gets `leagues/2026/odds/{id}` with the same fields, so the Cloud Run
rollback host stays functional. `winspool export` and `winspool import` both
grow an `odds` array; the runbook's promise that an export is a complete move
has to keep holding.

### Scheduling

One new oneshot service and timer in `deploy/pi/`, matching the existing scores
pair:

- `winspool-odds.service` — `POST /internal/refresh-odds` with
  `X-Refresh-Token`, the same shape as `winspool-scores.service`.
- `winspool-odds.timer` — `OnCalendar=*-*-* *:20:00`, hourly at :20 so it does
  not collide with the standings refresh on the quarter hours.

`/internal/refresh-odds` fetches all three sources for the current week, writes
one snapshot each, and returns a per-source count. A source that fails is logged
and skipped; the other two still write. One source being down must never cost us
the other two, which is most of the argument for three of them.

On Cloud Run the equivalent is a fifth Cloud Scheduler job created by
`scripts/cr-schedule.sh`. Cloud Run is a paused rollback host and this is a
cheap consistency, not a live path.

## API

`GET /api/week?season=&week=` returns everything the tab renders, so the front
end makes one call:

```json
{"season": 2026, "week": 1, "state": "live",
 "games": [{"home": "KC", "away": "DEN", "kickoff": "...", "state": "pre",
            "spread": -2.5, "total": 43.5,
            "p_model": 0.5496, "p_book": 0.5721, "p_kalshi": 0.565,
            "home_score": null, "away_score": null,
            "swing": {"Mitch Fischer": -0.0426, "...": 0.0339}}],
 "players": [{"name": "...", "chalk": 3.93, "locks": 0, "banked": 1,
              "dist": [0.009, 0.079, ...], "actual": null}]}
```

`state` is `live` for the current week and `final` once every game has a score,
which is what flips the front end into the completed-week view. `week` defaults
to the current week; a completed week is served from the log, never recomputed
— a retro view that recomputes with today's information is a lie about what we
knew.

**Swings.** Per game, per player, the change in that player's probability of
winning the pool between the two branches of that game, signed for a home win.
`compute_live` already runs exactly this loop and discards the per-game detail;
the change is to keep it, not to compute anything new. Cost is unchanged.

**Chalk and the distribution.** Chalk is expected wins for the week from the
consensus per-game probability, plus locks (both teams rostered, so exactly one
win) plus already-banked wins. The distribution over week totals is the exact
Poisson-binomial over that player's uncertain games — a linear recurrence over
at most six games, not a simulation. It is exact, instant, and needs no seed.

Both live in a new `src/winspool/week.py`. `live.py` is 365 lines and already
carries the season projection; the weekly view is a separate concern with a
separate cadence and belongs beside it, not inside it.

## The tab

A sixth tab, `Week`, sitting before `Standings` and visible to everyone. Two
cards. The existing `ThisWeek` strip comes off the Standings tab when this
lands — leaving a thinner version of the same thing one tab away is exactly the
kind of duplicate surface that makes a UI feel padded.

**Player strip** — the existing `ThisWeek` component, grown up. One row per
player: colour swatch and first name; their games as logo-vs-logo chips carrying
a win probability, or a score and a green/red tint once final; `CHALK` as an
italic condensed number; and the week-total distribution as small bars, one per
possible total, labelled with the total.

**Game board** — one row per game, ordered by the largest absolute swing on it,
so the games that matter to the pool sit on top regardless of kickoff time.
Columns: kickoff, matchup with an owner-colour dot per team and the favourite in
heavier type, line and over/under, home-win probability, and the swing column.

The probability cell is a single track: a grey band spanning the range across
the three sources with a navy tick at the consensus. When the three disagree by
more than eight points the band turns red. There is no numeric annotation of the
disagreement — the colour carries it, and a number there could not be justified
against the amount of text already on the row.

The swing column hangs off an axis captioned with the two teams' logos, away
left and home right. Each affected player gets a bar growing toward the team they
need, length proportional to the swing, in their player colour, with the
magnitude in points at the end. Players moved less than 0.2 points are omitted.
Hovering states it in words: *"Evan to win the pool — DEN wins 15.4%, KC wins
18.8%."*

The unit is percentage points of absolute probability of winning the pool. A
head-to-head game between two rostered teams moves two players at once and is
structurally the biggest row on any given board.

**Week picker** — a select in the card header, defaulting to the current week.
Past weeks switch both cards to the completed view: chalk becomes `2.2 → 1`,
what the spreads expected and what actually happened, with the actual total
outlined on the distribution; and the game board shows the recorded pre-kickoff
probability against the result, tinted green when the favourite held, red when
it did not, captioned `Upset` only when it did not.

Every string on the tab: the week picker, `Week N Schedule`, five column
headers, `CHALK`, `WEEK WINS`, `FINAL`, `Upset`, `o/u`. No legends, no
explanatory captions. Anything that needs explaining is a title attribute or is
cut.

## Testing

- **Parsers, from fixtures.** A saved ESPN scoreboard payload and a saved Kalshi
  markets payload, both captured from the live endpoints, asserted down to
  specific games. Team-code normalisation is asserted explicitly for `LAR`,
  `WSH` and `JAC`, which is where this breaks.
- **Odds conversion.** Spread to probability against known values; moneyline
  de-vigging sums to 1; a pick-'em is 0.5.
- **Poisson-binomial.** Against a brute-force enumeration over six games, and
  the degenerate cases — no games, all locks, a certainty.
- **Swings.** That every player's swing on a game they have no team in is
  approximately zero, that a head-to-head game moves its two owners in opposite
  directions, and that the two branches recombine to the unconditional
  probability at the game's own win probability.
- **Store round-trip.** `add_odds` then `odds_for_week` across all three store
  implementations, plus export/import carrying odds, plus that appending never
  mutates an existing row.
- **Live smoke tests**, marked and skippable, that the three endpoints still
  return what the parsers expect. These are the tests that will actually catch
  ESPN changing shape.

## Known limitations

**The model banks wins but learns nothing from them.** When Denver beats Kansas
City, the projection adds one to Denver's total and leaves both teams' strength
ratings untouched for the remaining sixteen games. A result carries information
about strength, and we discard it. Every swing number this tab shows is
therefore an understatement of true early-season leverage, and most so in weeks
1–4. This is the in-season rating project, and it is the next one.

**Vig removal is proportional**, which biases favourites. Correcting it needs a
fitted shape parameter and therefore needs the log.

**Sources are still equal voices** in the season ensemble. Nothing here measures
which of them is any good. That is the calibration project, and the log this
design ships is its input.
