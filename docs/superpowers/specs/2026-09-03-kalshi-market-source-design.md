# Kalshi Market-Implied Win Distributions — Design

**Date:** 2026-09-03
**Status:** Approved (brainstorm)
**Branch:** `implement-model-core`

## Problem

We want per-team season **over/under win totals** plus a **directional-confidence
signal** (how strongly the market leans over/under). Our existing book source
(BetMGM) is dead (persistent HTTP 520), and a single posted line throws away the
market's confidence. Kalshi's `KXNFLWINS` series exposes the *entire implied win
distribution* per team, which gives us the line, the confidence, and full shape.

## What Kalshi gives us

- Series `KXNFLWINS`: 32 team events (`KXNFLWINS-27<TEAM>`, e.g. `KXNFLWINS-27BUF`;
  `27` = end-of-2026 season, settling Jan 2027).
- Each event is a **17-rung ladder** of yes/no contracts. Market `floor_strike = k`
  is "team wins **≥ k**"; its price is the market-implied `P(W ≥ k)`.
- Prices readable from the **public** endpoint with **no auth**:
  `GET https://external-api.kalshi.com/trade-api/v2/events?series_ticker=KXNFLWINS&with_nested_markets=true&limit=200`.
  Price fields are strings in dollars: `yes_bid_dollars`, `yes_ask_dollars`,
  `last_price_dollars`.
- The `tradebot` repo's RSA-key auth is for **trading only**; we do not need it here.
  Noted as a fallback if we ever hit public rate limits.

## Deliverables

Three loosely-coupled units, each independently testable.

### 1. Fetch + PMF construction — `src/winspool/fetch/kalshi.py`

Pure ↔ network split, mirroring `scrapers.py`/`parsers.py`.

**Pure (unit-tested against a fixture):**
- `ladder_to_pmf(markets) -> np.ndarray` (length 18, indices 0..17):
  1. For each rung, price = mid of `yes_bid_dollars`/`yes_ask_dollars` when both
     present and > 0, else `last_price_dollars`; skip rungs with no usable price.
  2. Build `P(W ≥ k)` for k = 1..17 (k = 0 is 1.0 by definition).
  3. **Enforce monotonicity:** `P(≥k)` must be non-increasing in k; apply a
     cumulative-min (`np.minimum.accumulate`) to remove bid/ask crossing noise.
  4. PMF: `p(W=k) = P(≥k) − P(≥k+1)` for k = 0..16, `p(W=17) = P(≥17)`; clip
     negatives to 0; **normalize** so the PMF sums to 1 (removes vig/underround).
- `pmf_mean(pmf)`, `pmf_sd(pmf)`, `pmf_line(pmf)` (median = smallest k with
  CDF ≥ 0.5, interpolated to the 0.5 crossing for a continuous O/U line).
- `team_from_event_ticker(ticker) -> code` via `teams.resolve` on the suffix.

**Network (live smoke test only):**
- `fetch_kalshi_ladders() -> {code: markets_list}` — one public GET.
- `kalshi_distributions() -> {code: pmf}` — ladders → PMFs for all teams.
- `kalshi_totals() -> {code: implied_win_total}` — a `Source`-compatible fetch
  returning the per-team line (`pmf_line`) for the totals blend.

**Artifact:** `write_distributions(dists, cache_dir)` writes
`data/cache/kalshi_distributions.csv` (columns: `team, p0, p1, …, p17`).

### 2. Standalone market view — `src/winspool/market.py` + CLI `winspool market`

The pure market-insight layer (independent of the correlated sim).

- `load_distributions(path) -> (codes, pmf_matrix[N_TEAMS, 18])`.
- `summarize(pmf_matrix) -> per-team {line, mean, sd}` where `sd` is the
  directional-confidence signal (small sd = market is confident). Optionally, when
  a posted `win_totals.csv` line is passed, also `p_over_posted` = market prob of
  exceeding that line.
- `sample_independent(pmf_matrix, n_seasons, rng) -> wins[n_seasons, N_TEAMS]`:
  each team's season total drawn i.i.d. from its PMF (schedule-correlation-free —
  this is a *market view*, explicitly NOT the pick decision engine).
- CLI `winspool market` prints per-team line / mean / SD, sorted, with a
  confidence rank. Descriptive columns only (no editorializing in headers).

### 3. Decision-engine blend (pick recommender)

**No change to the correlated sim core in v1.** Kalshi's implied line is registered
as a **totals source alongside covers** in `fetch/registry.py`. The existing
`pipeline.refresh` already means-blends all `totals` sources into `win_totals.csv`,
which `recommend.build_wins` backs out into the `vegas` voice of the
mixture-of-models sim. So Kalshi blends with covers and votes alongside the power
ratings, with head-to-head and schedule correlation fully preserved.

The CLI `fetch` command additionally calls the Kalshi distribution writer (step 1)
so `kalshi_distributions.csv` is produced on every refresh.

## Deferred to Phase 2 (explicitly out of scope for v1)

- **Per-team SD injection (true moment-match):** thread Kalshi's implied per-team
  SD into the sim variance. Requires extending `simulate_mixture` from a scalar
  `base_sigma` to a per-team sigma vector, and mapping win-SD → strength-space
  sigma via `WINS_PER_POINT`. Clean but touches the sim core; ship v1 first.
- **Kalshi as its own separate mixture voice** (weighted independently of covers).

## Data / edge cases

- Illiquid rungs (no bid/ask/last) are skipped; monotone-fix + normalize make the
  PMF robust to gaps. If a team has too few priced rungs to form a valid PMF
  (e.g. < 3), log a warning and omit it (downstream defaults to posted mean).
- Team code mapping: `KXNFLWINS-27WAS` → `WAS` etc. via `teams.resolve`; verify
  all 32 resolve (LA/LAR, JAX/JAC handled by existing resolver).
- Kalshi fetch failing must not abort the run — it rides the resilient `refresh`
  loop (per-source try/except already added) for the totals Source; the
  distribution write is wrapped in its own try/except with a warning.

## Testing (TDD)

- Fixture `tests/fixtures/kalshi_kxnflwins.json` (BUF + ARI events, trimmed to the
  fields the parser uses) — already captured live.
- `tests/test_kalshi.py`: `ladder_to_pmf` produces a normalized, monotone-derived
  PMF; `pmf_mean`/`pmf_sd`/`pmf_line` match hand-computed values; monotonicity fix
  handles a deliberately non-monotone ladder; team-code extraction.
- `tests/test_market.py`: `summarize` and `sample_independent` shapes/means.
- Live smoke test (network-marked) hits the real endpoint for 32 events.

## Files touched

- New: `src/winspool/fetch/kalshi.py`, `src/winspool/market.py`,
  `tests/test_kalshi.py`, `tests/test_market.py`,
  `tests/fixtures/kalshi_kxnflwins.json` (done).
- Edit: `src/winspool/fetch/registry.py` (add `kalshi` totals Source),
  `src/winspool/cli.py` (add `market` subcommand; call distribution writer in
  `fetch`), `README.md` (document the source + `winspool market`).
