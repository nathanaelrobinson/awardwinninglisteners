# Kalshi Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the season sim's per-team variance market-calibrated to Kalshi's implied SD, and give Kalshi its own vote in the mixture (pulled out of the covers blend).

**Architecture:** A self-calibrating `calibrate_sigma` (two reference sims → per-team strength-noise σ matching each team's Kalshi win-SD) feeds `simulate_mixture`'s already-broadcasting `base_sigma`. `build_wins` loads `kalshi_distributions.csv` once to (a) add a distinct `kalshi` source voice from the implied line and (b) supply the per-team SD targets. Kalshi is dropped from the `win_totals` totals blend. All changes are backward-compatible when the Kalshi file is absent.

**Tech Stack:** Python 3.11, numpy, pandas, pytest, run via `uv`.

## Global Constraints

- Run everything with `uv run` (e.g. `uv run pytest`). Never bare `python`/`pip`.
- TDD: failing test first, verify RED for the right reason, minimal GREEN, commit.
- Moment-match is self-calibrating — NO hardcoded wins-per-point / slope constants. Calibrate the σ→win-SD slope from two reference sims of the actual schedule.
- Missing-team convention mirrors `data.load_win_totals`: a team absent from a source's data takes the mean of that source's posted values.
- All source voices stay EQUAL weight (no re-weighting).
- Backward compatibility: when `kalshi_distributions.csv` is absent, `build_wins` must behave exactly as Phase 1 (no `kalshi` voice, flat scalar `base_sigma`).
- Branch is `kalshi-phase2` (never push to main without approval). Commit after each task.

---

### Task 1: `calibrate_sigma` — per-team σ matching a target win-SD

**Files:**
- Modify: `src/winspool/ratings.py` (append the function)
- Test: `tests/test_ratings.py`

**Interfaces:**
- Consumes: `winspool.sim.simulate` (imported inside the function to avoid an import cycle).
- Produces: `calibrate_sigma(strength, home_idx, away_idx, target_sd, *, sigma_ref=4.5, sigma_max=12.0, n_seasons=8000, tie_base=0.003, seed=0) -> np.ndarray` (length = `strength.size`). `target_sd` is a per-team array of target win-SDs; `NaN` entries fall back to `sigma_ref`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ratings.py  (add to the existing file)
import numpy as np
from winspool.ratings import calibrate_sigma
from winspool.sim import simulate


def _toy_schedule():
    # 4 teams, round-robin home/away (each pair twice), no HFA in the sim calls
    home, away = [], []
    for i in range(4):
        for j in range(4):
            if i != j:
                home.append(i); away.append(j)
    return np.array(home), np.array(away)


def test_calibrate_sigma_nan_target_falls_back_to_ref():
    home, away = _toy_schedule()
    strength = np.zeros(4)
    target = np.array([np.nan, np.nan, np.nan, np.nan])
    sig = calibrate_sigma(strength, home, away, target, sigma_ref=4.5, n_seasons=4000)
    assert np.allclose(sig, 4.5)


def test_calibrate_sigma_reproduces_a_higher_target_sd():
    # Use the REAL 17-game schedule (the toy 6-game one saturates win-SD below
    # any useful target). Let hfa default so the verification sim matches the
    # assumptions calibrate_sigma uses in its own internal reference sims.
    from winspool.data import load_schedule, schedule_matchups
    df = load_schedule("data/cache/schedule_2026.csv")
    home, away = schedule_matchups(df)
    n = 32
    strength = np.zeros(n)
    base = simulate(strength, np.zeros(n), home, away, 8000,
                    tie_base=0.0, rng=np.random.default_rng(0))
    base_sd = base.std(axis=0).mean()
    target_val = base_sd + 1.0           # ~2.96, well within the market's 2.6-4.0 range
    target = np.full(n, target_val)
    sig = calibrate_sigma(strength, home, away, target, sigma_ref=4.5,
                          n_seasons=8000, tie_base=0.0)
    assert (sig > 0).all()
    # re-simulate with the solved sigma; realized win-SD should land near target
    w = simulate(strength, sig, home, away, 20000, tie_base=0.0,
                 rng=np.random.default_rng(1))
    realized = w.std(axis=0).mean()
    assert abs(realized - target_val) < 0.4


def test_calibrate_sigma_clips_to_max_and_zeros_below_baseline():
    home, away = _toy_schedule()
    strength = np.zeros(4)
    # target below the schedule-only baseline -> sigma 0; absurd target -> clipped
    low = calibrate_sigma(strength, home, away, np.full(4, 0.1),
                          sigma_ref=4.5, sigma_max=12.0, n_seasons=4000, tie_base=0.0)
    high = calibrate_sigma(strength, home, away, np.full(4, 50.0),
                           sigma_ref=4.5, sigma_max=12.0, n_seasons=4000, tie_base=0.0)
    assert np.allclose(low, 0.0)
    assert np.allclose(high, 12.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ratings.py -k calibrate -v`
Expected: FAIL — `cannot import name 'calibrate_sigma'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/winspool/ratings.py
def calibrate_sigma(strength, home_idx, away_idx, target_sd, *,
                    sigma_ref=4.5, sigma_max=12.0, n_seasons=8000,
                    tie_base=0.003, seed=0):
    """Per-team strength-space season-noise sigma (points) whose simulated
    total-win SD matches each team's target win-SD.

    Self-calibrated from two reference sims of THIS schedule (no hardcoded
    wins-per-point): win-variance is ~quadratic in sigma, so a sim at sigma=0
    and one at sigma=sigma_ref fix the per-team slope exactly. Then solve for the
    sigma that hits target_sd**2. target_sd entries that are NaN (no market data)
    fall back to sigma_ref. Result is clipped to [0, sigma_max]."""
    from .sim import simulate
    strength = np.asarray(strength, dtype=float)
    target_sd = np.asarray(target_sd, dtype=float)
    n = strength.size
    base = simulate(strength, np.zeros(n), home_idx, away_idx, n_seasons,
                    tie_base=tie_base, rng=np.random.default_rng(seed))
    ref = simulate(strength, np.full(n, sigma_ref), home_idx, away_idx, n_seasons,
                   tie_base=tie_base, rng=np.random.default_rng(seed + 1))
    base_var = base.var(axis=0)
    ref_var = ref.var(axis=0)
    slope2 = np.maximum((ref_var - base_var) / (sigma_ref ** 2), 1e-9)
    excess = np.maximum(target_sd ** 2 - base_var, 0.0)
    sigma = np.sqrt(excess / slope2)
    sigma = np.clip(sigma, 0.0, sigma_max)
    sigma = np.where(np.isnan(target_sd), sigma_ref, sigma)
    return sigma
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ratings.py -k calibrate -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/winspool/ratings.py tests/test_ratings.py
git commit -m "feat(ratings): calibrate_sigma — per-team season noise matching a target win-SD"
```

---

### Task 2: `simulate_mixture` accepts a per-team `base_sigma` vector

**Files:**
- Modify: `src/winspool/sim.py:36-50` (`simulate_mixture`)
- Test: `tests/test_sim.py`

**Interfaces:**
- Produces: `simulate_mixture(..., base_sigma=...)` where `base_sigma` is a scalar OR a length-`n_teams` array; a wrong-length vector raises `ValueError` naming `n_teams`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sim.py  (add)
import pytest

def _one_world(n_teams=2):
    # single "world": equal strengths, a 2-team home/away pair
    import numpy as np
    sm = np.zeros((1, n_teams))
    home = np.array([0, 1]); away = np.array([1, 0])
    return sm, home, away


def test_mixture_rejects_wrong_length_sigma():
    import numpy as np
    sm, home, away = _one_world(2)
    with pytest.raises(ValueError, match="n_teams"):
        simulate_mixture(sm, home, away, 100,
                         base_sigma=np.array([1.0, 2.0, 3.0]),   # len 3 != 2 teams
                         hfa=0.0, rng=np.random.default_rng(0))


def test_mixture_per_team_sigma_widens_only_that_team():
    import numpy as np
    sm, home, away = _one_world(2)
    w = simulate_mixture(sm, home, away, 20000,
                         base_sigma=np.array([0.05, 8.0]),   # team1 far noisier
                         hfa=0.0, tie_base=0.0, rng=np.random.default_rng(3))
    assert w[:, 1].std() > w[:, 0].std() + 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sim.py -k "wrong_length or per_team" -v`
Expected: `test_mixture_rejects_wrong_length_sigma` FAILS — numpy raises a broadcast `ValueError` whose message does NOT contain "n_teams", so `match="n_teams"` fails. (`per_team` may already pass via broadcasting — that's fine; it locks in the contract.)

- [ ] **Step 3: Write minimal implementation**

Change the body of `simulate_mixture` (after `n_sources, n_teams = source_matrix.shape`):

```python
    picks = rng.integers(0, n_sources, size=n_seasons)          # world per season
    base_sigma = np.asarray(base_sigma, dtype=float)
    if base_sigma.ndim == 1 and base_sigma.size != n_teams:
        raise ValueError(
            f"base_sigma vector length {base_sigma.size} != n_teams {n_teams}")
    S = source_matrix[picks] + rng.standard_normal((n_seasons, n_teams)) * base_sigma
    return _play(S, home_idx, away_idx, hfa=hfa, scale=scale, tie_base=tie_base, rng=rng)
```

And update the docstring's `Normal(0, base_sigma)` sentence to note: "`base_sigma`
may be a scalar or a per-team vector (length n_teams) — the latter lets each team's
season noise be calibrated independently (see `ratings.calibrate_sigma`)."

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sim.py -v`
Expected: PASS (existing sim tests + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/winspool/sim.py tests/test_sim.py
git commit -m "feat(sim): simulate_mixture accepts a per-team base_sigma vector (validated)"
```

---

### Task 3: Drop Kalshi from the `win_totals` totals blend

**Files:**
- Modify: `src/winspool/fetch/registry.py` (remove the kalshi Source + its import)
- Test: `tests/test_fetch_pipeline.py` (invert the existing assertion)

**Interfaces:**
- Produces: `default_sources()` no longer contains a source named `kalshi`.

- [ ] **Step 1: Rewrite the existing test to assert the new behavior**

Replace `test_default_sources_includes_kalshi` in `tests/test_fetch_pipeline.py` with:

```python
def test_default_sources_excludes_kalshi_totals():
    # Phase 2: Kalshi is its own mixture voice in build_wins, NOT a win_totals
    # totals source, so it must not appear in the fetch totals blend.
    from winspool.fetch.registry import default_sources
    names = {s.name for s in default_sources()}
    assert "kalshi" not in names
    assert "covers" in names  # covers remains the live totals source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fetch_pipeline.py -k kalshi -v`
Expected: FAIL — `assert 'kalshi' not in {...}` (kalshi is still registered).

- [ ] **Step 3: Remove the Source**

In `src/winspool/fetch/registry.py`: delete the `from .kalshi import kalshi_totals`
import line and delete the `Source("kalshi", "totals", kalshi_totals),` line from the
`default_sources()` return list. Leave all other sources unchanged. (The
`kalshi_distributions` write in the `fetch` CLI command stays — it is separate from
the registry.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fetch_pipeline.py -v`
Expected: PASS (all pipeline tests).

- [ ] **Step 5: Commit**

```bash
git add src/winspool/fetch/registry.py tests/test_fetch_pipeline.py
git commit -m "feat(fetch): drop kalshi from win_totals blend (becomes its own voice)"
```

---

### Task 4: `build_wins` — Kalshi voice + market-calibrated per-team σ

**Files:**
- Modify: `src/winspool/recommend.py:7-40` (`build_wins`; add `_assemble_sources` helper + `import os`)
- Test: `tests/test_recommend.py`

**Interfaces:**
- Consumes: `calibrate_sigma` (Task 1), per-team-sigma `simulate_mixture` (Task 2), `market.load_distributions`, `fetch.kalshi.pmf_line`/`pmf_sd`, `ratings.backout_market`.
- Produces:
  - `_assemble_sources(totals_path, power_path, home, away, kalshi_dist_path) -> (sources: dict[str, np.ndarray], target_sd: np.ndarray[N_TEAMS])`. Includes a `"kalshi"` voice iff the dist file exists; `target_sd` has per-team Kalshi SD (NaN where absent).
  - `build_wins(..., kalshi_dist_path="data/cache/kalshi_distributions.csv")` unchanged return `(wins, strengths)`, now with the Kalshi voice + calibrated per-team σ when the file is present.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recommend.py  (add)
import os
import numpy as np
import pandas as pd
from winspool.recommend import _assemble_sources, build_wins
from winspool.teams import TEAM_INDEX, TEAMS, N_TEAMS
from winspool.data import load_schedule, schedule_matchups


def _kalshi_csv(tmp_path):
    # give every team a spiked PMF at a distinct win count so pmf_sd varies:
    # half the teams sharply peaked (low SD), half spread (high SD)
    cols = [f"p{k}" for k in range(18)]
    rows = []
    for i, code in enumerate(TEAMS):
        pmf = np.zeros(18)
        if i % 2 == 0:
            pmf[9] = 1.0                      # degenerate -> SD 0
        else:
            pmf[6] = pmf[12] = 0.5            # bimodal -> large SD
        rows.append({"team": code, **dict(zip(cols, pmf))})
    p = tmp_path / "kdist.csv"
    pd.DataFrame(rows, columns=["team", *cols]).to_csv(p, index=False)
    return str(p)


def test_assemble_sources_adds_kalshi_voice_when_file_present(tmp_path):
    df = load_schedule("data/cache/schedule_2026.csv")
    home, away = schedule_matchups(df)
    kp = _kalshi_csv(tmp_path)
    src_with, target = _assemble_sources("data/cache/win_totals.csv",
                                         "data/cache/power_ratings.csv", home, away, kp)
    assert "kalshi" in src_with
    assert np.isfinite(target).all()          # every team had a Kalshi SD
    src_without, target2 = _assemble_sources("data/cache/win_totals.csv",
                                             "data/cache/power_ratings.csv", home, away, None)
    assert "kalshi" not in src_without
    assert np.isnan(target2).all()


def test_build_wins_variance_tracks_kalshi_sd(tmp_path):
    from winspool.fetch.kalshi import pmf_sd
    from winspool.market import load_distributions
    kp = _kalshi_csv(tmp_path)
    wins, _ = build_wins("data/cache/schedule_2026.csv", "data/cache/win_totals.csv",
                         n_seasons=6000, seed=0, power_path="data/cache/power_ratings.csv",
                         kalshi_dist_path=kp)
    sim_sd = wins.std(axis=0)
    codes, mat = load_distributions(kp)
    k_sd = np.zeros(N_TEAMS)
    for code, row in zip(codes, mat):
        k_sd[TEAM_INDEX[code]] = pmf_sd(row)
    # teams the market says are high-variance (bimodal) should simulate wider than
    # the low-variance (spiked) teams
    hi = sim_sd[k_sd > 1.0].mean()
    lo = sim_sd[k_sd == 0.0].mean()
    assert hi > lo
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_recommend.py -k "assemble or tracks" -v`
Expected: FAIL — `cannot import name '_assemble_sources'`.

- [ ] **Step 3: Write minimal implementation**

Rewrite `build_wins` and add the helper in `src/winspool/recommend.py`. Add `import os`
at the top of the file. Replace the current `build_wins` body with:

```python
def _assemble_sources(totals_path, power_path, home, away, kalshi_dist_path):
    """Build the {name: strength} source dict for the mixture, plus a per-team
    Kalshi target-SD array (NaN where the market has no data). Adds a distinct
    'kalshi' voice (backed out of the implied line) when the dist file exists."""
    from .data import load_power_ratings
    from .ratings import backout_market
    from .game import HFA, SCALE
    from .teams import TEAM_INDEX, N_TEAMS
    totals = load_win_totals(totals_path)
    sources = {"vegas": backout_market(totals, home, away, hfa=HFA, scale=SCALE)}
    if power_path:
        pdf = load_power_ratings(power_path)
        for col in pdf.columns:
            arr = np.zeros(N_TEAMS)
            for code, val in pdf[col].items():
                arr[TEAM_INDEX[code]] = float(val)
            sources[col] = arr
    target_sd = np.full(N_TEAMS, np.nan)
    if kalshi_dist_path and os.path.exists(kalshi_dist_path):
        from .market import load_distributions
        from .fetch.kalshi import pmf_line, pmf_sd
        codes, mat = load_distributions(kalshi_dist_path)
        line = np.full(N_TEAMS, np.nan)
        for code, row in zip(codes, mat):
            if code in TEAM_INDEX:
                line[TEAM_INDEX[code]] = pmf_line(row)
                target_sd[TEAM_INDEX[code]] = pmf_sd(row)
        line[np.isnan(line)] = np.nanmean(line)          # mirror load_win_totals
        sources["kalshi"] = backout_market(line, home, away, hfa=HFA, scale=SCALE)
    return sources, target_sd


def build_wins(schedule_path, totals_path, n_seasons=20000, seed=0,
               power_path=None, tie_base=0.003, base_sigma=4.5, spread_k=2.0,
               kalshi_dist_path="data/cache/kalshi_distributions.csv"):
    """Ensemble every available source into the season sim WITHOUT anchoring on
    any one. Vegas (covers, backed out of the O/U), Kalshi (its own voice), and
    each power column vote equally. The mixture samples which world is real; the
    per-team season variance is calibrated to Kalshi's implied SD when available
    (see ratings.calibrate_sigma), else a flat base_sigma."""
    from .ratings import ensemble, to_common_scale, calibrate_sigma
    df = load_schedule(schedule_path)
    home, away = schedule_matchups(df)
    sources, target_sd = _assemble_sources(totals_path, power_path, home, away,
                                           kalshi_dist_path)
    strengths, _ = ensemble(sources, base_sigma=base_sigma, spread_k=spread_k)
    rng = np.random.default_rng(seed)
    if len(sources) > 1:
        sigma = base_sigma
        if np.any(~np.isnan(target_sd)):
            sigma = calibrate_sigma(strengths, home, away, target_sd,
                                    sigma_ref=base_sigma, tie_base=tie_base, seed=seed)
        wins = simulate_mixture(to_common_scale(sources), home, away, n_seasons,
                                base_sigma=sigma, tie_base=tie_base, rng=rng)
    else:
        _, sigma = ensemble(sources, base_sigma=base_sigma, spread_k=spread_k)
        wins = simulate(strengths, sigma, home, away, n_seasons, tie_base=tie_base, rng=rng)
    return wins, strengths
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_recommend.py -v`
Expected: PASS (existing recommend tests + 2 new).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all selected tests PASS (1 network deselected). Note: any pre-existing test
that calls `build_wins` with defaults now auto-loads the real `kalshi_distributions.csv`
if present — shapes are unchanged, so those tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/winspool/recommend.py tests/test_recommend.py
git commit -m "feat(recommend): Kalshi voice + per-team variance calibrated to market SD"
```

---

### Task 5: Verify end-to-end + README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Full suite green**

Run: `uv run pytest -q`
Expected: all selected tests PASS, 1 deselected (network). No new warnings from
`winspool.ratings`/`sim`/`recommend`.

- [ ] **Step 2: Sanity-check the live effect**

Run:
```bash
uv run python -c "
import numpy as np
from winspool.recommend import build_wins
from winspool.market import load_distributions
from winspool.fetch.kalshi import pmf_sd
from winspool.teams import TEAM_INDEX, N_TEAMS
w,_ = build_wins('data/cache/schedule_2026.csv','data/cache/win_totals.csv',n_seasons=8000)
sim_sd = w.std(0)
codes,mat = load_distributions('data/cache/kalshi_distributions.csv')
k = np.zeros(N_TEAMS)
for c,row in zip(codes,mat): k[TEAM_INDEX[c]] = pmf_sd(row)
print('corr(sim win-SD, Kalshi SD):', round(float(np.corrcoef(sim_sd,k)[0,1]),3))
print('sim win-SD mean:', round(float(sim_sd.mean()),2), '(was ~2.73 flat in Phase 1)')
"
```
Expected: a positive correlation between simulated win-SD and Kalshi SD (Phase 1 was
~0 by construction — flat sigma), and a mean nearer the market's ~3.19.

- [ ] **Step 3: Document Phase 2 in README**

Under the Data section, update the win_totals/kalshi bullets to reflect: `win_totals.csv`
is covers-only (Kalshi is now its own voice, not blended in), and add a short line that
the sim's per-team season variance is calibrated to Kalshi's implied SD. Keep wording
factual.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: Phase 2 — Kalshi voice + market-calibrated variance"
```

---

## Self-Review Notes

- **Spec coverage:** Item 1 (calibrate_sigma Task 1, sim plumbing Task 2, wired in Task 4) ✓; Item 2 (drop from blend Task 3, add voice Task 4) ✓; backward-compat (Task 4 `if os.path.exists`) ✓; README (Task 5) ✓.
- **Self-calibration constraint:** `calibrate_sigma` derives its slope from two sims, no hardcoded wins-per-point. ✓
- **Missing-team convention:** Kalshi line mean-fills like `load_win_totals`; target_sd NaN → `sigma_ref`. ✓
- **Type consistency:** `calibrate_sigma(strength, home, away, target_sd, *, sigma_ref, sigma_max, n_seasons, tie_base, seed)`, `_assemble_sources(...) -> (sources, target_sd)`, `build_wins(..., kalshi_dist_path=...)` — names/signatures match between producer (Task 1/4) and consumer (Task 4) tasks. `simulate_mixture(base_sigma=vector)` contract (Task 2) matches Task 4's call.
- **Existing-test impact:** Task 3 inverts the one Phase-1 registry test; Task 4 notes default-path auto-load keeps prior `build_wins` tests shape-valid.
