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

The current week's games are also projected from market odds rather than from
team strengths — see *Using the market*.

Out of scope, deliberately: skill-based source weighting (needs logged history
first) and an in-season rating of our own (wants the calibration work first).
Both are unblocked by the snapshot log this design builds. The season ensemble's
source weights are untouched by this design; the only model change is which
probability the current week's games are simulated from.

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

`GameOdds` is a frozen dataclass carrying **raw** source values, never derived
ones: `home`, `away`, `spread` (home-favoured negative, matching ESPN), `total`,
`ml_home` and `ml_away` (American odds as quoted), `yes_home` and `yes_away`
(Kalshi bid/ask mids as quoted), `source`, `fetched_at`. Team codes are
normalised through `teams.resolve` at the adapter boundary, so nothing
downstream ever sees `LAR`, `WSH` or `JAC`; that is the only transformation an
adapter is allowed to perform.

The registry is the reason The Odds API is not in this design. If ESPN's
undocumented shape breaks, adding a paid adapter is a new module and a key, not
a rewrite. We are not paying for that until ESPN actually fails.

### Converting to a probability

Conversion happens **on read**, never on write. The log holds what the source
said; probabilities are derived from it every time they are needed. This is what
makes the choices below reversible: a better method applied in a later season
can be run back over every week already recorded, instead of being stuck with
whatever we baked in at write time.

- **Spread.** `norm.cdf(spread / SCALE)` with the existing `game.SCALE`, so a
  spread-derived probability is on the same footing as the model's own.
- **Moneyline.** American odds to implied probability per side, then normalise
  the pair to sum to 1 — the proportional method.
- **Kalshi.** Bid/ask mid per side, normalised the same way, as
  `fetch/kalshi.py` already treats the season ladder.

Proportional de-vigging is known to under-adjust longshots, so the alternatives
are worth naming. Measured across all fifteen Week 1 games, proportional,
additive and Shin differ by **at most 1.2 points and typically under 0.5** —
`CLE @ JAX` is the widest at 0.787 / 0.799 / 0.787 against a 4.2% vig. At this
margin the choice does not matter, and because the log stores raw odds it stops
being a decision we are committed to.

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
            "ml_home": -192, "ml_away": 160}]}
```

No `p_home`. Everything in a snapshot is a quoted number; a probability appears
only when something reads the log and converts. The one exception is the model's
own per-game probability, which has no rawer form — it is logged as a
probability under source `model`, so that the completed-week view can score the
model against the market from Week 1 without recomputing anything.

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

`winspool export` and `winspool import` both grow an `odds` array; the
runbook's promise that an export is a complete move has to keep holding.

Firestore gets the same methods for Protocol consistency, but **Cloud Run and
Firestore were retired on 2026-09-10** — the Pi is the permanent host and there
is no rollback target. That code is dead weight awaiting a separate cleanup,
not a supported path.

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

There is no Cloud Run equivalent. Cloud Run and Firestore were retired on
2026-09-10; the Pi timer is the only scheduler.

## Using the market

For the current week's games, the live projection simulates from the market
probability instead of the ratings-derived one. Everything from next week
onward is unchanged, and the season ensemble's weights are untouched.

The justification is the one already encoded in `vegas_share`, which fades
preseason win totals to nothing by week 9 on the grounds that stale information
should lose to fresh information. A closing line for a game kicking off on
Sunday is the freshest information available about that game; preferring it over
a number derived from preseason team strength finishes the thought rather than
starting a new one.

The disagreement is not academic. Across Week 1, book and Kalshi agree with each
other to within **0.9 points on average**, while both differ from the model by
**3.0 points on average and 7.8 at the widest** (`WAS @ PHI`: model 73.5%, book
65.7%, Kalshi 68.2%). Two independent markets lining up against the model is
the model being the outlier.

**Which probability.** The mean of the available market sources — book and
Kalshi — falling back in order to the book alone, the nflverse spread, and
finally the ratings-derived probability if every source is missing. Book and
Kalshi are close enough that averaging them is mostly a robustness measure
against one of them being stale or misparsed.

**Where it applies.** `live._project` samples this week's games from `p_home`
and simulates the remainder from team strengths. The change is confined to how
that one `p_home` vector is built for the current week; the rest-of-season path,
the per-team sigma and the Kalshi season calibration are all untouched. The
per-source lens views inherit the same current-week probabilities, since the
override is about which games are imminent, not about which season-level voice
is speaking.

**Both are always kept.** The ratings-derived probability is still computed and
still logged every hour alongside the market's. The completed-week view scores
them against each other from Week 1 onward, so the calibration project arrives
with a season of head-to-head evidence instead of starting from nothing.

The honest caveat: this is a change we are making on established evidence rather
than our own measurement, and measuring it is what the calibration project is
for. Adopting closing lines is about as well supported as anything in sports
forecasting, and the cost of waiting a season to confirm it locally is a season.

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
need, in their player colour, with the magnitude in points at the end. Bar
length is scaled against the largest absolute swing across the whole week, not
against the largest on its own row, so widths are comparable between games —
which is the point of ordering the board by swing at all. Players moved less than 0.2 points are omitted.
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
- **Market override.** That the current week's simulated probabilities equal the
  market consensus where sources exist, that the fallback chain degrades in
  order to book, spread and model, and that a week with no odds at all
  reproduces the pre-change projection exactly.
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

**Vig removal is proportional**, which under-adjusts longshots. Measured on
Week 1 the alternatives move a probability by under half a point, and because
the log stores raw odds the method can be changed retroactively over every week
recorded. This is a live decision, not a locked one.

**The market override is unmeasured locally.** We adopt closing lines for the
current week on general evidence, not on evidence from this pool. Both
probabilities are logged from Week 1 so the claim can be checked, and reversed,
once there is enough history to check it against.

**Sources are still equal voices** in the season ensemble. Nothing here measures
which of them is any good. That is the calibration project, and the log this
design ships is its input.
