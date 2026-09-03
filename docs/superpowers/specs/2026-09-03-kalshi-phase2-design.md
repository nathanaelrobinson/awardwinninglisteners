# Kalshi Phase 2 — Market-Calibrated Variance + Kalshi as Its Own Voice

**Date:** 2026-09-03
**Status:** Approved (brainstorm)
**Branch:** `kalshi-phase2`
**Builds on:** `2026-09-03-kalshi-market-source-design.md` (Phase 1, shipped)

## Problem

Phase 1 blended Kalshi's implied O/U line into `win_totals` and exposed the full
distribution in a standalone market view. Two deferred items remain:

1. The season sim's per-team variance is a **flat, arbitrary 4.5-pt** strength-noise
   draw — identical for every team, and below what the market implies. Kalshi gives
   the actual, team-specific uncertainty.
2. Kalshi's line is **diluted 50/50 into covers** inside `win_totals`, so it does not
   get its own vote in the mixture-of-models sim.

## Empirical grounding (measured 2026-09-03)

- Schedule randomness alone (17 games at fixed strength): win-SD ≈ **1.96** (range 1.76–2.03).
- Current production (schedule + flat 4.5-pt strength noise): win-SD ≈ **2.73**.
- Kalshi implied win-SD: mean **3.19**, range **2.64 (ARI) – 4.00 (PHI)**.

So today's cushion is flat and under-dispersed vs. the market. Phase 2 replaces it
with a per-team, market-calibrated cushion.

## Item 1 — Market-calibrated per-team variance (SD injection)

**Goal:** each team's *simulated* total-win SD reproduces its Kalshi implied SD,
instead of a flat 4.5-pt season noise.

**Mechanism — self-calibrating moment-match (no magic constants):**
The mapping from strength-space season-noise σ (points) to output win-SD is
near-linear locally and team-specific. Calibrate it from the real sim with two
reference runs, then solve per team:

1. Run the schedule sim at σ = 0 → per-team baseline win-variance `baseVar_t`.
2. Run it at σ = `SIGMA_REF` (reuse 4.5) → per-team `refVar_t`.
3. Per-team slope²: `s2_t = (refVar_t - baseVar_t) / SIGMA_REF**2`.
4. Solve for the σ that hits the Kalshi target variance `T_t = kalshiSD_t**2`:
   `sigma_t = SIGMA_REF * sqrt( max(T_t - baseVar_t, 0) / max(refVar_t - baseVar_t, eps) )`.
5. Clip `sigma_t` to `[0, SIGMA_MAX]` (SIGMA_MAX = 12.0 pts) for safety.

Teams with no Kalshi SD (absent from `kalshi_distributions.csv`) keep the flat
`SIGMA_REF` default. Function lives in `ratings.py`:
`calibrate_sigma(strength, home, away, target_sd, *, sigma_ref=4.5, sigma_max=12.0, n_seasons, rng, tie_base) -> np.ndarray[N_TEAMS]`.

**Sim plumbing:** `simulate_mixture`'s `base_sigma` already multiplies a
`(n_seasons, n_teams)` normal draw; a length-`N_TEAMS` array broadcasts with no
code change. The only change is documenting that `base_sigma` accepts a per-team
vector and passing one from `build_wins`.

**Deliberate interaction (documented, not a bug):** the mixture still samples
different source-worlds (different *means*), so teams the models disagree on land a
bit above their Kalshi SD — genuine model uncertainty layered on top of the market's
single number. Teams the models agree on land at the Kalshi SD.

## Item 2 — Kalshi as its own mixture voice

Pull Kalshi out of the `win_totals` blend and give it a distinct vote.

- **Registry:** remove `Source("kalshi", "totals", kalshi_totals)` from
  `default_sources()`, so `win_totals.csv` is covers-only (+ betmgm when alive).
  `winspool fetch` still writes `kalshi_distributions.csv` (unchanged).
- **`build_wins`:** gain a `kalshi_dist_path="data/cache/kalshi_distributions.csv"`
  param. When the file exists, load it once and use it for BOTH items:
  - derive per-team Kalshi line (`pmf_line`) → `sources["kalshi"] = backout_market(kalshi_line_totals, ...)`, a distinct voice alongside `vegas` (covers) and each power column.
  - derive per-team Kalshi SD (`pmf_sd`) → the `target_sd` for `calibrate_sigma` (Item 1).
  - teams missing from Kalshi: excluded from the `kalshi` voice (that source's entry uses the ensemble mean for missing teams, matching existing missing-data handling) and use flat `SIGMA_REF` variance.
- When the file is absent, `build_wins` behaves exactly as Phase 1 (backward compatible).

## Data flow after Phase 2

`winspool fetch` → `win_totals.csv` (covers), `power_ratings.csv` (5 sources),
`kalshi_distributions.csv` (PMFs). `build_wins` assembles sources
`{vegas(covers), kalshi(line), fpi, nfelo, clay, pff, epa}` for the mixture, and
computes a per-team season-noise vector moment-matched to Kalshi SD.

## Out of scope

- Changing the mixture's world-selection or the schedule/game model.
- Re-weighting sources unequally (all voices stay equal-weight).
- UI/CLI surface changes beyond what already exists (`analyze`/`positional`/`recommend`
  automatically reflect the new variance and voice via `build_wins`).

## Testing (TDD)

- `calibrate_sigma`: with a target SD equal to the σ=0 baseline, returns ~0 for all
  teams; with a higher target, returns positive σ that (re-simulated) reproduces the
  target within tolerance; clips at `SIGMA_MAX`; teams flagged as no-data get
  `sigma_ref`.
- `simulate_mixture` accepts a per-team `base_sigma` vector and a team given a large
  σ shows materially higher win-SD than one given σ=0 (behavior, not mock).
- `build_wins`: with a Kalshi dist file present, `sources` includes a distinct
  `kalshi` voice; the returned per-team win-SD tracks Kalshi's SD ordering
  (correlation check on a small fixture); with the file absent, output matches the
  Phase-1 path (no `kalshi` voice, flat sigma).
- Registry: `default_sources()` no longer includes a `kalshi` totals source.

## Files touched

- Edit: `src/winspool/ratings.py` (add `calibrate_sigma`), `src/winspool/recommend.py`
  (`build_wins`: load Kalshi dists, add voice, pass sigma vector),
  `src/winspool/sim.py` (docstring: `base_sigma` accepts per-team vector),
  `src/winspool/fetch/registry.py` (drop kalshi totals Source),
  `README.md` (note covers-only win_totals + Kalshi voice + market-calibrated variance).
- Tests: `tests/test_ratings.py`, `tests/test_sim.py`, `tests/test_recommend.py`,
  `tests/test_fetch_pipeline.py`.
