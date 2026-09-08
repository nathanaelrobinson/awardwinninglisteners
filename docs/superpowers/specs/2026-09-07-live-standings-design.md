# Live Standings: weekly win probabilities and week-to-week movement

**Status:** approved 2026-09-07 · **Date:** 2026-09-07 · **Depends on:** PR #11 (frozen pre-season projections)

## Goal

The Standings tab shows, every week, each player's probability of winning the pool
and how it moved since last week. It stays fun mid-season: who is playing this
week, which games matter most, who swung up or down.

Draft Review stays frozen as the pre-season baseline (PR #11). Standings is the
live view.

## What the user sees

Standings tab, top to bottom:

1. **Standings cards** (existing). Each card gains two numbers under the total:
   `Win 34%` and a delta chip `▲ 6` / `▼ 3` versus last week's snapshot. The
   biggest absolute mover gets the card's existing `me`-style emphasis border.
   Delta is hidden until two snapshots exist.
2. **This week strip** (new card, eyebrow `Week 3`). One row per player: that
   player's games as `LOGO vs LOGO` chips (no per-game percentage), then the
   **expected wins this week** (`2.8`) and the possible range (`2–4`). A game
   between two of the player's own teams is one chip marked `1`: exactly one win,
   nothing to sweat. Teams on bye are omitted. Rows are ordered by how much the
   week can swing that player's pool odds (see Leverage below). No explanatory text.
3. **Movement chart** (new card, eyebrow `Win probability by week`). One line per
   player in player colors, x = NFL week, y = P(win pool). Hidden until three
   snapshots exist. Axis labels: `Week`, `Win %`.
4. **Feed** (existing).

Strings added: `Win`, `Week N`, `Win probability by week`, `Week`, `Win %`. Each
labels a number the reader would otherwise have to guess at.

## Score lens (added 2026-09-08)

A dropdown in the Standings card header switches what the cards show:

- **Actual** (default): real wins, `Total`, and `Win %` from the blend.
- **Blend**: projected wins per team to one decimal, `Proj` total, `Win %`.
- **One source** (FPI, nfelo, Clay, PFF, EPA, Kalshi, Vegas): the same simulation
  with that voice at 100% weight, so every lens is comparable. Vegas is the
  Covers/BetMGM average; BetMGM has been failing since 2026-09-03.

The live doc carries `views: {blend, <source>...}` with the same row shape as
`rows` minus `dist` and `market_pwin`; weekly snapshots carry them too, so the
▲/▼ delta follows the chosen lens. The This-week strip and the movement chart
stay on the blend. Choice is remembered per browser. Commissioner win overrides
are only clickable under Actual.

## Model

### Inputs, refreshed weekly

| Input | Source | Already exists |
|---|---|---|
| Games played, scores, week numbers | `nfl_data_py.import_schedules([2026])` | yes, `standings._load_schedule` |
| Team strengths (current) | `winspool fetch` → `power_ratings.csv` (ESPN FPI, nfelo, Clay, PFF, EPA) | yes |
| Market win distributions | `winspool fetch` → `kalshi_distributions.csv` | yes |
| Pre-season win totals | `win_totals.csv` (Covers, BetMGM) | yes, **not refreshed in-season** |

Sportsbook season win-total pages go stale or disappear once the season starts.
`win_totals.csv` is frozen at its pre-season value and used only as one voice in
the strength ensemble, with its weight decaying by week (below). Kalshi
`KXNFLWINS` ladders trade all season and are the live market voice.

### Remaining-season simulation

`winspool.sim.simulate_mixture(source_matrix, home_idx, away_idx, n_seasons)`
already simulates an arbitrary list of matchups. The in-season run:

1. Split the schedule into `played` (both scores present, `game_type == "REG"`)
   and `remaining`.
2. `banked[t]` = wins from `played` (ties count 0.5, matching the sim's tie handling).
3. `source_matrix` is the **same ensemble Draft Review uses** (`recommend._assemble_sources`:
   Vegas, Kalshi, and every power column as equal voices, per-team season sigma
   calibrated to Kalshi's implied spread). Only Vegas changes in-season: its equal
   share is multiplied by `max(0, 1 - (week - 1) / 8)`, full at week 1 and gone by
   week 9, and the weights are renormalised. Before kickoff the live numbers
   therefore match Draft Review up to Monte Carlo noise (tested).
4. `season_noise` shrinks with games left: `base_sigma * sqrt(remaining_games / 17)`
   per team, so late-season projections tighten.
5. `future = simulate_mixture(source_matrix, remaining home/away, N_SEASONS)`.
6. `total[t] = banked[t] + future[:, t]`. Player totals, P(win pool), expected
   wins, and 10th–90th percentile follow the existing `league_projections` code
   path exactly (`_name_totals`, ties count for both).

Market check: from `kalshi_distributions.csv`, each player's market-implied
total is the convolution of their teams' PMFs (independence assumed, as
`winspool market` already does). P(win pool) under the market is computed from
`N_SEASONS` draws of those PMFs. Stored alongside the model number as
`market_pwin` for a possible later toggle. **Not shown in the UI**: Kalshi is
already one of the ensemble's voices, and two unexplained numbers on a card broke
the no-explanatory-text rule.

### Leverage (ordering the This Week strip)

For each player, run the remaining-season sim twice more per game they have this
week: with that game forced to a win, and forced to a loss. Leverage =
`|pwin_if_win - pwin_if_loss|`, summed over the player's games this week. Six
teams × two branches × one player is at most 12 extra sims per player on a
5,000-row matrix; well under a second total on the Pi. Rows sort by leverage
descending; the number itself is not shown.

## Data and storage

New store doc `cache/live_projection` (Firestore) / kv `live_projection` (SQLite):

```json
{"week": 3, "computed_at": 1758000000.0, "ratings_fetched_at": "2026-09-23T09:00",
 "rows": [{"player": "...", "teams": [{"code": "KC", "banked": 2, "exp_wins": 11.4}],
           "banked": 9, "exp_wins": 52.1, "pwin": 0.34, "market_pwin": 0.41,
           "p10": 46, "p90": 58, "dist": [...]}],
 "x": [...], "n_sims": 5000,
 "this_week": [{"player": "...", "leverage": 0.11,
                "games": [{"team": "KC", "opp": "LAC", "home": true, "p": 0.61}]}]}
```

New store collection `snapshots_weekly` keyed by week (`put_week(week, doc)`,
`list_weeks()`). A week's snapshot is written once, the first time a
`live_projection` is computed for that week with all of that week's games
final. Snapshots are keyed by the upcoming week, so `weeks/3` is the standing
entering week 3 (after week 2's games). The Standings delta chip compares the
two most recent snapshots, i.e. week-over-week movement, and can differ from
the live headline number mid-week by design. Re-computes within the same week
overwrite `live_projection` but never the snapshot. Export/import carries both.

`week` = the smallest schedule week with an unplayed regular-season game. Before
kickoff of week 1 it is 1, and the live projection equals the pre-season one
apart from ratings drift.

## API

| Route | Auth | Returns |
|---|---|---|
| `GET /api/league/live` | `viewer` (public once done) | the `live_projection` doc |
| `GET /api/league/weeks` | `viewer` | `[{week, rows:[{player, pwin, exp_wins}]}]` from `snapshots_weekly`, oldest first |
| `POST /internal/refresh-live` | `X-Refresh-Token` (same as refresh-standings) | recompute and store; write the weekly snapshot if due |

`refresh-live` runs after `refresh-standings` inside the existing
`winspool-scores.service` (one extra `curl`). No new timer. It reads whatever is
in `data/cache`, so ratings freshness is decoupled from the projection job.

## Ratings refresh job

`winspool fetch` needs headless Chromium for nfelo, which is slow and fragile on
the Pi. Decision: the commissioner runs `winspool fetch` by hand from a laptop
(Tuesday mornings), commits the refreshed `data/cache/*.csv` to `main`, and the
Pi's existing deploy pull picks them up. `make refresh-ratings` wraps fetch,
commit, and push so it is one command.

If a week is missed, the Pi keeps simulating on last week's ratings.
`live_projection` records `ratings_fetched_at`; the Standings card footer reuses
its existing `stale` chip when ratings are more than 8 days old, so the miss is
visible rather than silent. A GitHub Actions cron can replace the manual step
later without touching anything else.

`sim_matrix.npz` is content-keyed on the CSVs and rebuilds itself when they
change. Draft Review no longer depends on it after PR #11.

## Front end

- `league.ts`: `LiveProjection`, `WeekRow` types; `getLive()`, `getWeeks()`.
- `Standings.tsx`: fetch `getLive()` alongside `getStandings()`; render `Win %`
  and delta from `getWeeks()`; add `ThisWeek` and `MovementChart` components.
- `MovementChart` reuses the SVG approach of `ProjChart` in `Review.tsx`
  (player colors from `colors.ts`, no chart library). Values labelled at the
  right end of each line.
- Anonymous viewers see everything; no new write paths.

## Error handling

- Missing or malformed ratings CSV: `refresh-live` returns 503 and leaves the
  previous doc in place, mirroring `refresh_standings`.
- No `live_projection` yet (fresh deploy): Standings renders without `Win %`,
  strip, or chart. Nothing else changes.
- Schedule fetch failure: reuse the last cached schedule; `week` cannot advance,
  which is the correct conservative behaviour.

## Testing

- Unit: `split_schedule`, `banked_wins` (ties), `week_of`, weighted source
  sampling in `simulate_mixture`, leverage sign and symmetry, market PMF
  convolution against a hand-computed two-team case.
- API: `live` 401 before done and 200 after; `refresh-live` token gate; weekly
  snapshot written once per week; `weeks` ordering; export/import round-trip.
- Fixture: a schedule CSV with weeks 1–2 played, week 3 partially played, to pin
  `week` and `this_week` behaviour.
- Front end: build and lint; manual check with the dev league seeded to `done`.

## Out of scope

- Playoff odds, division races: the pool is regular-season wins only.
- Historical back-testing of the model.
- Push notifications on movement.
- Refreshing sportsbook win totals in-season.

## Decisions from review

1. Vegas weight decays linearly to zero by week 9. Approved.
2. `mkt NN%` removed from the UI on 2026-09-07 after launch review; `market_pwin`
   stays in the API.
3. Ratings fetched by hand for now via `make refresh-ratings`; no cron.
