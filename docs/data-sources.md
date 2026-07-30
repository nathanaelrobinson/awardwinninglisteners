# Data sources

Concrete free sources to wire into the ingestion pipeline (Milestone E, Tasks 12–13).
Each becomes a `Source` in `src/winspool/fetch/registry.py`, configured via
`data/cache/sources.json`. Selectors/endpoints are brittle and MUST be confirmed with a
live smoke test (each source should return ~32 teams) before a pre-draft refresh.

## Win totals (kind: "totals")
Multiple books → the pipeline averages them per team into `win_totals.csv`.

- Oddspedia — https://oddspedia.com/insights/american-football/nfl-win-totals-odds
- Covers — https://www.covers.com/nfl/nfl-odds-win-totals
- BetMGM (blog) — https://sports.betmgm.com/en/blog/nfl/nfl-odds-predictions-season-win-totals-bm16/

## Power ratings / projections (kind: "power")
Each becomes one column in `power_ratings.csv`; the blend averages all columns.

- ESPN FPI — https://www.espn.com/nfl/fpi/_/view/projections/sort/projections.probwintitle/dir/desc
  (FPI is a points power rating; the projections view also carries projected wins / win-title prob.)
- The Analyst (Opta) — https://theanalyst.com/nfl-predictions
  (projected final records / power predictions)

## Schedule
- nflverse via `nfl_data_py` (already implemented in `scripts/fetch_data.py`).

## Notes
- Win-total pages usually list posted O/U per team → map team name via `teams.resolve`.
- FPI / projection pages may express strength as projected wins or as a points rating;
  normalize each into `{team_code: value}` in its registry fetcher. If a source gives
  projected wins rather than a points rating, it can still feed the blend as its own
  column (points and wins are monotonically related for the averaging heuristic), but a
  wins→points conversion in the fetcher is cleaner — decide per source during Task 13.
