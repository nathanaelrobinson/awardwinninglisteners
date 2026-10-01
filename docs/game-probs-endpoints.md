# Strategy feed: game-probs endpoints

Read-only routes the tradebot strategy feed consumes. Implemented in
`src/winspool/gameprobs.py`, routed in `src/winspool/api_league.py`, tested in
`tests/test_gameprobs.py`.

## Auth

Every route takes the refresh routes' header: `X-Refresh-Token: $REFRESH_TOKEN`.

| Condition | Status |
|---|---|
| header missing or wrong | 401 |
| `REFRESH_TOKEN` not set on the server | 503 |
| `season` other than the served season (2026) | 404 |

Responses carry `cache-control: no-store`.

## Identifiers

- `game_id` = `<season>-<week>-<AWAY>@<HOME>`, e.g. `2026-3-TB@ARI`.
- Team codes are the app's standard (nflverse) abbreviations, the 32 codes in
  `src/winspool/teams.py`: ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU
  IND JAX KC LA LAC LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS.
  Watch for `LA` (Rams, not `LAR`), `LAC`, `LV`, `WAS`, `JAX`. Each probs
  response includes `teams: [{code, name}]`.
- Times are ISO-8601 UTC with a `Z` suffix, seconds precision.

## `GET /internal/game-probs?season=2026`

Every unplayed regular-season game (no final score yet, in-progress games
included), from the current store.

```json
{
  "as_of": "2026-09-22T12:00:00Z",
  "model_version": "abc1234@1789905600",
  "season": 2026,
  "ratings_fetched_at": "2026-09-20T12:00:00Z",
  "weights": {"espn_fpi": 0.052364, "epa_adj": 0.68851, "covers": 0.259126},
  "teams": [{"code": "ARI", "name": "Arizona Cardinals"}, "..."],
  "games": [
    {
      "game_id": "2026-3-TB@ARI",
      "week": 3,
      "kickoff_utc": "2026-09-24T17:00:00Z",
      "home": "ARI",
      "away": "TB",
      "p_home": 0.5929,
      "sources": {"espn_fpi": 0.7557, "epa_adj": 0.4514, "covers": 0.5589},
      "p_market": 0.7
    }
  ]
}
```

(Example from the test fixture; production has five voices: `espn_fpi`,
`kalshi`, `covers`, `epa_adj`, `market_strength`.)

| Field | Meaning |
|---|---|
| `as_of` | when the answer was computed (history: the requested `as_of`) |
| `model_version` | `<git short sha>@<newest ratings fetched_at, epoch s>`; `ratings@<stamp>` without a checkout. Override the sha with `WINSPOOL_GIT_SHA`. |
| `ratings_fetched_at` | newest rating row the model read |
| `weights` | BMA posterior weight per voice |
| `p_home` | model P(home wins): the 32-team Kalman posterior mean over the BMA-weighted voices, through the game probit (HFA 2.0, scale 13.5). Identical to the live doc's `p_model`. Never the market. |
| `sources` | P(home wins) under each voice alone (the live doc's `p_voices`) |
| `p_market` | odds-log consensus (book/Kalshi, else nflverse spread) for that game, or null |
| `kickoff_utc` | null when the schedule has no kickoff time |

Games are sorted by `(week, kickoff_utc, game_id)`. After week 18 `games` is `[]`.
503 when the store has no ratings.

## `GET /internal/game-probs/history?season=2026&as_of=<iso>`

Same shape, rebuilt as of `as_of` (`Z`, an offset, or no offset meaning UTC):

- ratings: only rows with `ok` and `fetched_at <= as_of` (newest per source);
- odds: only rows with `fetched_at <= as_of`;
- results: the schedule carries no result timestamps, so a game counts as
  played at `as_of` only if it has a final score **and** `kickoff + 4 h <= as_of`
  (a scored game with no kickoff time is treated as played). Banked wins, BMA
  weights and the posterior are all rebuilt from those results.

Deterministic for a given `as_of` and code version. With `as_of` = now it equals
the current endpoint. 404 when no rating row exists at or before `as_of`; 422
on an unparseable `as_of`.

Caveat: the schedule itself is today's schedule (a flexed or moved game is
reported at its current slot and kickoff).

## `GET /internal/games?season=2026`

Every regular-season game with its result, from the same nflverse schedule
frame standings counts wins from.

```json
{
  "season": 2026,
  "games": [
    {"game_id": "2026-1-ATL@TEN", "week": 1, "kickoff_utc": "2026-09-10T17:00:00Z",
     "home": "TEN", "away": "ATL", "home_score": 24, "away_score": 17, "played": true}
  ]
}
```

`played` is true when both scores are present; unplayed games have null scores.
Commissioner overrides of standings wins are not reflected (they adjust win
counts, not game scores).
