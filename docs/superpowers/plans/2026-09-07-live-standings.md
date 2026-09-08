# Live Standings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Standings tab shows each player's live probability of winning the pool, how it moved since last week, and which of this week's games matter most.

**Architecture:** A new pure module `winspool/live.py` splits the nfl_data_py schedule into played and unplayed games, banks real wins, simulates only the remaining games with the existing mixture sim on weekly-refreshed power ratings (pre-season Vegas fading out by week 9), and emits one JSON doc. The doc is stored (`live`) and snapshotted once per NFL week (`weeks`). Two public GET routes serve it; a token-gated internal POST recomputes it from the existing scores timer. The Standings page reads both and renders win %, deltas, a this-week strip, and a movement chart.

**Tech Stack:** Python 3.11, FastAPI, numpy/scipy, pandas, nfl_data_py, pytest; React 19 + TypeScript + Vite, inline SVG (no chart lib). Stores: InMemory, SQLite, Firestore.

**Spec:** `docs/superpowers/specs/2026-09-07-live-standings-design.md`

## Global Constraints

- All new API reads use the `viewer` dependency (public once draft status is `done`, 401 before). No new write paths for players.
- P(win pool) uses the `>=` rule: ties count for every tied player (matches `league_projections`).
- Vegas source sampling weight is `max(0, 1 - week / 9)`; power sources share the remainder equally.
- Per-team season noise is `base_sigma * sqrt(remaining_games_for_team / 17)`.
- `week` = smallest regular-season week with an unplayed game; `19` when the season is complete.
- New UI strings are limited to: `Win`, `Week N`, `Win probability by week`, `Week`, `Win %`. No explanatory text.
- `mkt NN%` shown only when `|pwin - market_pwin| > 0.05`.
- Ratings older than 8 days show the existing stale chip.
- Run Python tests with `uv run pytest`, front end with `cd web && npm run build && npm run lint`.
- Commit on a feature branch cut from `origin/main`. Never push to `main`.

---

## File structure

| File | Responsibility |
|---|---|
| `src/winspool/sim.py` (modify) | `simulate_mixture` gains optional `weights` |
| `src/winspool/live.py` (create) | Pure in-season model: schedule split, week, sources, sim, leverage, market check, `compute_live`, `refresh_live` |
| `src/winspool/store.py` (modify) | `get_live/put_live`, `put_week/list_weeks` on all three stores |
| `src/winspool/api_league.py` (modify) | `GET /api/league/live`, `GET /api/league/weeks`, `POST /internal/refresh-live` |
| `src/winspool/cli.py` (modify) | export/import carry `live` and `weeks` |
| `deploy/pi/winspool-scores.service`, `Makefile`, `docs/pi-runbook.md` (modify) | second curl; `make refresh-ratings`; runbook note |
| `web/src/league.ts` (modify) | `LiveProjection`, `WeekPoint` types; `getLive`, `getWeeks` |
| `web/src/components/Standings.tsx` (modify) | win %, delta, mover, stale ratings; mounts new components |
| `web/src/components/ThisWeek.tsx` (create) | this-week strip |
| `web/src/components/MovementChart.tsx` (create) | win probability by week |
| `web/src/live.css` (modify) | styles for the above |
| `tests/test_live.py` (create), `tests/test_sim.py`, `tests/test_store_sqlite.py`, `tests/test_api_league.py`, `tests/test_export_import.py` (modify) | tests |

Branch: `git checkout -b feat/live-standings origin/main`

---

### Task 1: Weighted source sampling in `simulate_mixture`

**Files:**
- Modify: `src/winspool/sim.py:36-60`
- Test: `tests/test_sim.py`

**Interfaces:**
- Produces: `simulate_mixture(source_matrix, home_idx, away_idx, n_seasons, *, base_sigma=4.5, hfa, scale, tie_base=0.0, weights=None, rng)`. `weights` is a length-`n_sources` array summing to 1, or `None` for uniform.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_sim.py`:

```python
def test_simulate_mixture_weights_select_sources():
    import numpy as np
    from winspool.sim import simulate_mixture
    # Source 0: team 0 is +20 points; source 1: team 1 is +20 points.
    src = np.zeros((2, 32))
    src[0, 0] = 20.0
    src[1, 1] = 20.0
    home = np.array([0]); away = np.array([1])
    rng = np.random.default_rng(1)
    w = simulate_mixture(src, home, away, 4000, base_sigma=0.0, tie_base=0.0,
                         weights=np.array([1.0, 0.0]), rng=rng)
    # Only source 0 is ever sampled, so team 0 (home, +22 with HFA) wins ~95%.
    assert w[:, 0].mean() > 0.9
    rng = np.random.default_rng(1)
    w = simulate_mixture(src, home, away, 4000, base_sigma=0.0, tie_base=0.0,
                         weights=np.array([0.0, 1.0]), rng=rng)
    assert w[:, 0].mean() < 0.15


def test_simulate_mixture_weights_length_checked():
    import numpy as np
    import pytest
    from winspool.sim import simulate_mixture
    src = np.zeros((2, 32))
    with pytest.raises(ValueError):
        simulate_mixture(src, np.array([0]), np.array([1]), 10,
                         weights=np.array([1.0]), rng=np.random.default_rng(0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sim.py -q -k weights`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'weights'`

- [ ] **Step 3: Implement**

In `src/winspool/sim.py` change the signature and the `picks` line:

```python
def simulate_mixture(source_matrix, home_idx, away_idx, n_seasons, *,
                     base_sigma=4.5, hfa=HFA, scale=SCALE, tie_base=0.0,
                     weights=None, rng):
    """... (keep docstring) ...

    `weights` (optional, length n_sources, sums to 1) sets how often each
    source is the sampled world; None = uniform."""
    source_matrix = np.asarray(source_matrix, dtype=float)
    n_sources, n_teams = source_matrix.shape
    if weights is None:
        picks = rng.integers(0, n_sources, size=n_seasons)
    else:
        weights = np.asarray(weights, dtype=float)
        if weights.size != n_sources:
            raise ValueError(f"weights length {weights.size} != n_sources {n_sources}")
        picks = rng.choice(n_sources, size=n_seasons, p=weights / weights.sum())
```

Keep everything after `picks` unchanged.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_sim.py -q`
Expected: all PASS (existing tests unaffected because `weights=None` keeps the old path).

- [ ] **Step 5: Commit**

```bash
git add src/winspool/sim.py tests/test_sim.py
git commit -m "feat(sim): optional per-source sampling weights in simulate_mixture"
```

---

### Task 2: Schedule helpers in `live.py`

**Files:**
- Create: `src/winspool/live.py`
- Create: `tests/test_live.py`

**Interfaces:**
- Produces:
  - `REG_COLS = ["week", "game_type", "home_team", "away_team", "home_score", "away_score"]`
  - `split_schedule(df) -> (played: DataFrame, remaining: DataFrame)`, both REG only, original columns.
  - `banked_wins(played) -> np.ndarray (32,) float` (ties 0.5 each).
  - `week_of(df) -> int` smallest REG week with an unplayed game; `19` if none.
  - `remaining_matchups(remaining) -> (home_idx, away_idx)` int arrays.
  - `games_in_week(remaining, week) -> DataFrame` rows of `remaining` with `week == week`.
  - `remaining_games_per_team(remaining) -> np.ndarray (32,) int`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_live.py`:

```python
import numpy as np
import pandas as pd
import pytest

from winspool import live
from winspool.teams import TEAM_INDEX

COLS = ["week", "game_type", "home_team", "away_team", "home_score", "away_score"]


def sched(rows):
    return pd.DataFrame(rows, columns=COLS)


@pytest.fixture
def inseason():
    """Weeks 1-2 played, week 3 has one final and one unplayed, week 4 unplayed."""
    return sched([
        (1, "REG", "KC", "BUF", 27, 20),
        (1, "REG", "DAL", "PHI", 17, 17),      # tie
        (2, "REG", "BUF", "KC", 10, 13),
        (2, "REG", "PHI", "DAL", 30, 10),
        (3, "REG", "KC", "PHI", 21, 14),
        (3, "REG", "BUF", "DAL", None, None),
        (4, "REG", "DAL", "KC", None, None),
        (4, "REG", "PHI", "BUF", None, None),
        (19, "POST", "KC", "BUF", None, None),  # ignored
    ])


def test_split_schedule_reg_only(inseason):
    played, remaining = live.split_schedule(inseason)
    assert len(played) == 5 and len(remaining) == 3
    assert set(played["game_type"]) == {"REG"} and set(remaining["game_type"]) == {"REG"}


def test_banked_wins_counts_ties_as_half(inseason):
    played, _ = live.split_schedule(inseason)
    b = live.banked_wins(played)
    assert b.shape == (32,)
    assert b[TEAM_INDEX["KC"]] == 3
    assert b[TEAM_INDEX["BUF"]] == 0
    assert b[TEAM_INDEX["DAL"]] == 0.5 and b[TEAM_INDEX["PHI"]] == 1.5


def test_week_of_is_first_week_with_unplayed_game(inseason):
    assert live.week_of(inseason) == 3
    done = inseason.copy()
    done.loc[done["home_score"].isna(), ["home_score", "away_score"]] = 1
    assert live.week_of(done) == 19


def test_remaining_matchups_and_games_in_week(inseason):
    _, remaining = live.split_schedule(inseason)
    home, away = live.remaining_matchups(remaining)
    assert list(home) == [TEAM_INDEX["BUF"], TEAM_INDEX["DAL"], TEAM_INDEX["PHI"]]
    assert list(away) == [TEAM_INDEX["DAL"], TEAM_INDEX["KC"], TEAM_INDEX["BUF"]]
    wk = live.games_in_week(remaining, 3)
    assert len(wk) == 1 and wk.iloc[0]["home_team"] == "BUF"
    per = live.remaining_games_per_team(remaining)
    assert per[TEAM_INDEX["KC"]] == 1 and per[TEAM_INDEX["BUF"]] == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_live.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'winspool.live'`

- [ ] **Step 3: Implement**

Create `src/winspool/live.py`:

```python
"""In-season live projection: banked wins plus a remaining-season Monte Carlo.

Pure functions over the nfl_data_py schedule frame (columns week, game_type,
home_team, away_team, home_score, away_score) and the data/cache ratings files.
No store or network access except in refresh_live()."""
import numpy as np
import pandas as pd

from .teams import N_TEAMS, TEAM_INDEX, TEAMS

REG_COLS = ["week", "game_type", "home_team", "away_team", "home_score", "away_score"]
FINAL_WEEK = 18


def _reg(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["game_type"].str.upper() == "REG"].reset_index(drop=True)


def split_schedule(df: pd.DataFrame):
    """(played, remaining) regular-season frames. A game is played when both
    scores are present."""
    reg = _reg(df)
    final = reg["home_score"].notna() & reg["away_score"].notna()
    return reg[final].reset_index(drop=True), reg[~final].reset_index(drop=True)


def banked_wins(played: pd.DataFrame) -> np.ndarray:
    """Real wins so far per team index; a tie is 0.5 to each side."""
    b = np.zeros(N_TEAMS)
    for r in played.itertuples(index=False):
        h, a = TEAM_INDEX[r.home_team], TEAM_INDEX[r.away_team]
        if r.home_score > r.away_score:
            b[h] += 1
        elif r.away_score > r.home_score:
            b[a] += 1
        else:
            b[h] += 0.5
            b[a] += 0.5
    return b


def week_of(df: pd.DataFrame) -> int:
    """Smallest regular-season week with an unplayed game; FINAL_WEEK + 1 if none."""
    _, remaining = split_schedule(df)
    if remaining.empty:
        return FINAL_WEEK + 1
    return int(remaining["week"].min())


def remaining_matchups(remaining: pd.DataFrame):
    home = remaining["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    away = remaining["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    return home, away


def games_in_week(remaining: pd.DataFrame, week: int) -> pd.DataFrame:
    return remaining[remaining["week"] == week].reset_index(drop=True)


def remaining_games_per_team(remaining: pd.DataFrame) -> np.ndarray:
    home, away = remaining_matchups(remaining)
    per = np.zeros(N_TEAMS, dtype=int)
    np.add.at(per, home, 1)
    np.add.at(per, away, 1)
    return per
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_live.py -q`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/winspool/live.py tests/test_live.py
git commit -m "feat(live): schedule split, banked wins, current week helpers"
```

---

### Task 3: Strength sources and season noise for a given week

**Files:**
- Modify: `src/winspool/live.py`
- Modify: `tests/test_live.py`

**Interfaces:**
- Consumes: `winspool.data.load_win_totals(path) -> (32,) array`, `load_power_ratings(path) -> DataFrame indexed by team`, `winspool.ratings.backout_market(totals, home, away, *, hfa, scale)`, `winspool.ratings.to_common_scale({name: (32,)}) -> (n, 32)`.
- Produces:
  - `vegas_weight(week) -> float` = `max(0.0, 1 - week / 9)`.
  - `source_matrix_for_week(totals_path, power_path, full_home, full_away, week) -> (matrix (n,32), weights (n,), names list)`. Vegas first (if totals file exists), then each power column. `full_home/full_away` are the full-season matchups (Vegas totals are full-season numbers).
  - `season_sigma(remaining_per_team, base_sigma=4.5) -> (32,)`.
  - `consensus(matrix, weights) -> (32,)` = `weights @ matrix`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_live.py`:

```python
FIX = "tests/fixtures"


def test_vegas_weight_decays_to_zero_by_week_9():
    assert live.vegas_weight(1) == pytest.approx(8 / 9)
    assert live.vegas_weight(5) == pytest.approx(4 / 9)
    assert live.vegas_weight(9) == 0.0
    assert live.vegas_weight(14) == 0.0


def test_source_matrix_weights_and_order():
    from winspool.data import load_schedule, schedule_matchups
    home, away = schedule_matchups(load_schedule(f"{FIX}/schedule_2026.csv"))
    m, w, names = live.source_matrix_for_week(f"{FIX}/win_totals.csv",
                                              f"{FIX}/power_ratings.csv",
                                              home, away, week=3)
    assert names[0] == "vegas" and names[1:] == ["fpi", "sagarin", "massey"]
    assert m.shape == (4, 32)
    assert w.sum() == pytest.approx(1.0)
    assert w[0] == pytest.approx(live.vegas_weight(3))
    assert np.allclose(w[1:], (1 - w[0]) / 3)
    m9, w9, _ = live.source_matrix_for_week(f"{FIX}/win_totals.csv",
                                            f"{FIX}/power_ratings.csv",
                                            home, away, week=9)
    assert w9[0] == 0.0 and np.allclose(w9[1:], 1 / 3)


def test_source_matrix_without_totals_file_has_no_vegas(tmp_path):
    from winspool.data import load_schedule, schedule_matchups
    home, away = schedule_matchups(load_schedule(f"{FIX}/schedule_2026.csv"))
    m, w, names = live.source_matrix_for_week(str(tmp_path / "missing.csv"),
                                              f"{FIX}/power_ratings.csv",
                                              home, away, week=1)
    assert names == ["fpi", "sagarin", "massey"] and np.allclose(w, 1 / 3)


def test_season_sigma_shrinks_with_games_left():
    per = np.full(32, 17)
    per[0] = 0
    per[1] = 4
    s = live.season_sigma(per, base_sigma=4.5)
    assert s[2] == pytest.approx(4.5)
    assert s[0] == 0.0
    assert s[1] == pytest.approx(4.5 * np.sqrt(4 / 17))


def test_consensus_is_weighted_mean():
    m = np.array([[1.0] * 32, [3.0] * 32])
    assert np.allclose(live.consensus(m, np.array([0.25, 0.75])), 2.5)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_live.py -q -k "vegas or source_matrix or sigma or consensus"`
Expected: FAIL with `AttributeError: module 'winspool.live' has no attribute 'vegas_weight'`

- [ ] **Step 3: Implement**

Append to `src/winspool/live.py`:

```python
import os

from .data import load_power_ratings, load_win_totals
from .game import HFA, SCALE
from .ratings import backout_market, to_common_scale

VEGAS_FADE_WEEK = 9


def vegas_weight(week: int) -> float:
    """Pre-season Vegas totals stop updating in-season: fade them out linearly
    so they carry no weight from week 9 on."""
    return max(0.0, 1.0 - week / VEGAS_FADE_WEEK)


def source_matrix_for_week(totals_path, power_path, full_home, full_away, week):
    """(matrix, weights, names). Vegas (backed out of full-season O/U) first when
    the totals file exists, then every power column. Weights: Vegas gets
    vegas_weight(week); power columns share the rest equally."""
    sources = {}
    if totals_path and os.path.exists(totals_path):
        totals = load_win_totals(totals_path)
        sources["vegas"] = backout_market(totals, full_home, full_away, hfa=HFA, scale=SCALE)
    pdf = load_power_ratings(power_path)
    for col in pdf.columns:
        arr = np.zeros(N_TEAMS)
        for code, val in pdf[col].items():
            if code in TEAM_INDEX:
                arr[TEAM_INDEX[code]] = float(val)
        sources[col] = arr
    names = list(sources)
    matrix = to_common_scale(sources)
    n_power = len(names) - (1 if "vegas" in sources else 0)
    if "vegas" in sources and n_power > 0:
        wv = vegas_weight(week)
        weights = np.array([wv] + [(1.0 - wv) / n_power] * n_power)
    else:
        weights = np.full(len(names), 1.0 / len(names))
    return matrix, weights, names


def season_sigma(remaining_per_team, base_sigma=4.5) -> np.ndarray:
    """Season noise shrinks with games left: fewer games, less room for a team
    to be 'different from its rating' this year."""
    per = np.asarray(remaining_per_team, dtype=float)
    return base_sigma * np.sqrt(per / 17.0)


def consensus(matrix, weights) -> np.ndarray:
    return np.asarray(weights, dtype=float) @ np.asarray(matrix, dtype=float)
```

Move the `import os` to the top of the file with the other imports.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_live.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/winspool/live.py tests/test_live.py
git commit -m "feat(live): weekly source matrix with fading Vegas weight and shrinking season noise"
```

---

### Task 4: `compute_live` — projection rows, this-week leverage, market check

**Files:**
- Modify: `src/winspool/live.py`
- Modify: `tests/test_live.py`

**Interfaces:**
- Consumes: Task 1 `simulate_mixture(..., weights=, rng=)`, Task 2/3 helpers, `winspool.game.win_prob(sh, sa)`, `winspool.market.load_distributions(path) -> (codes, (n,18) matrix)`, `winspool.market.sample_independent(pmf_matrix, n, rng) -> (n, n_teams) int16`.
- Produces:
  - `pool_pwin(totals_by_player: dict[str, (N,) array]) -> dict[str, float]` using the `>=` rule.
  - `market_pwin(rosters, kalshi_dist_path, n_sims, rng) -> dict[str, float] | None`.
  - `compute_live(rosters, sched_df, *, totals_path, power_path, kalshi_dist_path, ratings_fetched_at, n_seasons=5000, seed=0, now=None) -> dict` with the exact shape in the spec:

```python
{"week": int, "computed_at": float, "ratings_fetched_at": str | None,
 "rows": [{"player", "teams": [{"code", "banked", "exp_wins"}], "banked", "exp_wins",
           "pwin", "market_pwin" (float | None), "p10", "p90", "dist"}],
 "x": [int...], "n_sims": int,
 "this_week": [{"player", "leverage", "games": [{"team", "opp", "home", "p"}]}]}
```
  `rows` sorted by `(pwin, exp_wins)` desc; `this_week` sorted by `leverage` desc; `teams` sorted by `exp_wins` desc.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_live.py`:

```python
ROSTERS = {
    "A": ["KC", "PHI"],
    "B": ["BUF", "DAL"],
}


def test_pool_pwin_ties_count_for_both():
    t = {"A": np.array([10, 12, 8]), "B": np.array([10, 11, 9])}
    p = live.pool_pwin(t)
    assert p["A"] == pytest.approx(2 / 3)   # seasons 0 (tie) and 1
    assert p["B"] == pytest.approx(2 / 3)   # seasons 0 (tie) and 2


def test_compute_live_shape_and_banked(inseason):
    doc = live.compute_live(ROSTERS, inseason,
                            totals_path=f"{FIX}/win_totals.csv",
                            power_path=f"{FIX}/power_ratings.csv",
                            kalshi_dist_path=None,
                            ratings_fetched_at="2026-09-23T09:00:00",
                            n_seasons=2000, seed=1, now=1000.0)
    assert doc["week"] == 3 and doc["computed_at"] == 1000.0
    assert doc["ratings_fetched_at"] == "2026-09-23T09:00:00"
    assert doc["n_sims"] == 2000 and len(doc["x"]) > 0
    rows = {r["player"]: r for r in doc["rows"]}
    assert set(rows) == {"A", "B"}
    a = rows["A"]
    # KC 3 banked + PHI 1.5 banked
    assert a["banked"] == 4.5
    assert {t["code"]: t["banked"] for t in a["teams"]} == {"KC": 3, "PHI": 1.5}
    # Each team: exp_wins >= banked and <= banked + games left (KC 1, PHI 2)
    by = {t["code"]: t for t in a["teams"]}
    assert 3 <= by["KC"]["exp_wins"] <= 4
    assert 1.5 <= by["PHI"]["exp_wins"] <= 3.5
    assert a["exp_wins"] == pytest.approx(sum(t["exp_wins"] for t in a["teams"]), abs=0.2)
    assert a["p10"] <= a["p90"]
    assert len(a["dist"]) == len(doc["x"]) and abs(sum(a["dist"]) - 1) < 1e-3
    assert a["market_pwin"] is None
    assert 0.99 <= sum(r["pwin"] for r in doc["rows"]) <= 1.2
    assert [r["pwin"] for r in doc["rows"]] == sorted((r["pwin"] for r in doc["rows"]), reverse=True)


def test_compute_live_this_week_games_and_leverage(inseason):
    doc = live.compute_live(ROSTERS, inseason,
                            totals_path=f"{FIX}/win_totals.csv",
                            power_path=f"{FIX}/power_ratings.csv",
                            kalshi_dist_path=None, ratings_fetched_at=None,
                            n_seasons=2000, seed=1)
    tw = {r["player"]: r for r in doc["this_week"]}
    # Week 3 has one unplayed game: BUF (home) vs DAL. Both are B's teams; A has none.
    assert tw["A"]["games"] == [] and tw["A"]["leverage"] == 0.0
    games = tw["B"]["games"]
    assert {g["team"] for g in games} == {"BUF", "DAL"}
    buf = next(g for g in games if g["team"] == "BUF")
    dal = next(g for g in games if g["team"] == "DAL")
    assert buf["opp"] == "DAL" and buf["home"] is True
    assert dal["opp"] == "BUF" and dal["home"] is False
    assert buf["p"] == pytest.approx(1 - dal["p"], abs=1e-6)
    # B owns both sides, so the game cannot change B's total: leverage ~ 0.
    assert tw["B"]["leverage"] == pytest.approx(0.0, abs=0.02)
    assert [r["leverage"] for r in doc["this_week"]] == sorted(
        (r["leverage"] for r in doc["this_week"]), reverse=True)


def test_compute_live_leverage_positive_when_opponent_is_not_mine(inseason):
    rosters = {"A": ["KC", "BUF"], "B": ["PHI", "DAL"]}
    doc = live.compute_live(rosters, inseason,
                            totals_path=f"{FIX}/win_totals.csv",
                            power_path=f"{FIX}/power_ratings.csv",
                            kalshi_dist_path=None, ratings_fetched_at=None,
                            n_seasons=3000, seed=2)
    tw = {r["player"]: r for r in doc["this_week"]}
    assert tw["A"]["leverage"] > 0.05 and tw["B"]["leverage"] > 0.05


def test_compute_live_season_over(inseason):
    done = inseason.copy()
    done.loc[done["home_score"].isna(), ["home_score", "away_score"]] = [20, 10]
    doc = live.compute_live(ROSTERS, done,
                            totals_path=f"{FIX}/win_totals.csv",
                            power_path=f"{FIX}/power_ratings.csv",
                            kalshi_dist_path=None, ratings_fetched_at=None,
                            n_seasons=500, seed=0)
    assert doc["week"] == 19
    assert all(r["games"] == [] for r in doc["this_week"])
    rows = {r["player"]: r for r in doc["rows"]}
    assert rows["A"]["exp_wins"] == rows["A"]["banked"]
    assert rows["A"]["p10"] == rows["A"]["p90"]


def test_market_pwin_from_pmfs(tmp_path):
    # KC always 10 wins, BUF always 9, everyone else 0 -> A (KC) beats B (BUF) always.
    cols = ["team"] + [f"p{k}" for k in range(18)]
    rows = []
    for code in TEAMS:
        pmf = [0.0] * 18
        pmf[10 if code == "KC" else 9 if code == "BUF" else 0] = 1.0
        rows.append([code] + pmf)
    path = tmp_path / "k.csv"
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)
    p = live.market_pwin({"A": ["KC"], "B": ["BUF"]}, str(path), 200, np.random.default_rng(0))
    assert p == {"A": 1.0, "B": 0.0}
    assert live.market_pwin({"A": ["KC"]}, str(tmp_path / "nope.csv"), 10,
                            np.random.default_rng(0)) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_live.py -q -k "pool_pwin or compute_live or market_pwin"`
Expected: FAIL with `AttributeError: module 'winspool.live' has no attribute 'pool_pwin'`

- [ ] **Step 3: Implement**

Append to `src/winspool/live.py` (and add `import time` and `from .game import win_prob`, `from .sim import simulate_mixture`, `from .market import load_distributions, sample_independent` to the imports at the top):

```python
def pool_pwin(totals: dict) -> dict:
    """P(win pool) per player with ties counting for everyone tied (>= rule)."""
    names = list(totals)
    stack = np.stack([np.asarray(totals[n], dtype=float) for n in names], axis=1)
    rowmax = stack.max(axis=1)
    return {n: float((stack[:, i] >= rowmax).mean()) for i, n in enumerate(names)}


def _player_totals(rosters: dict, team_wins: np.ndarray) -> dict:
    """{player: (N,) array} from a (N, 32) per-team wins matrix."""
    out = {}
    for p, codes in rosters.items():
        idx = [TEAM_INDEX[c] for c in codes]
        out[p] = team_wins[:, idx].sum(axis=1) if idx else np.zeros(team_wins.shape[0])
    return out


def market_pwin(rosters: dict, kalshi_dist_path, n_sims: int, rng):
    """Kalshi-implied P(win pool): draw each team's season total from its market
    PMF independently (as `winspool market` does) and apply the >= rule.
    None when the distributions file is missing."""
    if not kalshi_dist_path or not os.path.exists(kalshi_dist_path):
        return None
    codes, mat = load_distributions(kalshi_dist_path)
    draws = sample_independent(mat, n_sims, rng)              # (N, n_codes)
    col = {c: i for i, c in enumerate(codes)}
    totals = {}
    for p, teams in rosters.items():
        idx = [col[t] for t in teams if t in col]
        totals[p] = draws[:, idx].sum(axis=1) if idx else np.zeros(n_sims)
    return {p: round(v, 3) for p, v in pool_pwin(totals).items()}


def compute_live(rosters: dict, sched_df: pd.DataFrame, *, totals_path, power_path,
                 kalshi_dist_path, ratings_fetched_at, n_seasons=5000, seed=0,
                 now=None) -> dict:
    """The live projection document. See the spec for the field list."""
    rng = np.random.default_rng(seed)
    played, remaining = split_schedule(sched_df)
    week = week_of(sched_df)
    banked = banked_wins(played)
    reg = _reg(sched_df)
    full_home = reg["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    full_away = reg["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    matrix, weights, _names = source_matrix_for_week(totals_path, power_path,
                                                     full_home, full_away, week)
    strength = consensus(matrix, weights)

    # This week's games are drawn explicitly so a single game can be forced
    # (leverage); the rest of the season goes through the mixture sim.
    this_week = games_in_week(remaining, week)
    rest = remaining[remaining["week"] != week].reset_index(drop=True)
    sigma = season_sigma(remaining_games_per_team(rest))
    if len(rest):
        rh, ra = remaining_matchups(rest)
        future_rest = simulate_mixture(matrix, rh, ra, n_seasons, base_sigma=sigma,
                                       tie_base=0.003, weights=weights, rng=rng).astype(float)
    else:
        future_rest = np.zeros((n_seasons, N_TEAMS))

    wh, wa = remaining_matchups(this_week)
    p_home = win_prob(strength[wh], strength[wa]) if len(wh) else np.zeros(0)
    week_outcomes = rng.random((n_seasons, len(wh))) < p_home[None, :]   # True = home wins

    def week_wins(outcomes):
        w = np.zeros((n_seasons, N_TEAMS))
        for g in range(outcomes.shape[1]):
            w[:, wh[g]] += outcomes[:, g]
            w[:, wa[g]] += ~outcomes[:, g]
        return w

    team_totals = banked[None, :] + future_rest + week_wins(week_outcomes)
    totals = _player_totals(rosters, team_totals)
    pwin = pool_pwin(totals)
    stack = np.stack(list(totals.values()), axis=1)
    lo, hi = int(np.floor(stack.min())), int(np.ceil(stack.max()))
    xs = list(range(lo, hi + 1))
    mkt = market_pwin(rosters, kalshi_dist_path, n_seasons, rng)

    rows = []
    for p, col in totals.items():
        counts = np.bincount(np.rint(col - lo).astype(int), minlength=len(xs))
        teams = [{"code": c, "banked": float(banked[TEAM_INDEX[c]]),
                  "exp_wins": round(float(team_totals[:, TEAM_INDEX[c]].mean()), 1)}
                 for c in rosters[p]]
        teams.sort(key=lambda t: t["exp_wins"], reverse=True)
        rows.append({
            "player": p, "teams": teams,
            "banked": float(sum(t["banked"] for t in teams)),
            "exp_wins": round(float(col.mean()), 1),
            "pwin": round(pwin[p], 3),
            "market_pwin": None if mkt is None else mkt.get(p),
            "p10": int(np.percentile(col, 10)), "p90": int(np.percentile(col, 90)),
            "dist": (counts / max(counts.sum(), 1)).round(5).tolist(),
        })
    rows.sort(key=lambda r: (r["pwin"], r["exp_wins"]), reverse=True)

    # Leverage: for each of my games this week, |pwin if we win - pwin if we lose|.
    tw_rows = []
    for p, codes in rosters.items():
        mine = set(codes)
        games, lev = [], 0.0
        for g in range(len(wh)):
            hcode, acode = TEAMS[wh[g]], TEAMS[wa[g]]
            for team, opp, home, p_win in ((hcode, acode, True, float(p_home[g])),
                                           (acode, hcode, False, float(1 - p_home[g]))):
                if team not in mine:
                    continue
                games.append({"team": team, "opp": opp, "home": home, "p": round(p_win, 3)})
                forced = week_outcomes.copy()
                forced[:, g] = home            # my team wins
                win_tot = _player_totals(rosters, banked[None, :] + future_rest + week_wins(forced))
                forced[:, g] = not home        # my team loses
                loss_tot = _player_totals(rosters, banked[None, :] + future_rest + week_wins(forced))
                lev += abs(pool_pwin(win_tot)[p] - pool_pwin(loss_tot)[p])
        tw_rows.append({"player": p, "leverage": round(lev, 3), "games": games})
    tw_rows.sort(key=lambda r: r["leverage"], reverse=True)

    return {"week": week, "computed_at": float(now if now is not None else time.time()),
            "ratings_fetched_at": ratings_fetched_at,
            "rows": rows, "x": xs, "n_sims": int(n_seasons), "this_week": tw_rows}
```

Note on `rest` sigma: `season_sigma` is computed from games remaining *after* this week, which is what the mixture sim actually plays.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_live.py -q`
Expected: all PASS. If `test_compute_live_this_week_games_and_leverage` leverage for B is not ~0, check that both forced branches were computed with the same `future_rest` (they are; B owning both teams means exactly one win lands on B either way).

- [ ] **Step 5: Commit**

```bash
git add src/winspool/live.py tests/test_live.py
git commit -m "feat(live): compute_live — banked + remaining-season sim, this-week leverage, Kalshi market check"
```

---

### Task 5: Store support for the live doc and weekly snapshots

**Files:**
- Modify: `src/winspool/store.py` (Protocol, InMemoryStore, FirestoreStore, SqliteStore)
- Modify: `tests/test_store_sqlite.py`

**Interfaces:**
- Produces on every store:
  - `get_live() -> dict | None`, `put_live(doc: dict) -> None`
  - `put_week(week: int, doc: dict) -> None` (idempotent overwrite by week)
  - `list_weeks() -> list[dict]` full docs, ascending by `week`.
- Firestore layout: `cache/live` document; `weeks/{week}` documents. SQLite: kv key `live`; new table `weeks (week INTEGER PRIMARY KEY, doc TEXT NOT NULL)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_store_sqlite.py` (the `store` fixture there runs against memory and sqlite):

```python
def test_live_doc_round_trips(store):
    assert store.get_live() is None
    store.put_live({"week": 3, "rows": []})
    assert store.get_live() == {"week": 3, "rows": []}
    store.put_live({"week": 4, "rows": []})
    assert store.get_live()["week"] == 4


def test_weeks_are_keyed_and_sorted(store):
    assert store.list_weeks() == []
    store.put_week(3, {"week": 3, "rows": [{"player": "A", "pwin": 0.5}]})
    store.put_week(1, {"week": 1, "rows": []})
    store.put_week(3, {"week": 3, "rows": [{"player": "A", "pwin": 0.6}]})  # overwrite
    weeks = store.list_weeks()
    assert [w["week"] for w in weeks] == [1, 3]
    assert weeks[1]["rows"][0]["pwin"] == 0.6
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_store_sqlite.py -q -k "live_doc or weeks"`
Expected: FAIL with `AttributeError: 'InMemoryStore' object has no attribute 'get_live'`

- [ ] **Step 3: Implement**

`src/winspool/store.py`:

Protocol, after `put_preseason`:
```python
    def get_live(self) -> dict | None: ...
    def put_live(self, doc: dict) -> None: ...
    def put_week(self, week: int, doc: dict) -> None: ...
    def list_weeks(self) -> list[dict]: ...
```

InMemoryStore `__init__`: add `self._live: dict | None = None` and `self._weeks: dict[int, dict] = {}`. After `put_preseason`:
```python
    def get_live(self):
        return self._live

    def put_live(self, doc):
        with self._lock:
            self._live = doc

    def put_week(self, week, doc):
        with self._lock:
            self._weeks[int(week)] = doc

    def list_weeks(self):
        return [self._weeks[k] for k in sorted(self._weeks)]
```

FirestoreStore, after `put_preseason`:
```python
    def get_live(self):
        snap = self._ref.collection("cache").document("live").get()
        return snap.to_dict() if snap.exists else None

    def put_live(self, doc):
        self._ref.collection("cache").document("live").set(doc)

    def put_week(self, week, doc):
        self._ref.collection("weeks").document(str(int(week))).set(doc)

    def list_weeks(self):
        docs = [d.to_dict() for d in self._ref.collection("weeks").stream()]
        return sorted(docs, key=lambda d: d["week"])
```

SqliteStore: add to `SCHEMA`:
```sql
    CREATE TABLE IF NOT EXISTS weeks     (week INTEGER PRIMARY KEY, doc TEXT NOT NULL);
```
and after `put_preseason`:
```python
    def get_live(self) -> dict | None:
        row = self._db.execute("SELECT v FROM kv WHERE k='live'").fetchone()
        return json.loads(row[0]) if row else None

    def put_live(self, doc: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO kv (k, v) VALUES ('live', ?)",
                             (json.dumps(doc),))

    def put_week(self, week: int, doc: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO weeks (week, doc) VALUES (?, ?)",
                             (int(week), json.dumps(doc)))

    def list_weeks(self) -> list[dict]:
        rows = self._db.execute("SELECT doc FROM weeks ORDER BY week").fetchall()
        return [json.loads(r[0]) for r in rows]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_store_sqlite.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/winspool/store.py tests/test_store_sqlite.py
git commit -m "feat(store): live projection doc and weekly snapshots on all stores"
```

---

### Task 6: `refresh_live` and the three API routes

**Files:**
- Modify: `src/winspool/live.py` (add `refresh_live`)
- Modify: `src/winspool/api_league.py` (routes)
- Modify: `tests/test_api_league.py`

**Interfaces:**
- Consumes: Task 4 `compute_live`, Task 5 store methods, `winspool.standings._load_schedule()`, `winspool.auth.viewer`, `league.view(doc)["rosters"]`, existing `REFRESH_TOKEN` header check pattern.
- Produces:
  - `live.refresh_live(store, cache_dir, *, n_seasons=5000) -> dict` (the doc). Loads the schedule via `standings._load_schedule()`, caching the last good frame in `live._LAST_SCHEDULE` and reusing it on failure. Reads `ratings_fetched_at` as the max `fetched_at` among `ok` entries of `cache_dir/sources_meta.json`, else `None`. Writes `put_live(doc)`; writes `put_week(doc["week"], doc)` only if no snapshot exists for that week yet.
  - `GET /api/league/live` → the live doc, 404 if none yet.
  - `GET /api/league/weeks` → `[{"week", "rows": [{"player", "pwin", "exp_wins"}]}]` ascending.
  - `POST /internal/refresh-live` → token gated like `refresh-standings`; 503 on failure.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api_league.py`:

```python
# --- Live projection ----------------------------------------------------------

def _inseason_df():
    import pandas as pd
    cols = ["week", "game_type", "home_team", "away_team", "home_score", "away_score"]
    rows = [(1, "REG", h, a, 20, 10) for h, a in zip(TEAMS[::2], TEAMS[1::2])]     # week 1 final
    rows += [(2, "REG", a, h, None, None) for h, a in zip(TEAMS[::2], TEAMS[1::2])]  # week 2 open
    return pd.DataFrame(rows, columns=cols)


@pytest.fixture
def live_env(monkeypatch, tmp_path):
    from winspool import live, standings
    monkeypatch.setattr(standings, "_load_schedule", _inseason_df)
    monkeypatch.setattr(live, "_LAST_SCHEDULE", None)
    monkeypatch.setattr(api_league, "LIVE_CACHE_DIR", "tests/fixtures")
    monkeypatch.setattr(api_league, "LIVE_N_SEASONS", 300)
    monkeypatch.setenv("REFRESH_TOKEN", "tok")
    return live


def test_live_404_until_refreshed_and_public_after_draft(api, store, live_env):
    _complete_draft(api, store)
    anon = TestClient(server.app)
    assert anon.get("/api/league/live").status_code == 404
    r = api.post("/internal/refresh-live", headers={"X-Refresh-Token": "tok"})
    assert r.status_code == 200, r.text
    body = anon.get("/api/league/live").json()
    assert body["week"] == 2
    assert sorted(x["player"] for x in body["rows"]) == sorted(PLAYERS)
    assert all(len(r["games"]) == 6 for r in body["this_week"])
    assert store.get_live()["week"] == 2


def test_live_and_weeks_401_before_draft_done(api, store, live_env):
    assert api.get("/api/league/live").status_code == 401
    assert api.get("/api/league/weeks").status_code == 401


def test_refresh_live_token_gate(api, store, live_env, monkeypatch):
    assert api.post("/internal/refresh-live").status_code == 403
    monkeypatch.delenv("REFRESH_TOKEN")
    assert api.post("/internal/refresh-live").status_code == 503


def test_weekly_snapshot_written_once_per_week(api, store, live_env):
    _complete_draft(api, store)
    h = {"X-Refresh-Token": "tok"}
    assert api.post("/internal/refresh-live", headers=h).status_code == 200
    first = store.list_weeks()
    assert [w["week"] for w in first] == [2]
    # Second refresh in the same week: live doc updates, snapshot does not.
    assert api.post("/internal/refresh-live", headers=h).status_code == 200
    assert store.list_weeks()[0]["computed_at"] == first[0]["computed_at"]
    weeks = api.get("/api/league/weeks").json()
    assert weeks[0]["week"] == 2
    assert set(weeks[0]["rows"][0]) == {"player", "pwin", "exp_wins"}


def test_refresh_live_reuses_last_schedule_on_fetch_failure(api, store, live_env, monkeypatch):
    from winspool import standings
    _complete_draft(api, store)
    h = {"X-Refresh-Token": "tok"}
    assert api.post("/internal/refresh-live", headers=h).status_code == 200

    def boom():
        raise RuntimeError("network down")
    monkeypatch.setattr(standings, "_load_schedule", boom)
    r = api.post("/internal/refresh-live", headers=h)
    assert r.status_code == 200 and r.json()["week"] == 2


def test_refresh_live_503_with_no_schedule_at_all(api, store, live_env, monkeypatch):
    from winspool import standings
    _complete_draft(api, store)

    def boom():
        raise RuntimeError("network down")
    monkeypatch.setattr(standings, "_load_schedule", boom)
    r = api.post("/internal/refresh-live", headers={"X-Refresh-Token": "tok"})
    assert r.status_code == 503
    assert api.get("/api/league/live").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_api_league.py -q -k "live or weekly_snapshot"`
Expected: FAIL with `AttributeError: module 'winspool.api_league' has no attribute 'LIVE_CACHE_DIR'`

- [ ] **Step 3: Implement `refresh_live`**

Append to `src/winspool/live.py` (add `import json` to imports):

```python
_LAST_SCHEDULE: pd.DataFrame | None = None


def _load_schedule_cached() -> pd.DataFrame:
    """Live schedule from nfl_data_py; on failure, the last frame that worked.
    Raises if there has never been a good fetch in this process."""
    global _LAST_SCHEDULE
    from . import standings
    try:
        df = standings._load_schedule()
        _LAST_SCHEDULE = df
        return df
    except Exception:
        if _LAST_SCHEDULE is None:
            raise
        return _LAST_SCHEDULE


def ratings_fetched_at(cache_dir) -> str | None:
    """Newest fetched_at among ok sources in sources_meta.json, or None."""
    path = os.path.join(cache_dir, "sources_meta.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        meta = json.load(f)
    stamps = [m["fetched_at"] for m in meta if m.get("ok") and m.get("fetched_at")]
    return max(stamps) if stamps else None


def refresh_live(store, cache_dir, *, n_seasons=5000) -> dict:
    """Recompute the live doc from the league's final rosters and the current
    schedule + ratings cache; store it; snapshot the week if not yet snapshotted."""
    from . import league as _league
    rosters = _league.view(store.get())["rosters"]
    df = _load_schedule_cached()
    doc = compute_live(
        rosters, df,
        totals_path=os.path.join(cache_dir, "win_totals.csv"),
        power_path=os.path.join(cache_dir, "power_ratings.csv"),
        kalshi_dist_path=os.path.join(cache_dir, "kalshi_distributions.csv"),
        ratings_fetched_at=ratings_fetched_at(cache_dir),
        n_seasons=n_seasons)
    store.put_live(doc)
    if not any(w["week"] == doc["week"] for w in store.list_weeks()):
        store.put_week(doc["week"], doc)
    return doc
```

- [ ] **Step 4: Implement the routes**

In `src/winspool/api_league.py`, near the top after `TOUCH_EVERY`:

```python
from pathlib import Path

from . import live as _live

# In-season live projection. Same cache dir the sim reads; overridable for tests.
LIVE_CACHE_DIR = os.environ.get("WINSPOOL_DATA_DIR") or str(
    Path(__file__).resolve().parents[2] / "data" / "cache")
LIVE_N_SEASONS = 5000
```

After `set_override`, before `internal_refresh_standings`:

```python
@router.get("/api/league/live")
def get_live(_: str | None = Depends(viewer)):
    doc = get_store().get_live()
    if doc is None:
        raise HTTPException(404, "no live projection yet")
    return doc


@router.get("/api/league/weeks")
def get_weeks(_: str | None = Depends(viewer)):
    return [{"week": w["week"],
             "rows": [{"player": r["player"], "pwin": r["pwin"], "exp_wins": r["exp_wins"]}
                      for r in w["rows"]]}
            for w in get_store().list_weeks()]


def _check_refresh_token(x_refresh_token: str | None) -> None:
    expected = os.environ.get("REFRESH_TOKEN")
    if not expected:
        raise HTTPException(503, "refresh token not configured")
    if not x_refresh_token or not hmac.compare_digest(x_refresh_token, expected):
        raise HTTPException(403, "forbidden")


@router.post("/internal/refresh-live", include_in_schema=False)
def internal_refresh_live(x_refresh_token: str | None = Header(default=None)):
    _check_refresh_token(x_refresh_token)
    doc = _doc()
    if doc["status"] != "done":
        raise HTTPException(409, "draft not finished")
    try:
        out = _live.refresh_live(get_store(), LIVE_CACHE_DIR, n_seasons=LIVE_N_SEASONS)
    except Exception as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(e)[:200]})
    return {"ok": True, "week": out["week"], "computed_at": out["computed_at"]}
```

Replace the token check inside `internal_refresh_standings` with `_check_refresh_token(x_refresh_token)` so both routes share it.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_api_league.py -q`
Expected: all PASS, including the pre-existing `test_internal_refresh_standings_requires_token`.

- [ ] **Step 6: Commit**

```bash
git add src/winspool/live.py src/winspool/api_league.py tests/test_api_league.py
git commit -m "feat(api): live projection routes and token-gated refresh-live with weekly snapshots"
```

---

### Task 7: Export/import carries `live` and `weeks`

**Files:**
- Modify: `src/winspool/cli.py:198-245`
- Modify: `tests/test_export_import.py`

**Interfaces:**
- Consumes: Task 5 store methods.
- Produces: export payload keys add `"live"` (dict | None) and `"weeks"` (list). Import restores both.

- [ ] **Step 1: Write the failing tests**

In `tests/test_export_import.py`, in `populated()` after `s.put_preseason(...)`:
```python
    s.put_live({"week": 3, "rows": [], "computed_at": 7.0})
    s.put_week(2, {"week": 2, "rows": [], "computed_at": 5.0})
    s.put_week(3, {"week": 3, "rows": [], "computed_at": 7.0})
```
In the round-trip assertions after the preseason line:
```python
    assert dst.get_live() == src.get_live()
    assert dst.list_weeks() == src.list_weeks()
```
Update the payload key set:
```python
    assert set(payload) == {"league", "messages", "snapshots", "standings",
                            "preseason", "live", "weeks", "exported_at"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_export_import.py -q`
Expected: FAIL on the key-set assertion.

- [ ] **Step 3: Implement**

`src/winspool/cli.py` export payload:
```python
            "preseason": store.get_preseason(),
            "live": store.get_live(),
            "weeks": store.list_weeks(),
            "exported_at": _time.time(),
```
import, after the preseason block:
```python
        if payload.get("live"):
            store.put_live(payload["live"])
        for w in payload.get("weeks") or []:
            store.put_week(w["week"], w)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_export_import.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/winspool/cli.py tests/test_export_import.py
git commit -m "feat(cli): export/import carry live projection and weekly snapshots"
```

---

### Task 8: Ops — second curl in the scores unit, `make refresh-ratings`, runbook

**Files:**
- Modify: `deploy/pi/winspool-scores.service`
- Modify: `Makefile`
- Modify: `docs/pi-runbook.md`

- [ ] **Step 1: Scores unit runs both refreshes**

Replace the `ExecStart` in `deploy/pi/winspool-scores.service` with two lines (systemd runs them in order; a failing first does not block the second thanks to the leading `-`):

```ini
ExecStart=-/usr/bin/curl -fsS --retry 3 --retry-delay 5 --max-time 120 \
    -X POST -H "X-Refresh-Token: ${REFRESH_TOKEN}" \
    http://127.0.0.1:8080/internal/refresh-standings
ExecStart=/usr/bin/curl -fsS --retry 3 --retry-delay 5 --max-time 300 \
    -X POST -H "X-Refresh-Token: ${REFRESH_TOKEN}" \
    http://127.0.0.1:8080/internal/refresh-live
```

- [ ] **Step 2: `make refresh-ratings`**

Add under the `# == Development` section of `Makefile`:

```make
.PHONY: refresh-ratings
refresh-ratings:  ## Fetch fresh power ratings + Kalshi, commit CSVs on a branch, push (run weekly from a laptop)
	@test "$$(git rev-parse --abbrev-ref HEAD)" != "main" || { echo "switch off main first: git checkout -b ratings/$$(date +%F)"; exit 1; }
	uv run winspool fetch
	git add data/cache/power_ratings.csv data/cache/kalshi_distributions.csv data/cache/sources_meta.json
	git commit -m "data: ratings refresh $$(date +%F)"
	git push -u origin HEAD
	@echo "open a PR into main, merge, then 'make deploy' on the Pi"
```

`win_totals.csv` is deliberately not added: sportsbook totals are pre-season only.

- [ ] **Step 3: Runbook**

Append to `docs/pi-runbook.md`:

```markdown
## Weekly ratings refresh (manual)

Tuesday morning, from a laptop with Chromium available for nfelo:

    git checkout -b ratings/$(date +%F) origin/main
    make refresh-ratings

Open the PR, merge, then on the Pi `make deploy`. The scores timer calls
`/internal/refresh-live` after every standings refresh, so the live projection
picks up the new ratings on its next run. If a week is skipped the Standings
footer shows the stale chip once ratings are more than 8 days old.
```

- [ ] **Step 4: Verify the unit file parses**

Run: `systemd-analyze verify deploy/pi/winspool-scores.service 2>&1 || true` (macOS has no systemd; a visual check of the two `ExecStart=` lines is the gate here). Run `make -n refresh-ratings` and confirm the commands print.

- [ ] **Step 5: Commit**

```bash
git add deploy/pi/winspool-scores.service Makefile docs/pi-runbook.md
git commit -m "ops: refresh-live after standings refresh; make refresh-ratings; runbook"
```

---

### Task 9: Front end — types, win %, delta, mover, stale ratings

**Files:**
- Modify: `web/src/league.ts`
- Modify: `web/src/components/Standings.tsx`
- Modify: `web/src/live.css`

**Interfaces:**
- Produces in `league.ts`:

```ts
export interface LiveGame { team: string; opp: string; home: boolean; p: number }
export interface LiveWeekRow { player: string; leverage: number; games: LiveGame[] }
export interface LiveTeam { code: string; banked: number; exp_wins: number }
export interface LiveRow {
  player: string; teams: LiveTeam[]; banked: number; exp_wins: number;
  pwin: number; market_pwin: number | null; p10: number; p90: number; dist: number[];
}
export interface LiveProjection {
  week: number; computed_at: number; ratings_fetched_at: string | null;
  rows: LiveRow[]; x: number[]; n_sims: number; this_week: LiveWeekRow[];
}
export interface WeekPoint { week: number; rows: { player: string; pwin: number; exp_wins: number }[] }
export const getLive = () => call<LiveProjection>('/api/league/live');
export const getWeeks = () => call<WeekPoint[]>('/api/league/weeks');
```

- [ ] **Step 1: Add the types and calls**

Append the block above to `web/src/league.ts`.

- [ ] **Step 2: Fetch live + weeks in Standings**

In `web/src/components/Standings.tsx`:

```tsx
import type { LeagueView, LiveProjection, Me, StandingsResponse, WeekPoint } from '../league';
import { getLive, getStandings, getWeeks, setOverride } from '../league';
```

Add state and a loader next to the existing effects:

```tsx
  const [live, setLive] = useState<LiveProjection | null>(null);
  const [weeks, setWeeks] = useState<WeekPoint[]>([]);

  useEffect(() => {
    let alive = true;
    let timer: number;
    const tick = async () => {
      try {
        const [l, w] = await Promise.all([getLive(), getWeeks()]);
        if (alive) { setLive(l); setWeeks(w); }
      } catch { /* 404 until the first refresh; keep last */ }
      timer = window.setTimeout(tick, 5 * 60_000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);
```

Derive per-player numbers before the `return`:

```tsx
  const pwinBy: Record<string, number> = {};
  const mktBy: Record<string, number | null> = {};
  for (const r of live?.rows ?? []) { pwinBy[r.player] = r.pwin; mktBy[r.player] = r.market_pwin; }
  const deltaBy: Record<string, number> = {};
  if (weeks.length >= 2) {
    const prev = Object.fromEntries(weeks[weeks.length - 2].rows.map((r) => [r.player, r.pwin]));
    for (const r of weeks[weeks.length - 1].rows) deltaBy[r.player] = r.pwin - (prev[r.player] ?? r.pwin);
  }
  const mover = Object.entries(deltaBy).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0]?.[0];
  const ratingsStale = !!live?.ratings_fetched_at
    && Date.now() - new Date(live.ratings_fetched_at).getTime() > 8 * 24 * 3600_000;
```

- [ ] **Step 3: Render win %, delta, mover**

Change the card class and add a second footer row under the existing `standings-foot`:

```tsx
              <div key={r.player} className={`standings-player${isMe ? ' me' : ''}${r.player === mover ? ' mover' : ''}`}>
```

```tsx
                <div className="standings-foot">
                  <span>Total</span>
                  <b>{r.total}</b>
                </div>
                {pwinBy[r.player] !== undefined && (
                  <div className="standings-foot standings-win">
                    <span>Win</span>
                    <b>
                      {Math.round(pwinBy[r.player] * 100)}%
                      {mktBy[r.player] != null && Math.abs(mktBy[r.player]! - pwinBy[r.player]) > 0.05 && (
                        <span className="mkt">mkt {Math.round(mktBy[r.player]! * 100)}%</span>
                      )}
                      {deltaBy[r.player] !== undefined && Math.round(Math.abs(deltaBy[r.player]) * 100) > 0 && (
                        <span className={`delta ${deltaBy[r.player] > 0 ? 'up' : 'down'}`}>
                          {deltaBy[r.player] > 0 ? '▲' : '▼'} {Math.round(Math.abs(deltaBy[r.player]) * 100)}
                        </span>
                      )}
                    </b>
                  </div>
                )}
```

Extend the existing stale line:

```tsx
        <div className="stale">
          Updated {new Date(data.fetched_at * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
          {(data.stale || ratingsStale) && ' · stale'}
        </div>
```

- [ ] **Step 4: Styles**

Append to `web/src/live.css`:

```css
.standings-player.mover { box-shadow: inset 0 0 0 2px var(--accent, #d50a0a), var(--shadow-sm); }
.standings-win b { display: inline-flex; align-items: baseline; gap: var(--s2); }
.standings-win .delta { font-size: 12px; font-weight: 700; }
.standings-win .delta.up { color: #1a7f37; }
.standings-win .delta.down { color: #b42318; }
.standings-win .mkt { font-size: 11px; font-weight: 500; color: var(--text-dim); }
```

If `--accent` is not defined in `App.css`, use `var(--navy)` with `opacity` unchanged; the `me` border already uses navy, so the mover border must differ: use `#d50a0a` directly.

- [ ] **Step 5: Build and lint**

Run: `cd web && npm run build && npm run lint`
Expected: both clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/league.ts web/src/components/Standings.tsx web/src/live.css
git commit -m "feat(web): live win % with week-over-week delta and market check on standings cards"
```

---

### Task 10: Front end — This week strip

**Files:**
- Create: `web/src/components/ThisWeek.tsx`
- Modify: `web/src/components/Standings.tsx` (mount)
- Modify: `web/src/live.css`

**Interfaces:**
- Consumes: `LiveProjection` from Task 9, `TeamLogo`, `playerColor`.
- Produces: `<ThisWeek live={live} />`. Renders nothing when `live.this_week` has no games at all (season over).

- [ ] **Step 1: Component**

Create `web/src/components/ThisWeek.tsx`:

```tsx
// web/src/components/ThisWeek.tsx — each player's games this week, ordered by
// how much the week can swing their pool odds.
import { playerColor } from '../colors';
import type { LiveProjection } from '../league';
import TeamLogo from './TeamLogo';

const first = (n: string) => n.trim().split(/\s+/)[0] ?? n;

export default function ThisWeek({ live }: { live: LiveProjection }) {
  if (!live.this_week.some((r) => r.games.length)) return null;
  return (
    <div className="card">
      <span className="eyebrow">Week {live.week}</span>
      <div className="week-grid">
        {live.this_week.map((r) => {
          const c = playerColor(r.player);
          return (
            <div key={r.player} className="week-row">
              <span className="week-name"><span className="proj-swatch" style={{ background: c.bg }} />{first(r.player)}</span>
              <span className="week-games">
                {r.games.map((g) => (
                  <span key={g.team} className="week-game" title={`${g.team} ${g.home ? 'vs' : 'at'} ${g.opp}`}>
                    <TeamLogo code={g.team} size={18} />
                    <span className="week-vs">{g.home ? 'vs' : '@'}</span>
                    <TeamLogo code={g.opp} size={18} />
                    <b>{Math.round(g.p * 100)}%</b>
                  </span>
                ))}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Mount**

In `Standings.tsx`, import `ThisWeek from './ThisWeek'` and render between the standings card and the feed:

```tsx
      {live && <ThisWeek live={live} />}
      <Feed view={view} myName={me?.name ?? null} />
```

- [ ] **Step 3: Styles**

Append to `web/src/live.css`:

```css
.week-grid { display: flex; flex-direction: column; }
.week-row { display: grid; grid-template-columns: 7.5em 1fr; gap: var(--s2) var(--s3); align-items: start; padding: var(--s2) 0; border-top: 1px solid var(--border); font-size: 14px; }
.week-name { white-space: nowrap; }
.week-games { display: flex; flex-wrap: wrap; gap: var(--s2) var(--s4); font-size: 12px; color: var(--text-dim); font-variant-numeric: tabular-nums; }
.week-game { display: inline-flex; align-items: center; gap: 3px; }
.week-game b { color: var(--text); margin-left: 2px; }
.week-vs { font-size: 10px; }
@media (max-width: 480px) { .week-row { grid-template-columns: 1fr; } }
```

- [ ] **Step 4: Build and lint**

Run: `cd web && npm run build && npm run lint`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/ThisWeek.tsx web/src/components/Standings.tsx web/src/live.css
git commit -m "feat(web): this-week strip on standings ordered by leverage"
```

---

### Task 11: Front end — Movement chart

**Files:**
- Create: `web/src/components/MovementChart.tsx`
- Modify: `web/src/components/Standings.tsx` (mount)
- Modify: `web/src/live.css`

**Interfaces:**
- Consumes: `WeekPoint[]` from Task 9, `playerColor`.
- Produces: `<MovementChart weeks={weeks} me={me?.name ?? ''} />`. Renders nothing with fewer than 3 weeks.

- [ ] **Step 1: Component**

Create `web/src/components/MovementChart.tsx`:

```tsx
// web/src/components/MovementChart.tsx — P(win pool) by NFL week, one line per player.
import { useEffect, useRef, useState } from 'react';
import { playerColor } from '../colors';
import type { WeekPoint } from '../league';

const first = (n: string) => n.trim().split(/\s+/)[0] ?? n;
const H = 200, ML = 34, MR = 56, MT = 10, MB = 24;

export default function MovementChart({ weeks, me }: { weeks: WeekPoint[]; me: string }) {
  const box = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(380);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(Math.max(240, el.clientWidth)));
    ro.observe(el);
    setW(Math.max(240, el.clientWidth));
    return () => ro.disconnect();
  }, []);
  if (weeks.length < 3) return null;

  const players = weeks[weeks.length - 1].rows.map((r) => r.player);
  const series = players.map((p) => ({
    player: p,
    pts: weeks.map((w) => ({ week: w.week, p: w.rows.find((r) => r.player === p)?.pwin ?? 0 })),
  }));
  const x0 = weeks[0].week, x1 = weeks[weeks.length - 1].week;
  const maxP = Math.max(0.2, ...series.flatMap((s) => s.pts.map((q) => q.p)));
  const pw = W - ML - MR, ph = H - MT - MB;
  const xPx = (w: number) => ML + ((w - x0) / Math.max(1, x1 - x0)) * pw;
  const yPx = (p: number) => MT + ph - (p / maxP) * ph;
  const path = (pts: { week: number; p: number }[]) =>
    pts.map((q, i) => `${i ? 'L' : 'M'}${xPx(q.week).toFixed(1)},${yPx(q.p).toFixed(1)}`).join('');
  const yTicks = [0, 0.25, 0.5, 0.75, 1].filter((t) => t <= maxP + 1e-9);

  return (
    <div className="card">
      <span className="eyebrow">Win probability by week</span>
      <div ref={box} className="move-chart">
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label="Each player's probability of winning the pool by NFL week">
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={ML} y1={yPx(t)} x2={ML + pw} y2={yPx(t)} stroke="var(--border)" />
              <text x={ML - 6} y={yPx(t) + 3} fill="var(--text-dim)" fontSize={10} textAnchor="end">{Math.round(t * 100)}%</text>
            </g>
          ))}
          {weeks.map((w) => (
            <text key={w.week} x={xPx(w.week)} y={H - 6} fill="var(--text-dim)" fontSize={10} textAnchor="middle">{w.week}</text>
          ))}
          {series.map((s) => {
            const c = playerColor(s.player).bg;
            const last = s.pts[s.pts.length - 1];
            return (
              <g key={s.player}>
                <path d={path(s.pts)} fill="none" stroke={c} strokeWidth={s.player === me ? 3 : 2} />
                <text x={xPx(last.week) + 6} y={yPx(last.p) + 3} fill={c} fontSize={11} fontWeight={700}>
                  {first(s.player)} {Math.round(last.p * 100)}%
                </text>
              </g>
            );
          })}
        </svg>
        <div className="move-axes"><span>Week</span><span>Win %</span></div>
      </div>
    </div>
  );
}
```


- [ ] **Step 2: Mount**

In `Standings.tsx`, import `MovementChart from './MovementChart'` and render after `ThisWeek`:

```tsx
      {live && <ThisWeek live={live} />}
      <MovementChart weeks={weeks} me={me?.name ?? ''} />
      <Feed view={view} myName={me?.name ?? null} />
```

- [ ] **Step 3: Styles**

Append to `web/src/live.css`:

```css
.move-chart { position: relative; }
.move-chart svg { display: block; max-width: 100%; }
.move-axes { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-dim); margin-top: 2px; }
```

- [ ] **Step 4: Build and lint**

Run: `cd web && npm run build && npm run lint`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/MovementChart.tsx web/src/components/Standings.tsx web/src/live.css
git commit -m "feat(web): win probability by week chart on standings"
```

---

### Task 12: End-to-end check against the dev league and PR

**Files:** none new.

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 2: Manual run**

Terminal 1: `REFRESH_TOKEN=dev uv run winspool-serve --port 8000`
Terminal 2: `cd web && npm run dev`

In the browser at the Vite URL, log in as each of the five dev players (PIN `1234`), let the commissioner randomize, and make all 30 picks (or use the Practice tab's autosim if it drives the league; otherwise pick by hand). Then:

```bash
curl -s -X POST -H "X-Refresh-Token: dev" http://127.0.0.1:8000/internal/refresh-live
curl -s http://127.0.0.1:8000/api/league/live | head -c 400
```

Expected: `{"ok": true, "week": N, ...}` then a doc. Note: this hits nfl_data_py over the network for the real schedule; before week 1 kicks off `week` is 1 and `this_week` lists every team's opener.

Open Standings in a private window (anonymous). Expected: cards show `Win NN%`, no delta (one snapshot), the `Week N` strip with each player's six games and percentages, no chart (fewer than three weeks), and the feed without a compose box.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/live-standings
gh pr create --base main --head feat/live-standings \
  --title "Live standings: weekly win probabilities, this-week leverage, movement chart" \
  --body "Implements docs/superpowers/specs/2026-09-07-live-standings-design.md. See plan docs/superpowers/plans/2026-09-07-live-standings.md."
```

Do not merge; the user merges.

---

## Self-review notes

- Spec coverage: standings win % + delta + mover (Task 9), this-week strip ordered by leverage (Tasks 4, 10), movement chart hidden under 3 snapshots (Task 11), remaining-season sim with Vegas fade and shrinking sigma (Tasks 1, 3, 4), Kalshi market check with 5-point display rule (Tasks 4, 9), storage and once-per-week snapshot (Tasks 5, 6), routes and auth (Task 6), scores job + manual ratings refresh + stale chip at 8 days (Tasks 8, 9), export/import (Task 7), error handling: 503 keeps previous doc, schedule fallback, 404 before first refresh (Task 6).
- Deviation from spec, deliberate: the spec's `leverage` sims each forced game through the full mixture; the plan draws this week's games explicitly as Bernoulli outcomes from consensus strengths and forces columns, which is equivalent for leverage and avoids 12 extra full sims per player. The spec's "snapshot when all of that week's games are final" is realised as "snapshot keyed by the upcoming week, written the first time that week is seen", which is the same moment.
- Type consistency: `LiveProjection.this_week[].games[]` fields `team/opp/home/p` match `compute_live`; `WeekPoint.rows[]` fields `player/pwin/exp_wins` match `get_weeks`.
