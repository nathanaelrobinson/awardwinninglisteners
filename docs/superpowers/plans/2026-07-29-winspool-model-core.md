# NFL Wins Pool — Model Core (Plan 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working Python package (`winspool`) that simulates the NFL season and, given a live draft state, recommends draft picks that maximize P(I finish 1st) in a 6-player winner-take-all wins pool.

**Architecture:** Data (CSV cache) → strength ratings → Monte Carlo season sim producing an N×32 win matrix → draft brain that reads that matrix to rank picks. Built MVP-first: a crude end-to-end recommender runs by Task 6, then calibration, variance analysis, rollout lookahead, and mock studies are layered on. Backend (Plan 2) and React UI (Plan 3) come later.

**Tech Stack:** Python 3.11+, numpy, pandas, scipy (`scipy.stats.norm`, `scipy.optimize.brentq`), pytest, `nfl_data_py` (data fetch only, never in tests).

## Global Constraints

- Python 3.11+. Dependencies limited to: `numpy`, `pandas`, `scipy`, `nfl_data_py`, and `pytest` (dev). No web framework or scraping libs in this plan.
- **Team indexing is stable and global:** `winspool.teams.TEAMS` is the 32 nflverse team codes sorted alphabetically; a team's column index in every matrix is its position in `TEAMS`. Never reorder.
- **Determinism:** all randomness goes through an explicitly-passed `numpy.random.Generator` (`np.random.default_rng(seed)`). No global `np.random` calls, no `Date.now`-style nondeterminism. Tests seed the RNG and assert reproducibility.
- **No network in tests.** `nfl_data_py` is used only in `scripts/fetch_data.py`. All tests read small CSV fixtures under `tests/fixtures/`.
- Player slots are 1–6 (matching the draft table); internally a player's column index is `player - 1`.
- Constants: 32 teams, 6 players, 5 teams/player, 30 picks. `HFA = 2.0` pts, `SCALE = 13.5` pts (margin-of-victory SD).
- Commit after every task with a `feat:`/`test:`/`chore:` message. Do not push (no remote configured).

---

## Milestone A — MVP: end-to-end recommender (Tasks 1–6)

By the end of Task 6, `winspool recommend --slot N --taken ...` prints a ranked list of best available picks from real data. Ratings are crude (linear from Vegas O/U) and the recommender is naive (no rollout) — that's fine; it's the runnable skeleton we'll sharpen.

### Task 1: Project scaffold + team constants

**Files:**
- Create: `pyproject.toml`
- Create: `src/winspool/__init__.py`
- Create: `src/winspool/teams.py`
- Test: `tests/test_teams.py`

**Interfaces:**
- Produces: `winspool.teams.TEAMS: list[str]` (32 codes, sorted), `TEAM_INDEX: dict[str,int]`, `DIVISION: dict[str,str]`, `N_TEAMS=32`, `N_PLAYERS=6`, `ROSTER_SIZE=5`, `N_PICKS=30`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "winspool"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["numpy", "pandas", "scipy", "nfl_data_py"]

[project.optional-dependencies]
dev = ["pytest"]

[project.scripts]
winspool = "winspool.cli:main"

[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_teams.py
from winspool.teams import TEAMS, TEAM_INDEX, DIVISION, N_TEAMS

def test_thirty_two_unique_sorted_teams():
    assert len(TEAMS) == N_TEAMS == 32
    assert len(set(TEAMS)) == 32
    assert TEAMS == sorted(TEAMS)

def test_index_matches_position():
    assert all(TEAM_INDEX[c] == i for i, c in enumerate(TEAMS))

def test_eight_divisions_of_four():
    from collections import Counter
    counts = Counter(DIVISION[c] for c in TEAMS)
    assert len(counts) == 8
    assert all(v == 4 for v in counts.values())
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pip install -e ".[dev]" && pytest tests/test_teams.py -v`
Expected: FAIL (`ModuleNotFoundError: winspool.teams`).

- [ ] **Step 4: Write the implementation**

```python
# src/winspool/__init__.py
# (empty; package marker)
```

```python
# src/winspool/teams.py
N_TEAMS = 32
N_PLAYERS = 6
ROSTER_SIZE = 5
N_PICKS = 30

_DIVISIONS = {
    "AFC East": ["BUF", "MIA", "NE", "NYJ"],
    "AFC North": ["BAL", "CIN", "CLE", "PIT"],
    "AFC South": ["HOU", "IND", "JAX", "TEN"],
    "AFC West": ["DEN", "KC", "LAC", "LV"],
    "NFC East": ["DAL", "NYG", "PHI", "WAS"],
    "NFC North": ["CHI", "DET", "GB", "MIN"],
    "NFC South": ["ATL", "CAR", "NO", "TB"],
    "NFC West": ["ARI", "LA", "SEA", "SF"],
}

DIVISION = {code: div for div, codes in _DIVISIONS.items() for code in codes}
TEAMS = sorted(DIVISION.keys())
TEAM_INDEX = {code: i for i, code in enumerate(TEAMS)}

assert len(TEAMS) == N_TEAMS
```

- [ ] **Step 5: Run tests, then commit**

Run: `pytest tests/test_teams.py -v` → Expected: PASS.

```bash
git add pyproject.toml src/winspool/__init__.py src/winspool/teams.py tests/test_teams.py
git commit -m "feat: project scaffold and stable team constants"
```

---

### Task 2: Data layer — CSV cache loaders

**Files:**
- Create: `src/winspool/data.py`
- Create: `scripts/fetch_data.py`
- Create: `tests/fixtures/schedule_2026.csv`
- Create: `tests/fixtures/win_totals.csv`
- Test: `tests/test_data.py`

**Interfaces:**
- Consumes: `TEAMS`, `TEAM_INDEX` from Task 1.
- Produces:
  - `load_schedule(path) -> pandas.DataFrame` (columns `home_team, away_team`, regular season only).
  - `schedule_matchups(df) -> tuple[np.ndarray, np.ndarray]` (`home_idx`, `away_idx`, dtype int, values are team column indices).
  - `load_win_totals(path) -> np.ndarray` shape (32,), aligned to `TEAMS` order.

- [ ] **Step 1: Write fixtures**

```csv
# tests/fixtures/schedule_2026.csv
home_team,away_team,game_type
BUF,NYJ,REG
NYJ,BUF,REG
KC,LV,REG
LV,KC,REG
BUF,KC,REG
DAL,PHI,REG
PHI,DAL,REG
BUF,MIA,PRE
```

```csv
# tests/fixtures/win_totals.csv
team,win_total
BUF,11.5
NYJ,6.5
KC,11.0
LV,6.5
DAL,9.5
PHI,10.5
MIA,8.5
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_data.py
import numpy as np
from winspool.data import load_schedule, schedule_matchups, load_win_totals
from winspool.teams import TEAM_INDEX, N_TEAMS

SCHED = "tests/fixtures/schedule_2026.csv"
TOTALS = "tests/fixtures/win_totals.csv"

def test_load_schedule_drops_non_regular():
    df = load_schedule(SCHED)
    assert len(df) == 7  # the PRE row is dropped

def test_matchups_are_team_indices():
    home, away = schedule_matchups(load_schedule(SCHED))
    assert home.dtype.kind == "i" and away.dtype.kind == "i"
    assert home[0] == TEAM_INDEX["BUF"] and away[0] == TEAM_INDEX["NYJ"]
    assert len(home) == len(away) == 7

def test_win_totals_aligned_and_full_length():
    totals = load_win_totals(TOTALS)
    assert totals.shape == (N_TEAMS,)
    assert totals[TEAM_INDEX["BUF"]] == 11.5
    # teams absent from the file default to the league-average total
    assert np.isfinite(totals).all()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_data.py -v`
Expected: FAIL (`ModuleNotFoundError: winspool.data`).

- [ ] **Step 4: Write the implementation**

```python
# src/winspool/data.py
import numpy as np
import pandas as pd
from .teams import TEAM_INDEX, N_TEAMS

def load_schedule(path):
    df = pd.read_csv(path)
    df = df[df["game_type"].str.upper() == "REG"].reset_index(drop=True)
    return df[["home_team", "away_team"]]

def schedule_matchups(df):
    home = df["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    away = df["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    return home, away

def load_win_totals(path):
    df = pd.read_csv(path)
    totals = np.full(N_TEAMS, np.nan)
    for _, row in df.iterrows():
        totals[TEAM_INDEX[row["team"]]] = float(row["win_total"])
    # teams with no posted number default to the mean of those posted
    totals[np.isnan(totals)] = np.nanmean(totals)
    return totals
```

```python
# scripts/fetch_data.py
"""Fetch the real 2026 schedule into a CSV the loaders read.
Run manually (needs network): python scripts/fetch_data.py
Win totals are maintained by hand in data/cache/win_totals.csv (team,win_total)."""
import os
import nfl_data_py as nfl

CACHE = "data/cache"

def main():
    os.makedirs(CACHE, exist_ok=True)
    sched = nfl.import_schedules([2026])
    cols = sched.rename(columns={"game_type": "game_type"})[["home_team", "away_team", "game_type"]]
    cols.to_csv(f"{CACHE}/schedule_2026.csv", index=False)
    print(f"Wrote {CACHE}/schedule_2026.csv ({len(cols)} games)")

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests, then commit**

Run: `pytest tests/test_data.py -v` → Expected: PASS.

```bash
git add src/winspool/data.py scripts/fetch_data.py tests/fixtures/ tests/test_data.py
git commit -m "feat: CSV data loaders for schedule and win totals + fetch script"
```

---

### Task 3: Game model + MVP strength ratings

**Files:**
- Create: `src/winspool/game.py`
- Create: `src/winspool/ratings.py`
- Test: `tests/test_game.py`, `tests/test_ratings.py`

**Interfaces:**
- Consumes: `TEAMS`, `N_TEAMS`.
- Produces:
  - `game.HFA=2.0`, `game.SCALE=13.5`, `game.win_prob(sh, sa, hfa=HFA, scale=SCALE) -> float|ndarray`.
  - `game.expected_wins(strengths, home_idx, away_idx, hfa=HFA, scale=SCALE) -> ndarray(32,)`.
  - `ratings.WINS_PER_POINT = 0.502`.
  - `ratings.strength_from_totals(win_totals: ndarray(32,)) -> ndarray(32,)` (mean-centered strengths in points).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_game.py
import numpy as np
from winspool.game import win_prob, expected_wins, HFA, SCALE

def test_even_matchup_on_neutral_is_half():
    assert abs(win_prob(0.0, 0.0, hfa=0.0) - 0.5) < 1e-9

def test_seven_point_favorite_neutral_about_seventy():
    p = win_prob(7.0, 0.0, hfa=0.0)
    assert 0.66 < p < 0.72

def test_home_field_helps_home_team():
    assert win_prob(0.0, 0.0, hfa=HFA) > 0.5

def test_expected_wins_sums_to_total_games():
    # 2-team, 2-game fixture: each game contributes exactly 1 win somewhere
    home = np.array([0, 1]); away = np.array([1, 0])
    ew = expected_wins(np.zeros(2), home, away, hfa=0.0)
    assert abs(ew.sum() - 2.0) < 1e-9
```

```python
# tests/test_ratings.py
import numpy as np
from winspool.ratings import strength_from_totals

def test_higher_total_gets_higher_strength():
    totals = np.array([11.5, 6.5, 9.0])
    s = strength_from_totals(totals)
    assert s[0] > s[2] > s[1]

def test_strengths_mean_centered():
    s = strength_from_totals(np.array([11.5, 6.5, 9.0, 8.0]))
    assert abs(s.mean()) < 1e-9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_game.py tests/test_ratings.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write the implementations**

```python
# src/winspool/game.py
import numpy as np
from scipy.stats import norm

HFA = 2.0
SCALE = 13.5

def win_prob(sh, sa, hfa=HFA, scale=SCALE):
    return norm.cdf((np.asarray(sh) - np.asarray(sa) + hfa) / scale)

def expected_wins(strengths, home_idx, away_idx, hfa=HFA, scale=SCALE):
    strengths = np.asarray(strengths, dtype=float)
    p_home = win_prob(strengths[home_idx], strengths[away_idx], hfa, scale)
    ew = np.zeros(len(strengths))
    np.add.at(ew, home_idx, p_home)
    np.add.at(ew, away_idx, 1.0 - p_home)
    return ew
```

```python
# src/winspool/ratings.py
import numpy as np

# d(expected wins)/d(strength) at a neutral matchup over a 17-game season:
#   17 * (1/SCALE) * pdf(0) = 17 * (1/13.5) * 0.3989 ≈ 0.502 wins per point.
WINS_PER_POINT = 0.502

def strength_from_totals(win_totals):
    totals = np.asarray(win_totals, dtype=float)
    centered = totals - totals.mean()
    return centered / WINS_PER_POINT
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_game.py tests/test_ratings.py -v` → Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/winspool/game.py src/winspool/ratings.py tests/test_game.py tests/test_ratings.py
git commit -m "feat: game win-prob model and MVP strength-from-totals"
```

---

### Task 4: Monte Carlo season simulation

**Files:**
- Create: `src/winspool/sim.py`
- Test: `tests/test_sim.py`

**Interfaces:**
- Consumes: `game.HFA`, `game.SCALE`.
- Produces: `sim.simulate(strengths, sigma, home_idx, away_idx, n_seasons, *, hfa=HFA, scale=SCALE, tie_base=0.0, rng) -> np.ndarray` shape `(n_seasons, n_teams)`, dtype int16 (win totals). `sigma` is a `(n_teams,)` array of preseason strength SDs.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sim.py
import numpy as np
from winspool.sim import simulate

def _two_team(rng, n=20000, sig=0.0):
    # team 0 is +14 pts stronger; play each other twice, no HFA
    home = np.array([0, 1]); away = np.array([1, 0])
    s = np.array([7.0, -7.0]); sigma = np.array([sig, sig])
    return simulate(s, sigma, home, away, n, hfa=0.0, rng=rng)

def test_shape_and_dtype():
    w = _two_team(np.random.default_rng(1))
    assert w.shape == (20000, 2) and w.dtype == np.int16

def test_stronger_team_wins_more():
    w = _two_team(np.random.default_rng(2))
    # 14-pt gap over 2 games -> stronger team averages well above 1 win
    assert w[:, 0].mean() > w[:, 1].mean()
    assert 1.2 < w[:, 0].mean() < 2.0

def test_deterministic_under_seed():
    a = _two_team(np.random.default_rng(7))
    b = _two_team(np.random.default_rng(7))
    assert np.array_equal(a, b)

def test_sigma_widens_spread():
    narrow = _two_team(np.random.default_rng(3), sig=0.0)
    wide = _two_team(np.random.default_rng(3), sig=8.0)
    assert wide[:, 0].std() >= narrow[:, 0].std()

def test_ties_reduce_total_wins():
    home = np.array([0, 1]); away = np.array([1, 0])
    s = np.zeros(2); sigma = np.zeros(2)
    no_tie = simulate(s, sigma, home, away, 50000, hfa=0.0, tie_base=0.0,
                      rng=np.random.default_rng(4))
    with_tie = simulate(s, sigma, home, away, 50000, hfa=0.0, tie_base=0.05,
                        rng=np.random.default_rng(4))
    assert with_tie.sum() < no_tie.sum()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sim.py -v`
Expected: FAIL (`ModuleNotFoundError: winspool.sim`).

- [ ] **Step 3: Write the implementation**

```python
# src/winspool/sim.py
import numpy as np
from scipy.stats import norm
from .game import HFA, SCALE

def simulate(strengths, sigma, home_idx, away_idx, n_seasons, *,
             hfa=HFA, scale=SCALE, tie_base=0.0, rng):
    strengths = np.asarray(strengths, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    n_teams = strengths.size
    # one true-strength draw per season per team (preseason uncertainty)
    S = strengths[None, :] + rng.standard_normal((n_seasons, n_teams)) * sigma[None, :]
    wins = np.zeros((n_seasons, n_teams), dtype=np.int16)
    for h, a in zip(home_idx, away_idx):
        z = (S[:, h] - S[:, a] + hfa) / scale
        p_home = norm.cdf(z)
        tie_p = tie_base * np.exp(-0.5 * z * z) if tie_base > 0 else 0.0
        u = rng.random(n_seasons)          # decides tie
        r = rng.random(n_seasons)          # decides winner if not tie
        tie = u < tie_p
        home_win = (~tie) & (r < p_home)
        away_win = (~tie) & (~(r < p_home))
        wins[:, h] += home_win
        wins[:, a] += away_win
    return wins
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sim.py -v` → Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/winspool/sim.py tests/test_sim.py
git commit -m "feat: Monte Carlo season simulation to N x 32 win matrix"
```

---

### Task 5: Draft state + P(win) objective + greedy pick

**Files:**
- Create: `src/winspool/draft.py`
- Test: `tests/test_draft.py`

**Interfaces:**
- Consumes: `N_TEAMS`, `N_PLAYERS`, `N_PICKS`.
- Produces:
  - `draft.PICK_ORDER: list[int]` (length 30, player 1–6 picking at each pick index).
  - `draft.DraftState(my_player)` with: `.picks: list[tuple[int,int]]`, `.board() -> list[int]`, `.rosters() -> dict[int,list[int]]`, `.current_player -> int|None`, `.done -> bool`, `.apply_pick(team_idx)`, `.copy()`, `.picks_until_my_next() -> int`.
  - `draft.player_totals(rosters, wins) -> ndarray(n, N_PLAYERS)`.
  - `draft.pwin(rosters, wins, player) -> float` (ties count as a win — co-champion rule).
  - `draft.greedy_pick(state, wins, player) -> int` (available team maximizing that player's `pwin`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_draft.py
import numpy as np
from collections import Counter
from winspool.draft import (PICK_ORDER, DraftState, player_totals, pwin, greedy_pick)

def test_pick_order_valid():
    assert len(PICK_ORDER) == 30
    counts = Counter(PICK_ORDER)
    assert set(counts) == {1, 2, 3, 4, 5, 6}
    assert all(v == 5 for v in counts.values())
    assert PICK_ORDER[:6] == [1, 2, 3, 4, 5, 6]

def test_state_tracks_board_and_current_player():
    st = DraftState(my_player=3)
    assert st.current_player == 1
    st.apply_pick(10)  # player 1 takes team 10
    assert st.current_player == 2
    assert 10 not in st.board()
    assert st.rosters()[1] == [10]

def test_pwin_ties_count_as_win():
    # 2 sims, 2 players, identical totals -> both "win" every sim
    wins = np.array([[3, 3], [4, 4]], dtype=np.int16)  # cols are teams 0,1
    rosters = {1: [0], 2: [1], 3: [], 4: [], 5: [], 6: []}
    assert pwin(rosters, wins, 1) == 1.0
    assert pwin(rosters, wins, 2) == 1.0

def test_pwin_strict_winner():
    wins = np.array([[5, 1], [5, 1]], dtype=np.int16)
    rosters = {1: [0], 2: [1], 3: [], 4: [], 5: [], 6: []}
    assert pwin(rosters, wins, 1) == 1.0
    assert pwin(rosters, wins, 2) == 0.0

def test_greedy_picks_highest_win_team_when_alone():
    # team 2 wins most in every sim; an empty-roster player should grab it
    wins = np.array([[1, 2, 9], [0, 3, 8]], dtype=np.int16)
    st = DraftState(my_player=1, n_teams=3)
    assert greedy_pick(st, wins, 1) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_draft.py -v`
Expected: FAIL (`ModuleNotFoundError: winspool.draft`).

- [ ] **Step 3: Write the implementation**

```python
# src/winspool/draft.py
import numpy as np
from .teams import N_TEAMS, N_PLAYERS, N_PICKS

# Fixed "optimized" order: player picking at each of the 30 picks (1-indexed players).
PICK_ORDER = [1, 2, 3, 4, 5, 6, 5, 6, 4, 6, 3, 1, 4, 2, 5,
              2, 3, 5, 3, 1, 6, 2, 1, 4, 3, 2, 4, 5, 6, 1]
assert len(PICK_ORDER) == N_PICKS

class DraftState:
    def __init__(self, my_player, picks=None, n_teams=N_TEAMS):
        self.my_player = my_player
        self.n_teams = n_teams
        self.picks = list(picks) if picks else []  # list[(player, team_idx)]

    def drafted(self):
        return {t for _, t in self.picks}

    def board(self):
        drafted = self.drafted()
        return [i for i in range(self.n_teams) if i not in drafted]

    def rosters(self):
        r = {p: [] for p in range(1, N_PLAYERS + 1)}
        for p, t in self.picks:
            r[p].append(t)
        return r

    @property
    def done(self):
        return len(self.picks) >= N_PICKS

    @property
    def current_player(self):
        return None if self.done else PICK_ORDER[len(self.picks)]

    def apply_pick(self, team_idx):
        if self.done:
            raise RuntimeError("draft is complete")
        self.picks.append((self.current_player, team_idx))

    def copy(self):
        return DraftState(self.my_player, self.picks, self.n_teams)

    def picks_until_my_next(self):
        count = 0
        for i in range(len(self.picks), N_PICKS):
            if PICK_ORDER[i] == self.my_player:
                return count
            count += 1
        return count  # no more picks

def player_totals(rosters, wins):
    n = wins.shape[0]
    totals = np.zeros((n, N_PLAYERS))
    for p, teams in rosters.items():
        if teams:
            totals[:, p - 1] = wins[:, teams].sum(axis=1)
    return totals

def pwin(rosters, wins, player):
    totals = player_totals(rosters, wins)
    rowmax = totals.max(axis=1)
    return float(np.mean(totals[:, player - 1] >= rowmax))

def greedy_pick(state, wins, player):
    # Rank by P(win); break ties by marginal expected wins. Early in a draft
    # most rosters are empty, so many candidates tie on P(win) (everyone is a
    # co-leader under the >= rule) — the marginal-wins tiebreak keeps the choice
    # meaningful and order-independent instead of falling to iteration order.
    best_team, best_key = None, None
    rosters = state.rosters()
    for t in state.board():
        rosters[player].append(t)
        totals = player_totals(rosters, wins)
        col = totals[:, player - 1]
        score = float(np.mean(col >= totals.max(axis=1)))
        mean_wins = float(col.mean())
        rosters[player].pop()
        key = (score, mean_wins)
        if best_key is None or key > best_key:
            best_key, best_team = key, t
    return best_team
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_draft.py -v` → Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/winspool/draft.py tests/test_draft.py
git commit -m "feat: draft state, P(win) objective, greedy pick"
```

---

### Task 6: MVP recommender + CLI (end-to-end runnable)

**Files:**
- Create: `src/winspool/recommend.py`
- Create: `src/winspool/cli.py`
- Test: `tests/test_recommend.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `DraftState`, `pwin`, `player_totals`, `sim.simulate`, `ratings.strength_from_totals`, data loaders.
- Produces:
  - `recommend.naive_recommend(state, wins) -> list[dict]` — one dict per available team `{team, pwin, delta_wins}`, sorted by `pwin` desc. `delta_wins` = mean wins the team adds to my roster.
  - `recommend.build_wins(schedule_path, totals_path, n_seasons, seed) -> tuple[np.ndarray, np.ndarray]` returning `(wins, strengths)`.
  - `cli.main(argv=None) -> int` implementing `winspool recommend --slot N [--taken A,B,...] [--n 20000] [--seed 0]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_recommend.py
import numpy as np
from winspool.draft import DraftState
from winspool.recommend import naive_recommend, build_wins

def test_naive_recommend_ranks_and_covers_board():
    # team 2 dominant, team 0 weak
    wins = np.array([[1, 5, 9], [2, 4, 8], [0, 6, 10]], dtype=np.int16)
    st = DraftState(my_player=1, n_teams=3)
    recs = naive_recommend(st, wins)
    assert [r["team"] for r in recs][0] == 2      # best first
    assert {r["team"] for r in recs} == {0, 1, 2}  # all available teams present
    assert recs[0]["pwin"] >= recs[-1]["pwin"]

def test_build_wins_shapes():
    wins, strengths = build_wins("tests/fixtures/schedule_2026.csv",
                                 "tests/fixtures/win_totals.csv",
                                 n_seasons=500, seed=0)
    from winspool.teams import N_TEAMS
    assert wins.shape == (500, N_TEAMS)
    assert strengths.shape == (N_TEAMS,)
```

```python
# tests/test_cli.py
from winspool.cli import main

def test_cli_recommend_runs(capsys):
    code = main(["recommend", "--slot", "1",
                 "--schedule", "tests/fixtures/schedule_2026.csv",
                 "--totals", "tests/fixtures/win_totals.csv",
                 "--n", "300", "--seed", "0"])
    out = capsys.readouterr().out
    assert code == 0
    assert "pwin" in out.lower()
    # every board team should appear in the printed table
    assert "BUF" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_recommend.py tests/test_cli.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write the implementations**

```python
# src/winspool/recommend.py
import numpy as np
from .data import load_schedule, schedule_matchups, load_win_totals
from .ratings import strength_from_totals
from .sim import simulate
from .draft import player_totals, pwin

def build_wins(schedule_path, totals_path, n_seasons=20000, seed=0):
    df = load_schedule(schedule_path)
    home, away = schedule_matchups(df)
    totals = load_win_totals(totals_path)
    strengths = strength_from_totals(totals)
    sigma = np.full(strengths.size, 6.0)  # MVP: flat preseason uncertainty
    rng = np.random.default_rng(seed)
    wins = simulate(strengths, sigma, home, away, n_seasons, rng=rng)
    return wins, strengths

def naive_recommend(state, wins):
    rosters = state.rosters()
    me = state.my_player
    base_total = player_totals(rosters, wins)[:, me - 1].mean()
    out = []
    for t in state.board():
        rosters[me].append(t)
        score = pwin(rosters, wins, me)
        added = player_totals(rosters, wins)[:, me - 1].mean() - base_total
        rosters[me].pop()
        out.append({"team": t, "pwin": score, "delta_wins": added})
    out.sort(key=lambda r: r["pwin"], reverse=True)
    return out
```

```python
# src/winspool/cli.py
import argparse
from .teams import TEAMS, TEAM_INDEX
from .draft import DraftState, PICK_ORDER
from .recommend import build_wins, naive_recommend

def _apply_taken(state, taken):
    """taken: comma-separated team codes in pick order."""
    if not taken:
        return
    for code in taken.split(","):
        code = code.strip().upper()
        if code:
            state.apply_pick(TEAM_INDEX[code])

def main(argv=None):
    parser = argparse.ArgumentParser(prog="winspool")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("recommend")
    rec.add_argument("--slot", type=int, required=True)
    rec.add_argument("--taken", default="")
    rec.add_argument("--schedule", default="data/cache/schedule_2026.csv")
    rec.add_argument("--totals", default="data/cache/win_totals.csv")
    rec.add_argument("--n", type=int, default=20000)
    rec.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    if args.cmd == "recommend":
        wins, _ = build_wins(args.schedule, args.totals, args.n, args.seed)
        state = DraftState(my_player=args.slot)
        _apply_taken(state, args.taken)
        recs = naive_recommend(state, wins)
        on_clock = state.current_player
        print(f"Slot {args.slot} | on the clock: player {on_clock} | "
              f"your next pick in {state.picks_until_my_next()} picks")
        print(f"{'team':<5}{'pwin':>8}{'dWins':>8}")
        for r in recs[:15]:
            print(f"{TEAMS[r['team']]:<5}{r['pwin']:>8.3f}{r['delta_wins']:>8.2f}")
        return 0
    return 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_recommend.py tests/test_cli.py -v` → Expected: PASS.

- [ ] **Step 5: Commit — MVP milestone reached**

```bash
git add src/winspool/recommend.py src/winspool/cli.py tests/test_recommend.py tests/test_cli.py
git commit -m "feat: MVP naive recommender and CLI (end-to-end runnable)"
```

**Milestone A checkpoint:** after fetching real data (`python scripts/fetch_data.py` and hand-entering `data/cache/win_totals.csv`), `winspool recommend --slot 3` prints a real ranked board. Eyeball it before proceeding.

---

## Milestone B — Calibrated ratings + variance/differentiator analysis (Tasks 7–8)

### Task 7: Market back-out + power-rating blend

**Files:**
- Modify: `src/winspool/ratings.py`
- Create: `tests/fixtures/power_ratings.csv`
- Modify: `src/winspool/data.py` (add `load_power_ratings`)
- Modify: `src/winspool/recommend.py` (use calibrated strengths + per-team sigma)
- Test: `tests/test_ratings.py` (extend), `tests/test_calibration.py`

**Interfaces:**
- Produces:
  - `data.load_power_ratings(path) -> pandas.DataFrame` — every numeric source column, indexed by team code (supports any number of sources, e.g. `fpi, sagarin, massey, elo_*`).
  - `ratings.power_strength(power_df) -> ndarray(32,)` (mean of ALL centered source columns present, points).
  - `ratings.backout_market(win_totals, home_idx, away_idx, *, hfa, scale, iters=60, tol=1e-4) -> ndarray(32,)` — strengths whose `expected_wins` match `win_totals`, mean-centered.
  - `ratings.blend(market, power, w=0.65) -> ndarray(32,)`.
  - `ratings.team_sigma(power_df, base=5.0, disagreement_weight=1.0) -> ndarray(32,)` (preseason SD per team = base + weight·std of the team's source strengths).

- [ ] **Step 1: Write fixture + failing tests**

```csv
# tests/fixtures/power_ratings.csv
team,fpi,sagarin,massey
BUF,6.0,5.5,6.2
NYJ,-4.0,-3.5,-4.5
KC,5.5,6.0,5.0
LV,-3.0,-2.5,-3.5
DAL,1.0,0.5,1.5
PHI,3.0,3.5,2.5
MIA,0.0,0.5,-0.5
```

```python
# tests/test_calibration.py
import numpy as np
from winspool.data import load_schedule, schedule_matchups, load_win_totals
from winspool.ratings import backout_market
from winspool.game import expected_wins, HFA, SCALE

def test_backout_reproduces_posted_totals():
    df = load_schedule("tests/fixtures/schedule_2026.csv")
    home, away = schedule_matchups(df)
    totals = load_win_totals("tests/fixtures/win_totals.csv")
    s = backout_market(totals, home, away, hfa=HFA, scale=SCALE)
    ew = expected_wins(s, home, away)
    # only teams that actually appear in the fixture schedule are constrained
    played = sorted(set(home.tolist()) | set(away.tolist()))
    assert np.allclose(ew[played], totals[played], atol=0.05)
```

```python
# tests/test_ratings.py  (append)
import numpy as np
from winspool.data import load_power_ratings
from winspool.ratings import power_strength, blend, team_sigma

def test_blend_endpoints():
    m = np.array([2.0, -2.0, 0.0]); p = np.array([-1.0, 1.0, 0.0])
    assert np.allclose(blend(m, p, w=1.0), m)
    assert np.allclose(blend(m, p, w=0.0), p)

def test_power_strength_orders_teams():
    df = load_power_ratings("tests/fixtures/power_ratings.csv")
    s = power_strength(df)
    from winspool.teams import TEAM_INDEX
    assert s[TEAM_INDEX["BUF"]] > s[TEAM_INDEX["NYJ"]]

def test_team_sigma_rises_with_disagreement():
    df = load_power_ratings("tests/fixtures/power_ratings.csv")
    sig = team_sigma(df)
    assert (sig > 0).all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_calibration.py tests/test_ratings.py -v`
Expected: FAIL (`load_power_ratings`/`backout_market` undefined).

- [ ] **Step 3: Write the implementations**

```python
# src/winspool/data.py  (append)
def load_power_ratings(path):
    """Return every numeric source column, indexed by team code.
    Any number of source columns is supported (fpi, sagarin, massey, elo_*, ...);
    the blend averages whatever is present."""
    df = pd.read_csv(path).set_index("team")
    return df.select_dtypes("number")
```

```python
# src/winspool/ratings.py  (append)
import pandas as pd
from scipy.optimize import brentq
from .teams import TEAMS, TEAM_INDEX, N_TEAMS
from .game import expected_wins, HFA, SCALE

def power_strength(power_df):
    """Mean of centered source columns. Averages ALL numeric columns present,
    so adding a new Elo/power source needs no code change."""
    cols = list(power_df.columns)
    s = np.zeros(N_TEAMS)
    for col in cols:
        col_arr = np.zeros(N_TEAMS)
        for code, val in power_df[col].items():
            col_arr[TEAM_INDEX[code]] = float(val)
        s += col_arr - col_arr.mean()
    return s / len(cols)

def team_sigma(power_df, base=5.0, disagreement_weight=1.0):
    """Preseason SD per team = base + weight * SD across the team's source values."""
    sig = np.full(N_TEAMS, base)
    for code, row in power_df.iterrows():
        sig[TEAM_INDEX[code]] = base + disagreement_weight * float(
            np.std(row.to_numpy(dtype=float)))
    return sig

def _team_games(home_idx, away_idx, n_teams):
    """For each team: list of (opponent_idx, is_home)."""
    games = {t: [] for t in range(n_teams)}
    for h, a in zip(home_idx, away_idx):
        games[h].append((a, True))
        games[a].append((h, False))
    return games

def backout_market(win_totals, home_idx, away_idx, *, hfa=HFA, scale=SCALE,
                   iters=60, tol=1e-4):
    from scipy.stats import norm
    totals = np.asarray(win_totals, dtype=float)
    n_teams = totals.size
    s = np.zeros(n_teams)
    games = _team_games(home_idx, away_idx, n_teams)

    def team_ew(t, st):
        ew = 0.0
        for opp, is_home in games[t]:
            d = (st - s[opp] + (hfa if is_home else -hfa)) / scale
            ew += norm.cdf(d)
        return ew

    for _ in range(iters):
        max_delta = 0.0
        for t in range(n_teams):
            if not games[t]:
                continue
            target = totals[t]
            f = lambda st: team_ew(t, st) - target
            lo, hi = -40.0, 40.0
            if f(lo) > 0 or f(hi) < 0:
                continue  # target unreachable given opponents; leave as is
            new_s = brentq(f, lo, hi, xtol=1e-4)
            max_delta = max(max_delta, abs(new_s - s[t]))
            s[t] = new_s
        if max_delta < tol:
            break
    return s - s.mean()

def blend(market, power, w=0.65):
    market = np.asarray(market) - np.asarray(market).mean()
    power = np.asarray(power) - np.asarray(power).mean()
    return w * market + (1.0 - w) * power
```

```python
# src/winspool/recommend.py  (modify build_wins)
def build_wins(schedule_path, totals_path, n_seasons=20000, seed=0,
               power_path=None, w=0.65, tie_base=0.003):
    from .data import load_power_ratings
    from .ratings import (backout_market, power_strength, blend, team_sigma,
                          strength_from_totals)
    from .game import HFA, SCALE
    df = load_schedule(schedule_path)
    home, away = schedule_matchups(df)
    totals = load_win_totals(totals_path)
    market = backout_market(totals, home, away, hfa=HFA, scale=SCALE)
    if power_path:
        pdf = load_power_ratings(power_path)
        strengths = blend(market, power_strength(pdf), w=w)
        sigma = team_sigma(pdf)
    else:
        strengths = market
        sigma = np.full(strengths.size, 6.0)
    rng = np.random.default_rng(seed)
    wins = simulate(strengths, sigma, home, away, n_seasons, tie_base=tie_base, rng=rng)
    return wins, strengths
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_calibration.py tests/test_ratings.py -v` → Expected: PASS.
Then full suite: `pytest -v` → Expected: PASS (confirm `test_recommend.py::test_build_wins_shapes` still passes with the new signature).

- [ ] **Step 5: Commit**

```bash
git add src/winspool/ratings.py src/winspool/data.py src/winspool/recommend.py \
        tests/fixtures/power_ratings.csv tests/test_calibration.py tests/test_ratings.py
git commit -m "feat: market back-out calibration + power-rating blend"
```

---

### Task 8: Standalone team attributes (variance/differentiator view)

**Files:**
- Create: `src/winspool/analysis.py`
- Modify: `src/winspool/cli.py` (add `analyze` subcommand)
- Test: `tests/test_analysis.py`

**Interfaces:**
- Produces:
  - `analysis.team_attributes(wins) -> list[dict]` — per team `{team, mean, sd, ceiling, floor}` where `ceiling=P(wins>=12)`, `floor=P(wins<=6)`.
  - `analysis.win_correlation(wins) -> ndarray(32,32)`.
  - `analysis.strength_of_schedule(strengths, home_idx, away_idx) -> ndarray(32,)` (mean opponent strength).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis.py
import numpy as np
from winspool.analysis import team_attributes, win_correlation, strength_of_schedule

def test_attributes_basic():
    wins = np.array([[12, 4], [13, 5], [11, 6]], dtype=np.int16)
    attrs = {a["team"]: a for a in team_attributes(wins)}
    assert attrs[0]["mean"] == 12.0
    assert attrs[0]["ceiling"] > attrs[1]["ceiling"]   # team 0 hits >=12 often
    assert attrs[1]["floor"] > attrs[0]["floor"]       # team 1 low-win often

def test_division_rivals_negatively_correlated():
    # teams that only play each other are perfectly anti-correlated in wins
    from winspool.sim import simulate
    home = np.array([0, 1]); away = np.array([1, 0])
    wins = simulate(np.zeros(2), np.zeros(2), home, away, 5000, hfa=0.0,
                    rng=np.random.default_rng(0))
    c = win_correlation(wins)
    assert c[0, 1] < 0

def test_sos_higher_for_tougher_schedule():
    strengths = np.array([0.0, 5.0, -5.0])
    # team 0 plays team1(+5) twice; team 2 plays team? make team0 face strong
    home = np.array([0, 0]); away = np.array([1, 1])
    sos = strength_of_schedule(strengths, home, away)
    assert sos[0] == 5.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analysis.py -v`
Expected: FAIL (`ModuleNotFoundError: winspool.analysis`).

- [ ] **Step 3: Write the implementation**

```python
# src/winspool/analysis.py
import numpy as np

def team_attributes(wins, ceiling_at=12, floor_at=6):
    n_teams = wins.shape[1]
    out = []
    for t in range(n_teams):
        col = wins[:, t]
        out.append({
            "team": t,
            "mean": float(col.mean()),
            "sd": float(col.std()),
            "ceiling": float(np.mean(col >= ceiling_at)),
            "floor": float(np.mean(col <= floor_at)),
        })
    return out

def win_correlation(wins):
    return np.corrcoef(wins.T)

def strength_of_schedule(strengths, home_idx, away_idx):
    strengths = np.asarray(strengths, dtype=float)
    n_teams = strengths.size
    opp_sum = np.zeros(n_teams)
    opp_cnt = np.zeros(n_teams)
    for h, a in zip(home_idx, away_idx):
        opp_sum[h] += strengths[a]; opp_cnt[h] += 1
        opp_sum[a] += strengths[h]; opp_cnt[a] += 1
    with np.errstate(invalid="ignore"):
        return np.where(opp_cnt > 0, opp_sum / opp_cnt, 0.0)
```

```python
# src/winspool/cli.py  (add analyze subcommand: register in main())
# In main(), after building `rec` parser, add:
#     ana = sub.add_parser("analyze")
#     ana.add_argument("--schedule", default="data/cache/schedule_2026.csv")
#     ana.add_argument("--totals", default="data/cache/win_totals.csv")
#     ana.add_argument("--power", default=None)
#     ana.add_argument("--n", type=int, default=20000)
#     ana.add_argument("--seed", type=int, default=0)
# and handle it:
#     if args.cmd == "analyze":
#         from .analysis import team_attributes
#         wins, _ = build_wins(args.schedule, args.totals, args.n, args.seed,
#                              power_path=args.power)
#         attrs = sorted(team_attributes(wins), key=lambda a: a["mean"], reverse=True)
#         print(f"{'team':<5}{'mean':>7}{'sd':>7}{'ceil':>7}{'floor':>7}")
#         for a in attrs:
#             print(f"{TEAMS[a['team']]:<5}{a['mean']:>7.2f}{a['sd']:>7.2f}"
#                   f"{a['ceiling']:>7.3f}{a['floor']:>7.3f}")
#         return 0
```

(Implement the two snippets above as real code in `cli.py`, mirroring the `recommend` branch.)

- [ ] **Step 4: Run tests, then a manual eyeball**

Run: `pytest tests/test_analysis.py -v` → Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/winspool/analysis.py src/winspool/cli.py tests/test_analysis.py
git commit -m "feat: standalone team attributes (variance/ceiling/floor/SOS)"
```

---

## Milestone C — Opponent-aware rollout recommender (Tasks 9–10)

### Task 9: Opponent policies

**Files:**
- Create: `src/winspool/opponents.py`
- Test: `tests/test_opponents.py`

**Interfaces:**
- A `Policy` is a callable `(state: DraftState, player: int, rng) -> int` returning an available team index.
- Produces:
  - `opponents.chalk_power(strengths) -> Policy` — always picks the highest-strength available team.
  - `opponents.entropy(strengths, temperature=8.0) -> Policy` — samples a board team with prob ∝ softmax(strength/temperature). High temperature → near-uniform (chaotic). This is the default live opponent model; `temperature` is the "chalkiness" knob (lower = chalkier).
  - `opponents.greedy_self(wins) -> Policy` — picks `greedy_pick(state, wins, player)` (used for my own seat in rollouts/mock).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_opponents.py
import numpy as np
from winspool.draft import DraftState
from winspool.opponents import chalk_power, entropy, greedy_self

def test_chalk_takes_strongest_available():
    strengths = np.array([1.0, 9.0, 3.0])
    pol = chalk_power(strengths)
    st = DraftState(my_player=1, n_teams=3)
    assert pol(st, 1, np.random.default_rng(0)) == 1  # team 1 strongest

def test_chalk_skips_taken():
    strengths = np.array([1.0, 9.0, 3.0])
    st = DraftState(my_player=1, n_teams=3); st.apply_pick(1)  # strongest gone
    assert chalk_power(strengths)(st, 2, np.random.default_rng(0)) == 2

def test_entropy_returns_available_and_is_seed_deterministic():
    strengths = np.array([1.0, 2.0, 3.0, 4.0])
    pol = entropy(strengths, temperature=8.0)
    st = DraftState(my_player=1, n_teams=4)
    a = pol(st, 1, np.random.default_rng(5))
    b = pol(st, 1, np.random.default_rng(5))
    assert a == b and a in st.board()

def test_low_temperature_is_chalky():
    strengths = np.array([0.0, 0.0, 0.0, 20.0])
    pol = entropy(strengths, temperature=0.5)
    st = DraftState(my_player=1, n_teams=4)
    picks = [pol(st, 1, np.random.default_rng(s)) for s in range(50)]
    assert picks.count(3) > 40  # team 3 dominates at low temp
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_opponents.py -v`
Expected: FAIL (`ModuleNotFoundError: winspool.opponents`).

- [ ] **Step 3: Write the implementation**

```python
# src/winspool/opponents.py
import numpy as np
from .draft import greedy_pick

def chalk_power(strengths):
    strengths = np.asarray(strengths, dtype=float)
    def policy(state, player, rng):
        board = state.board()
        return max(board, key=lambda t: strengths[t])
    return policy

def entropy(strengths, temperature=8.0):
    strengths = np.asarray(strengths, dtype=float)
    def policy(state, player, rng):
        board = np.array(state.board())
        z = strengths[board] / temperature
        z -= z.max()
        p = np.exp(z); p /= p.sum()
        return int(rng.choice(board, p=p))
    return policy

def greedy_self(wins):
    def policy(state, player, rng):
        return greedy_pick(state, wins, player)
    return policy
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_opponents.py -v` → Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/winspool/opponents.py tests/test_opponents.py
git commit -m "feat: pluggable opponent policies (chalk, entropy, greedy-self)"
```

---

### Task 10: Rollout recommender

**Files:**
- Modify: `src/winspool/recommend.py` (add `rollout_recommend`)
- Modify: `src/winspool/cli.py` (recommend uses rollout when `--rollouts > 0`)
- Test: `tests/test_rollout.py`

**Interfaces:**
- Produces:
  - `recommend.playout(state, wins, self_policy, opp_policy, rng) -> DraftState` — advances a copy of `state` to completion using `self_policy` for `state.my_player` and `opp_policy` for everyone else.
  - `recommend.rollout_recommend(state, wins, self_policy, opp_policy, *, n_rollouts=300, rng) -> list[dict]` — for each available team, tentatively take it now, then average `pwin(me)` over `n_rollouts` playouts; returns `{team, pwin, survival}` sorted by `pwin` desc. `survival` = fraction of playouts (without pre-taking t) in which t is still on the board at my next pick.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rollout.py
import numpy as np
from winspool.draft import DraftState
from winspool.opponents import chalk_power, entropy, greedy_self
from winspool.recommend import playout, rollout_recommend

def _wins():
    # 6 teams, cols 0..5; team win totals descend so ordering is clear
    rng = np.random.default_rng(0)
    base = np.array([13, 11, 10, 8, 6, 4], dtype=float)
    return (base[None, :] + rng.normal(0, 2, (4000, 6))).round().clip(0, 17).astype(np.int16)

def test_playout_fills_all_picks_capped_to_board():
    wins = _wins()
    st = DraftState(my_player=1, n_teams=6)
    # only 6 teams exist, so a 30-pick order can't fully run; playout must stop at board exhaustion
    final = playout(st, wins, greedy_self(wins), chalk_power(np.arange(6)[::-1]),
                    np.random.default_rng(1))
    drafted = final.drafted()
    assert len(drafted) == 6  # all teams taken, no duplicates
    assert len(drafted) == len(set(drafted))

def test_rollout_returns_sorted_survival_bounded():
    wins = _wins()
    st = DraftState(my_player=1, n_teams=6)
    recs = rollout_recommend(st, wins, greedy_self(wins),
                             entropy(np.arange(6)[::-1], temperature=8.0),
                             n_rollouts=40, rng=np.random.default_rng(2))
    assert {r["team"] for r in recs} == set(range(6))
    assert 0.0 <= recs[0]["survival"] <= 1.0
    assert recs == sorted(recs, key=lambda r: r["pwin"], reverse=True)
```

Note: the 6-team fixture forces `playout` to handle board exhaustion (fewer teams than the 30-pick order). Guard for it in the implementation.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rollout.py -v`
Expected: FAIL (`playout`/`rollout_recommend` undefined).

- [ ] **Step 3: Write the implementation**

```python
# src/winspool/recommend.py  (append)
from .draft import pwin, PICK_ORDER, greedy_pick

def playout(state, wins, self_policy, opp_policy, rng):
    st = state.copy()
    while not st.done and st.board():
        player = st.current_player
        pol = self_policy if player == st.my_player else opp_policy
        st.apply_pick(pol(st, player, rng))
    return st

def rollout_recommend(state, wins, self_policy, opp_policy, *, n_rollouts=300, rng):
    me = state.my_player
    board = state.board()

    # survival: how often each team lasts to my next pick if I DON'T take it now
    until = state.picks_until_my_next()
    survive = {t: 0 for t in board}
    for _ in range(n_rollouts):
        st = state.copy()
        steps = 0
        while steps < until and not st.done and st.board():
            player = st.current_player
            pol = self_policy if player == me else opp_policy
            st.apply_pick(pol(st, player, rng))
            steps += 1
        still_up = set(st.board())
        for t in board:
            if t in still_up:
                survive[t] += 1

    out = []
    for t in board:
        scores = []
        for _ in range(n_rollouts):
            st = state.copy()
            st.apply_pick(t)  # take candidate now (as me)
            final = playout(st, wins, self_policy, opp_policy, rng)
            scores.append(pwin(final.rosters(), wins, me))
        out.append({"team": t, "pwin": float(np.mean(scores)),
                    "survival": survive[t] / n_rollouts})
    out.sort(key=lambda r: r["pwin"], reverse=True)
    return out
```

Also update `cli.py` `recommend` branch: add `rec.add_argument("--rollouts", type=int, default=0)` and, when `args.rollouts > 0`, build `entropy(strengths, temperature=args.temp)` opp policy + `greedy_self(wins)` self policy and call `rollout_recommend(...)`, printing the `survival` column; otherwise keep `naive_recommend`. Add `rec.add_argument("--temp", type=float, default=8.0)` and thread `strengths` out of `build_wins` (already returned).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rollout.py -v` → Expected: PASS. Then `pytest -v` (full suite) → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/winspool/recommend.py src/winspool/cli.py tests/test_rollout.py
git commit -m "feat: opponent-aware rollout recommender with survival probabilities"
```

---

## Milestone D — Mock-draft harness (Task 11)

### Task 11: Positional-value study + auto/practice draft

**Files:**
- Create: `src/winspool/mock.py`
- Modify: `src/winspool/cli.py` (add `positional` subcommand)
- Test: `tests/test_mock.py`

**Interfaces:**
- Produces:
  - `mock.auto_draft(wins, policies: dict[int, Policy], my_player, rng) -> DraftState` — runs a full draft; `policies[p]` drives seat `p`.
  - `mock.positional_study(wins, self_policy, opp_policy, *, k=200, rng) -> dict[int, float]` — for each slot 1–6, run `k` auto-drafts with me in that slot (opponents share `opp_policy`), return mean `pwin` by slot.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mock.py
import numpy as np
from winspool.opponents import chalk_power, entropy, greedy_self
from winspool.mock import auto_draft, positional_study

def _wins():
    rng = np.random.default_rng(0)
    base = np.linspace(12, 4, 32)
    return (base[None, :] + rng.normal(0, 2, (3000, 32))).round().clip(0, 17).astype(np.int16)

def test_auto_draft_completes_full_board():
    wins = _wins()
    strengths = np.linspace(12, 4, 32)
    pols = {p: entropy(strengths, 8.0) for p in range(1, 7)}
    pols[1] = greedy_self(wins)
    final = auto_draft(wins, pols, my_player=1, rng=np.random.default_rng(1))
    assert len(final.picks) == 30
    assert len(final.drafted()) == 30  # no duplicates

def test_positional_study_returns_all_slots():
    wins = _wins()
    strengths = np.linspace(12, 4, 32)
    res = positional_study(wins, greedy_self(wins), entropy(strengths, 8.0),
                           k=15, rng=np.random.default_rng(3))
    assert set(res) == {1, 2, 3, 4, 5, 6}
    assert all(0.0 <= v <= 1.0 for v in res.values())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mock.py -v`
Expected: FAIL (`ModuleNotFoundError: winspool.mock`).

- [ ] **Step 3: Write the implementation**

```python
# src/winspool/mock.py
import numpy as np
from .draft import DraftState, pwin

def auto_draft(wins, policies, my_player, rng):
    st = DraftState(my_player=my_player)
    while not st.done and st.board():
        player = st.current_player
        st.apply_pick(policies[player](st, player, rng))
    return st

def positional_study(wins, self_policy, opp_policy, *, k=200, rng):
    results = {}
    for slot in range(1, 7):
        pols = {p: opp_policy for p in range(1, 7)}
        pols[slot] = self_policy
        total = 0.0
        for _ in range(k):
            final = auto_draft(wins, pols, my_player=slot, rng=rng)
            total += pwin(final.rosters(), wins, slot)
        results[slot] = total / k
    return results
```

Also add a `positional` subcommand to `cli.py` that builds `wins, strengths`, runs `positional_study(wins, greedy_self(wins), entropy(strengths, temp), k=args.k, rng=...)`, and prints P(win) by slot sorted descending — the answer to "which draft slot is best for me."

- [ ] **Step 4: Run tests, then full suite**

Run: `pytest tests/test_mock.py -v` → Expected: PASS.
Run: `pytest -v` → Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/winspool/mock.py src/winspool/cli.py tests/test_mock.py
git commit -m "feat: mock-draft harness (positional study + auto draft)"
```

---

## Milestone E — Multi-source data ingestion pipeline (Tasks 12–13)

Refreshable scrape/fetch layer that populates the cache CSVs the model reads. The model
never changes when sources are added. Testable offline: all *logic* (name resolution,
multi-source aggregation) is unit-tested with fixtures/fake sources; only the thin network
fetchers in `registry.py` require a live smoke test (documented, not unit-tested).

### Task 12: Team-name resolver + rating-table parsers

**Files:**
- Modify: `src/winspool/teams.py` (add `TEAM_NAMES`, `resolve`)
- Create: `src/winspool/fetch/__init__.py`
- Create: `src/winspool/fetch/parsers.py`
- Create: `tests/fixtures/power_table.csv`
- Test: `tests/test_parsers.py`

**Interfaces:**
- Produces:
  - `teams.TEAM_NAMES: dict[str,str]` (code → full name).
  - `teams.resolve(name: str) -> str | None` — map a code / nickname / full name (case-insensitive) to a canonical code; `None` if unresolvable.
  - `parsers.parse_rating_table(rows: list[dict], name_key, value_key) -> dict[str,float]` — resolve each row's team, coerce value to float, silently skip unresolved rows and non-numeric values.
  - `parsers.parse_csv_ratings(text: str, name_col, value_col) -> dict[str,float]` — parse CSV text then `parse_rating_table`.

- [ ] **Step 1: Write fixture + failing tests**

```csv
# tests/fixtures/power_table.csv
name,rating
Kansas City Chiefs,6.0
Buffalo Bills,6.5
Not A Real Team,9.9
```

```python
# tests/test_parsers.py
from winspool.teams import resolve
from winspool.fetch.parsers import parse_rating_table, parse_csv_ratings

def test_resolve_code_nickname_and_full_name():
    assert resolve("KC") == "KC"
    assert resolve("chiefs") == "KC"
    assert resolve("Kansas City Chiefs") == "KC"
    assert resolve("  Buffalo Bills ") == "BUF"

def test_resolve_unknown_is_none():
    assert resolve("Not A Real Team") is None
    assert resolve("") is None

def test_parse_rating_table_resolves_and_skips_unknown():
    rows = [{"name": "Chiefs", "r": "6.0"},
            {"name": "Bogus", "r": "1.0"},
            {"name": "Bills", "r": "not_a_number"}]
    out = parse_rating_table(rows, "name", "r")
    assert out == {"KC": 6.0}  # Bogus skipped (unresolved), Bills skipped (bad value)

def test_parse_csv_ratings_from_text():
    text = open("tests/fixtures/power_table.csv").read()
    out = parse_csv_ratings(text, "name", "rating")
    assert out == {"KC": 6.0, "BUF": 6.5}  # bogus row dropped
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_parsers.py -v`
Expected: FAIL (`resolve`/`winspool.fetch` undefined).

- [ ] **Step 3: Write the implementation**

```python
# src/winspool/teams.py  (append)
TEAM_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers",
    "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
    "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
}

_ALIASES = {}
for _code, _full in TEAM_NAMES.items():
    _ALIASES[_code.lower()] = _code
    _ALIASES[_full.lower()] = _code
    _ALIASES[_full.split()[-1].lower()] = _code  # nickname (last word)

def resolve(name):
    if not name:
        return None
    key = str(name).strip().lower()
    if key.upper() in TEAM_INDEX:
        return key.upper()
    return _ALIASES.get(key)
```

```python
# src/winspool/fetch/__init__.py
# (empty; package marker)
```

```python
# src/winspool/fetch/parsers.py
import csv
import io
from ..teams import resolve

def parse_rating_table(rows, name_key, value_key):
    out = {}
    for row in rows:
        code = resolve(row.get(name_key, ""))
        if code is None:
            continue
        try:
            out[code] = float(row[value_key])
        except (TypeError, ValueError, KeyError):
            continue
    return out

def parse_csv_ratings(text, name_col, value_col):
    reader = csv.DictReader(io.StringIO(text))
    return parse_rating_table(list(reader), name_col, value_col)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_parsers.py -v` → Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/winspool/teams.py src/winspool/fetch/__init__.py src/winspool/fetch/parsers.py \
        tests/fixtures/power_table.csv tests/test_parsers.py
git commit -m "feat: team-name resolver and rating-table parsers"
```

---

### Task 13: Fetch orchestration + refresh CLI

**Files:**
- Create: `src/winspool/fetch/pipeline.py`
- Create: `src/winspool/fetch/registry.py`
- Modify: `src/winspool/cli.py` (add `fetch` subcommand)
- Test: `tests/test_fetch_pipeline.py`

**Interfaces:**
- Produces:
  - `pipeline.Source(name: str, kind: str, fetch: Callable[[], dict[str,float]])` — `kind` is `"totals"` or `"power"`; `fetch()` returns `{team_code: value}`.
  - `pipeline.refresh(sources, cache_dir, now="unknown") -> list[dict]` — fetches every source; writes `win_totals.csv` (mean across all `totals` sources, columns `team,win_total`), `power_ratings.csv` (one column per `power` source, plus `team`), and `sources_meta.json` (provenance list); returns the meta list. Raises `ValueError` on an unknown `kind`.
  - `registry.http_json(url)`, `registry.http_text(url)` — stdlib `urllib` helpers (no `requests` dependency).
  - `registry.default_sources(config: dict) -> list[Source]` — builds network Sources from a config dict (API keys / URLs). **Network; not unit-tested — verify with a live smoke test.**

**Consumes:** `parsers.parse_csv_ratings`, `teams.resolve`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fetch_pipeline.py
import json
import pandas as pd
import pytest
from winspool.fetch.pipeline import Source, refresh

def test_refresh_aggregates_totals_and_columns_power(tmp_path):
    srcs = [
        Source("book_a", "totals", lambda: {"BUF": 11.0, "KC": 10.0}),
        Source("book_b", "totals", lambda: {"BUF": 12.0, "KC": 10.0}),
        Source("fpi", "power", lambda: {"BUF": 6.0, "KC": 5.0}),
        Source("sagarin", "power", lambda: {"BUF": 6.5, "KC": 4.5}),
    ]
    meta = refresh(srcs, str(tmp_path), now="2026-08-20")

    wt = pd.read_csv(tmp_path / "win_totals.csv").set_index("team")["win_total"]
    assert wt["BUF"] == 11.5 and wt["KC"] == 10.0      # mean across books

    pr = pd.read_csv(tmp_path / "power_ratings.csv").set_index("team")
    assert set(pr.columns) == {"fpi", "sagarin"}       # one column per power source
    assert pr.loc["BUF", "fpi"] == 6.0

    assert {m["name"] for m in meta} == {"book_a", "book_b", "fpi", "sagarin"}
    saved = json.load(open(tmp_path / "sources_meta.json"))
    assert all(m["fetched_at"] == "2026-08-20" for m in saved)

def test_refresh_rejects_unknown_kind(tmp_path):
    with pytest.raises(ValueError):
        refresh([Source("x", "weird", lambda: {"BUF": 1.0})], str(tmp_path))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fetch_pipeline.py -v`
Expected: FAIL (`winspool.fetch.pipeline` undefined).

- [ ] **Step 3: Write the implementation**

```python
# src/winspool/fetch/pipeline.py
import json
import os
from dataclasses import dataclass
from typing import Callable
import pandas as pd

@dataclass
class Source:
    name: str
    kind: str  # "totals" | "power"
    fetch: Callable[[], dict]

def refresh(sources, cache_dir, now="unknown"):
    os.makedirs(cache_dir, exist_ok=True)
    totals_cols, power_cols, meta = {}, {}, []
    for s in sources:
        if s.kind not in ("totals", "power"):
            raise ValueError(f"unknown source kind: {s.kind!r}")
        data = s.fetch()
        meta.append({"name": s.name, "kind": s.kind,
                     "n_teams": len(data), "fetched_at": now})
        (totals_cols if s.kind == "totals" else power_cols)[s.name] = data
    if totals_cols:
        win_total = pd.DataFrame(totals_cols).mean(axis=1)
        (win_total.rename("win_total").rename_axis("team").reset_index()
         .to_csv(os.path.join(cache_dir, "win_totals.csv"), index=False))
    if power_cols:
        (pd.DataFrame(power_cols).rename_axis("team").reset_index()
         .to_csv(os.path.join(cache_dir, "power_ratings.csv"), index=False))
    with open(os.path.join(cache_dir, "sources_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    return meta
```

```python
# src/winspool/fetch/registry.py
"""Concrete network data sources.

NOTE: These perform live HTTP and depend on external endpoints/schemas that
change. They are NOT unit-tested. Before relying on them, run a smoke test:
    python -c "from winspool.fetch.registry import default_sources; \
               print([(s.name, len(s.fetch())) for s in default_sources(CONFIG)])"
and confirm each source returns ~32 teams. Add a new source by writing a
fetch function that returns {team_code: value} and appending a Source here."""
import json
import urllib.request
from .pipeline import Source
from .parsers import parse_csv_ratings, parse_rating_table

def http_text(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def http_json(url, timeout=30):
    return json.loads(http_text(url, timeout))

def _odds_api_totals(api_key):
    """Season win totals from The Odds API. Returns {code: mean point across books}.
    Endpoint/market key must be confirmed live; shape assumed:
    [{"home_team": <name>, "bookmakers":[{"markets":[
        {"key":"team_totals","outcomes":[{"name":<team>,"point":<wins>}]}]}]}]"""
    url = (f"https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
           f"?regions=us&markets=team_totals&apiKey={api_key}")
    payload = http_json(url)
    from collections import defaultdict
    from ..teams import resolve
    pts = defaultdict(list)
    for event in payload:
        for book in event.get("bookmakers", []):
            for market in book.get("markets", []):
                for o in market.get("outcomes", []):
                    code = resolve(o.get("name", ""))
                    if code is not None and "point" in o:
                        pts[code].append(float(o["point"]))
    return {code: sum(v) / len(v) for code, v in pts.items() if v}

def _csv_power(url, name_col, value_col):
    return parse_csv_ratings(http_text(url), name_col, value_col)

def default_sources(config):
    """Build sources from config, e.g.
    {"odds_api_key": "...",
     "power_csv": [{"name":"sagarin","url":"...","name_col":"team","value_col":"rating"}]}.
    Missing/blank config entries are skipped so a partial config still runs."""
    sources = []
    if config.get("odds_api_key"):
        key = config["odds_api_key"]
        sources.append(Source("odds_api", "totals", lambda: _odds_api_totals(key)))
    for spec in config.get("power_csv", []):
        sources.append(Source(
            spec["name"], "power",
            lambda spec=spec: _csv_power(spec["url"], spec["name_col"], spec["value_col"])))
    return sources
```

```python
# src/winspool/cli.py  (add fetch subcommand)
# Register in main():
#     fet = sub.add_parser("fetch")
#     fet.add_argument("--config", default="data/cache/sources.json")
#     fet.add_argument("--cache", default="data/cache")
# Handle it:
#     if args.cmd == "fetch":
#         import json, datetime
#         from .fetch.registry import default_sources
#         from .fetch.pipeline import refresh
#         with open(args.config) as f:
#             config = json.load(f)
#         sources = default_sources(config)
#         if not sources:
#             print("No sources configured. See src/winspool/fetch/registry.py.")
#             return 1
#         now = datetime.datetime.now().isoformat(timespec="seconds")
#         meta = refresh(sources, args.cache, now=now)
#         for m in meta:
#             print(f"{m['name']:<12}{m['kind']:<8}{m['n_teams']} teams  @ {m['fetched_at']}")
#         return 0
```

(Implement the `fetch` branch in `cli.py` as real code mirroring the existing `recommend` branch.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fetch_pipeline.py -v` → Expected: PASS.
Then full suite: `pytest -v` → Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/winspool/fetch/pipeline.py src/winspool/fetch/registry.py \
        src/winspool/cli.py tests/test_fetch_pipeline.py
git commit -m "feat: multi-source data ingestion pipeline + fetch CLI"
```

**Milestone E note:** the ingestion *logic* is fully tested offline. The live fetchers in
`registry.py` need a one-time network smoke test (command in the module docstring) to
confirm each endpoint still returns ~32 teams before the pre-draft refresh.

---

## Self-Review (spec coverage)

- Draft order / fixed pattern → Task 5 `PICK_ORDER` (validated against the spec table).
- Winner-take-all P(1st), ties as co-champion → Task 5 `pwin` (`>= rowmax`).
- NFL tie games = 0 wins, small rate → Task 4 `tie_base` mechanism; Task 7 enables it (`tie_base=0.003`).
- Data layer (schedule, Vegas, power) free/cached → Tasks 2, 7 + `scripts/fetch_data.py`.
- Multi-source refreshable ingestion (more win/Elo sources, re-run before draft) → Tasks 12–13 (`winspool fetch`, extensible source registry, provenance in `sources_meta.json`).
- Ratings blend market+power, `w≈0.65`, calibration back-out → Task 7.
- Preseason strength draw, per-team σ → Task 4 (`sigma` draw), Task 7 (`team_sigma`).
- Monte Carlo N×32 matrix, game-by-game, correlation emerges → Task 4; correlation surfaced Task 8.
- Differentiator view (SD/ceiling/floor/SOS for market-equal teams) → Task 8.
- Draft brain: marginal P(win), rollout, survival, opponent model, chalkiness knob → Tasks 9–10.
- Interpretable Δwins / survival columns → Tasks 6 (Δwins), 10 (survival). (Δσ and correlation-with-roster columns deferred to a Plan-2 enrichment; noted as a gap below.)
- Mock harness: positional study + practice → Task 11 (positional + `auto_draft`; interactive practice-draft loop is a thin Plan-2/CLI addition over `auto_draft`).

**Known deferrals (intentional, not gaps in MVP correctness):** per-candidate Δσ and correlation-with-my-current-roster columns, and the interactive (human-in-the-loop) practice draft, are left for Plan 2 where the API/UI makes them useful; the underlying data (win matrix, correlation, `auto_draft`) is all in place.

## Handoff

After Task 11, Plan 1 delivers a working, tested draft recommender + positional study runnable from the CLI on real data. Plan 2 (FastAPI) and Plan 3 (React) build the live-draft UI on top.
