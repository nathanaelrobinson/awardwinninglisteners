# Ratings Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace seven mostly-frozen rating sources with five live ones, stored as structured append-only rows in SQLite, fetched on a schedule by the Pi, with a commissioner-only panel showing whether the pipeline is healthy.

**Architecture:** Ratings move from cached CSVs to a `ratings` table shaped exactly like the existing odds log. Two of the five voices are computed by us — an opponent-adjusted EPA (ridge regression over play-by-play) and a market strength vector (least squares over every closing spread in the odds log). Three are fetched (ESPN FPI, Kalshi season market, covers). `recommend._assemble_sources` is the single loader boundary; it gains a store-backed path guarded by an exact-equivalence test against the file-backed path.

**Tech Stack:** Python 3.12, numpy/pandas/scipy, `nfl_data_py`, `requests`, SQLite, FastAPI, React 18 + TypeScript, pytest, systemd timers on a Raspberry Pi.

**Spec:** `docs/superpowers/specs/2026-09-10-ratings-pipeline-design.md`

## Global Constraints

- **Only live sources predict.** PFF, Clay, betmgm and nfelo are removed from the ensemble entirely — deleted, not faded. A source that cannot be kept current does not get to predict.
- **No browser dependency ships to the Pi.** No playwright, no chromium. If a source needs one, it is out.
- **The ratings table is append-only.** A failed fetch writes a row with `ok = 0` and its error; an absent row and a failed fetch must stay distinguishable.
- **The equivalence property is load-bearing:** the store-backed loader must produce *identical* team strengths to the file-backed loader given the same data. Exact, not approximate. If that test cannot pass, stop and report — do not weaken it.
- **Test budget: 8 new test functions total across the whole plan**, allocated per task below. This project is under a standing test-reduction order; the suite is 353 and must not balloon. Never write a test that only asserts a key exists or a type is returned.
- **Run the suite with plain `uv run pytest -q`.** Do NOT pass `-m` on the command line: it REPLACES the marker expression in `addopts` rather than intersecting with it, which silently re-admits tests that call live third-party endpoints.
- **Never touch the live host.** No ssh, no systemctl, no deploy. Deployment is a human action.
- **Never push.** Commit on the working branch only.

---

### Task 1: The `ratings` table

**Files:**
- Modify: `src/winspool/store.py` — `Store` protocol, `InMemoryStore`, `SqliteStore`
- Modify: `src/winspool/cli.py` — export/import payloads
- Test: `tests/test_store_ratings.py`

**Interfaces:**
- Consumes: nothing.
- Produces, on both stores:
  - `add_rating(self, row: dict) -> str`
  - `put_rating(self, row: dict) -> None` (import path, preserves `id`)
  - `latest_ratings(self) -> dict[str, dict]` — newest row per source **where `ok` is true**
  - `ratings_history(self, source: str) -> list[dict]` — oldest first
  - `all_ratings(self) -> list[dict]` — export, oldest first

A row is `{"id", "source", "kind", "fetched_at", "ok", "doc"}` where `kind` is `"power" | "totals" | "distribution"` and `doc` is `{team: value}` for power/totals, `{team: [pmf floats]}` for distribution, or `{"error": "..."}` when `ok` is false.

- [ ] **Step 1: Write the failing test** — `tests/test_store_ratings.py`, **2 test functions, which is this task's entire budget**:

```python
import pytest

from winspool.store import InMemoryStore, SqliteStore


def _row(source, fetched_at, ok=True, value=1.0):
    doc = {"KC": value, "BUF": -value} if ok else {"error": "boom"}
    return {"source": source, "kind": "power", "fetched_at": fetched_at,
            "ok": ok, "doc": doc}


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    return InMemoryStore({}) if request.param == "memory" else SqliteStore(tmp_path / "t.db")


def test_latest_is_the_newest_ok_row_per_source(store):
    store.add_rating(_row("espn_fpi", 100.0, value=1.0))
    store.add_rating(_row("espn_fpi", 200.0, value=2.0))     # newer, wins
    store.add_rating(_row("espn_fpi", 300.0, ok=False))      # newest but failed
    store.add_rating(_row("kalshi", 150.0, value=9.0))

    latest = store.latest_ratings()
    assert set(latest) == {"espn_fpi", "kalshi"}
    # the failed row must NOT mask the last good one — that is the whole point
    assert latest["espn_fpi"]["doc"]["KC"] == 2.0
    assert latest["espn_fpi"]["fetched_at"] == 200.0
    # ...and the failure is still recorded, distinguishable from never having run
    hist = store.ratings_history("espn_fpi")
    assert [r["fetched_at"] for r in hist] == [100.0, 200.0, 300.0]
    assert hist[-1]["ok"] is False and hist[-1]["doc"]["error"] == "boom"


def test_rows_are_appended_never_replaced_and_survive_a_round_trip(store, tmp_path):
    first = store.add_rating(_row("epa_adj", 100.0, value=1.0))
    store.add_rating(_row("epa_adj", 200.0, value=2.0))
    kept = next(r for r in store.ratings_history("epa_adj") if r["id"] == first)
    assert kept["doc"]["KC"] == 1.0            # the earlier row is untouched

    dst = SqliteStore(tmp_path / "dst.db")
    for row in store.all_ratings():
        dst.put_rating(row)
    assert [r["id"] for r in dst.ratings_history("epa_adj")] == \
           [r["id"] for r in store.ratings_history("epa_adj")]
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/test_store_ratings.py -q`
Expected: FAIL, `AttributeError: 'InMemoryStore' object has no attribute 'add_rating'`

- [ ] **Step 3: Add the five methods to the `Store` protocol**

In `src/winspool/store.py`, in `class Store(Protocol)`, after the odds methods:

```python
    def add_rating(self, row: dict) -> str: ...
    def put_rating(self, row: dict) -> None: ...
    def latest_ratings(self) -> dict[str, dict]: ...
    def ratings_history(self, source: str) -> list[dict]: ...
    def all_ratings(self) -> list[dict]: ...
```

- [ ] **Step 4: Implement on `InMemoryStore`**

Add `self._ratings: list[dict] = []` to `__init__`, then:

```python
    def add_rating(self, row: dict) -> str:
        r = {**row, "id": row.get("id") or uuid.uuid4().hex}
        self._ratings.append(r)
        return r["id"]

    def put_rating(self, row: dict) -> None:
        self._ratings = [r for r in self._ratings if r["id"] != row["id"]]
        self._ratings.append(dict(row))

    def latest_ratings(self) -> dict[str, dict]:
        best: dict[str, dict] = {}
        for r in sorted(self._ratings, key=lambda r: r["fetched_at"]):
            if r["ok"]:
                best[r["source"]] = r
        return best

    def ratings_history(self, source: str) -> list[dict]:
        rows = [r for r in self._ratings if r["source"] == source]
        return sorted(rows, key=lambda r: r["fetched_at"])

    def all_ratings(self) -> list[dict]:
        return sorted(self._ratings, key=lambda r: r["fetched_at"])
```

- [ ] **Step 5: Implement on `SqliteStore`**

Append to `SCHEMA`:

```sql
    CREATE TABLE IF NOT EXISTS ratings (id TEXT PRIMARY KEY, source TEXT NOT NULL,
                                        kind TEXT NOT NULL, fetched_at REAL NOT NULL,
                                        ok INTEGER NOT NULL, doc TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ratings_source_time ON ratings(source, fetched_at);
```

Then the methods, matching how the odds methods in the same class guard writes with `self._lock`:

```python
    # --- ratings (append only) ---

    def add_rating(self, row: dict) -> str:
        r = {**row, "id": row.get("id") or uuid.uuid4().hex}
        self.put_rating(r)
        return r["id"]

    def put_rating(self, row: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO ratings (id, source, kind, fetched_at, ok, doc) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (row["id"], row["source"], row["kind"], float(row["fetched_at"]),
                 1 if row["ok"] else 0, json.dumps(row["doc"])))

    def _rating_rows(self, sql: str, args=()) -> list[dict]:
        rows = self._db.execute(sql, args).fetchall()
        return [{"id": r[0], "source": r[1], "kind": r[2], "fetched_at": r[3],
                 "ok": bool(r[4]), "doc": json.loads(r[5])} for r in rows]

    def latest_ratings(self) -> dict[str, dict]:
        best: dict[str, dict] = {}
        for r in self._rating_rows(
                "SELECT id, source, kind, fetched_at, ok, doc FROM ratings "
                "WHERE ok=1 ORDER BY fetched_at, rowid"):
            best[r["source"]] = r
        return best

    def ratings_history(self, source: str) -> list[dict]:
        return self._rating_rows(
            "SELECT id, source, kind, fetched_at, ok, doc FROM ratings "
            "WHERE source=? ORDER BY fetched_at, rowid", (source,))

    def all_ratings(self) -> list[dict]:
        return self._rating_rows(
            "SELECT id, source, kind, fetched_at, ok, doc FROM ratings "
            "ORDER BY fetched_at, rowid")
```

- [ ] **Step 6: Carry ratings through export/import**

In `src/winspool/cli.py`, add `"ratings": store.all_ratings(),` to the export payload and extend its summary print with `f"{len(payload['ratings'])} ratings, "`. In the import path, after the odds loop:

```python
        for row in payload.get("ratings") or []:
            store.put_rating(row)
```

and extend that summary print the same way. There is an existing test asserting the exact export key set — find it (`grep -rn "expected_keys" tests/`) and add `"ratings"` to it.

- [ ] **Step 7: Run and commit**

```bash
uv run pytest -q
git add src/winspool/store.py src/winspool/cli.py tests/test_store_ratings.py tests/test_export_import.py
git commit -m "feat(store): append-only ratings table"
```

---

### Task 2: Remove the dead sources

**Files:**
- Modify: `src/winspool/fetch/registry.py`
- Modify: `pyproject.toml` — drop `playwright` and `pdfplumber`
- Modify: `src/winspool/fetch/scrapers.py` — delete the fetchers that are now unreachable
- Modify: `tests/test_scrapers.py`, `tests/test_fetch_pipeline.py` — remove tests for deleted code

**Interfaces:**
- Produces: `default_sources()` returning exactly `covers` (totals) and `espn_fpi` (power).

**Test budget: 0 new tests.** This task only deletes; existing tests are trimmed to match.

- [ ] **Step 1: Trim the registry**

`src/winspool/fetch/registry.py`'s `default_sources()` becomes:

```python
def default_sources(config=None):
    """Only sources that can be kept current. A forecast that cannot change is
    not evidence about a season in progress, so preseason artifacts (PFF's news
    article, Clay's PDF, betmgm's blog post) are gone, and nfelo is gone with
    the headless browser it needed."""
    return [
        Source("covers", "totals", covers_totals),
        Source("espn_fpi", "power", espn_fpi),
    ]
```

Update the module docstring, which currently lists sources that no longer exist.

- [ ] **Step 2: Delete the unreachable fetchers**

From `src/winspool/fetch/scrapers.py`, delete `betmgm_totals`, `nfelo_power`, `parse_nfelo`, `_render`, `clay_projections`, `parse_clay_page`, `pff_projections`, `parse_pff`, and the constants only they used (`BETMGM_URL`, `NFELO_URL`, `ELO_PER_POINT`, `CLAY_URL`, `PFF_URL`, `_PFF_FIX`). Leave `epa_from_pbp` and `epa_ratings` — Task 3 rewrites them.

- [ ] **Step 3: Drop the dependencies**

In `pyproject.toml` remove `"playwright"` and `"pdfplumber"` from the dependency list, then:

```bash
uv lock && uv sync --extra dev
```

Commit the updated `uv.lock`.

- [ ] **Step 4: Trim the tests**

Run `uv run pytest -q` and delete every test that referenced the removed functions. Report which you deleted and why in your report — this reduces the suite, which is desirable.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest -q
git add -A && git commit -m "feat(fetch): keep only sources that can be kept current"
```

---

### Task 3: Opponent-adjusted, in-season EPA

**Files:**
- Modify: `src/winspool/fetch/scrapers.py` — replace `epa_from_pbp` and `epa_ratings`
- Test: `tests/test_epa_adjusted.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `epa_adjusted(pbp: pd.DataFrame, ridge: float = 1.0) -> dict[str, float]`
  - `epa_ratings() -> dict[str, float]` — same public shape as today

**Test budget: 2 test functions.**

- [ ] **Step 1: Write the failing test** — `tests/test_epa_adjusted.py`:

```python
import numpy as np
import pandas as pd
import pytest

from winspool.fetch.scrapers import EPA_SHRINK_K, epa_adjusted, shrink_weight


def _pbp(rows):
    """rows: (posteam, defteam, epa) triples, one per play."""
    return pd.DataFrame(
        [{"posteam": o, "defteam": d, "epa": e, "pass": 1, "rush": 0} for o, d, e in rows])


def test_opponent_adjustment_separates_a_good_offence_from_a_weak_schedule():
    # KC and BUF both average +0.30 EPA/play. KC did it against DEN, whose
    # defence is terrible; BUF did it against SEA, whose defence is strong.
    # An unadjusted mean rates them equal; opponent adjustment must rate BUF
    # higher. Extra plays pin the two defences relative to each other.
    rows = []
    rows += [("KC", "DEN", 0.30)] * 40
    rows += [("BUF", "SEA", 0.30)] * 40
    rows += [("SEA", "DEN", 0.60)] * 40      # DEN's defence bleeds against everyone
    rows += [("DEN", "SEA", 0.00)] * 40      # SEA's defence holds everyone
    out = epa_adjusted(_pbp(rows), ridge=0.01)
    assert out["BUF"] > out["KC"], f"expected BUF above KC, got {out}"


def test_shrinkage_moves_from_last_season_to_this_one_as_plays_accumulate():
    assert shrink_weight(0) == 0.0
    assert shrink_weight(EPA_SHRINK_K) == pytest.approx(0.5)
    assert shrink_weight(10 ** 9) > 0.99
    # week 1 of a season is a few hundred plays: this season must barely count
    assert shrink_weight(166) < 0.05
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/test_epa_adjusted.py -q`
Expected: FAIL, `ImportError: cannot import name 'epa_adjusted'`

- [ ] **Step 3: Implement**

In `src/winspool/fetch/scrapers.py`, replace `epa_from_pbp`/`epa_ratings` with:

```python
EPA_SEASONS = (2026, 2025)      # (current, prior) — current is shrunk toward prior
EPA_POINTS_SCALE = 50.0         # net EPA/play -> rough points scale
EPA_SHRINK_K = 8000             # plays at which this season and last count equally
EPA_RIDGE = 1.0                 # regularises the near-singular early-season system


def shrink_weight(n_plays: int, k: int = EPA_SHRINK_K) -> float:
    """How much this season counts against last. Week 1 is a few hundred plays,
    so this season barely registers; by midseason it dominates. An unstable
    voice is worse than a lagging one when only four voices exist."""
    return float(n_plays) / (float(n_plays) + float(k))


def epa_adjusted(pbp, ridge: float = EPA_RIDGE) -> dict:
    """Opponent-adjusted net EPA per team, as a mean-centered points strength.

    A plain mean of offensive EPA minus defensive EPA allowed flatters a team
    that has faced weak opponents. Regressing play-level EPA on offence-team and
    defence-team indicators separates the two: the fitted coefficients are what
    a team did *given who it played*. This is what DVOA provides and we cannot
    buy."""
    if "pass" in pbp.columns and "rush" in pbp.columns:
        pbp = pbp[(pbp["pass"] == 1) | (pbp["rush"] == 1)]
    p = pbp.dropna(subset=["epa", "posteam", "defteam"])
    if not len(p):
        return {}

    off_codes = [resolve(str(t)) for t in p["posteam"]]
    def_codes = [resolve(str(t)) for t in p["defteam"]]
    keep = [i for i, (o, d) in enumerate(zip(off_codes, def_codes))
            if o is not None and d is not None]
    if not keep:
        return {}
    y = p["epa"].to_numpy(dtype=float)[keep]
    teams = sorted({off_codes[i] for i in keep} | {def_codes[i] for i in keep})
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    # One column per team's offence, one per its defence.
    X = np.zeros((len(keep), 2 * n))
    for r, i in enumerate(keep):
        X[r, idx[off_codes[i]]] = 1.0
        X[r, n + idx[def_codes[i]]] = 1.0

    # Ridge: (X'X + λI)β = X'y. λ keeps the system solvable in September, when a
    # team has faced one or two opponents and the columns are near-collinear.
    A = X.T @ X + ridge * np.eye(2 * n)
    beta = np.linalg.solve(A, X.T @ y)
    net = {t: float(beta[idx[t]] - beta[n + idx[t]]) for t in teams}
    mean = sum(net.values()) / len(net)
    return {t: (v - mean) * EPA_POINTS_SCALE for t, v in net.items()}


def epa_ratings():
    """Opponent-adjusted efficiency from nflverse play-by-play (free), this
    season shrunk toward last so September is not driven by one game."""
    import nfl_data_py as nfl
    cur, prior = EPA_SEASONS

    def _load(year):
        try:
            df = nfl.import_pbp_data([year], downcast=True)
            return df if len(df) else None
        except Exception:
            return None

    cur_pbp, prior_pbp = _load(cur), _load(prior)
    cur_out = epa_adjusted(cur_pbp) if cur_pbp is not None else {}
    prior_out = epa_adjusted(prior_pbp) if prior_pbp is not None else {}
    if not cur_out:
        return prior_out
    if not prior_out:
        return cur_out
    w = shrink_weight(len(cur_pbp))
    return {t: w * cur_out.get(t, 0.0) + (1 - w) * prior_out.get(t, 0.0)
            for t in set(cur_out) | set(prior_out)}
```

Ensure `numpy as np` and `resolve` are imported in that module (`resolve` already is).

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/test_epa_adjusted.py -q && uv run pytest -q
git add src/winspool/fetch/scrapers.py tests/test_epa_adjusted.py
git commit -m "feat(epa): opponent-adjusted, in-season, shrunk toward last year"
```

---

### Task 4: Market strength from the odds log

**Files:**
- Create: `src/winspool/marketstrength.py`
- Test: `tests/test_market_strength.py`

**Interfaces:**
- Consumes: `store.odds_for_week(season, week)` (exists), `gameodds.GameOdds`/`to_prob` (exist), `game.HFA`/`SCALE` (exist).
- Produces:
  - `closing_spreads(store, season, weeks) -> list[tuple[str, str, float, int]]` — `(home, away, spread, week)`, spread home-favoured-negative, one per game, from the last read before that game's kickoff
  - `strength_from_spreads(games, current_week, half_life=HALF_LIFE_WEEKS, ridge=RIDGE) -> dict[str, float]`

**Test budget: 2 test functions.**

- [ ] **Step 1: Write the failing test** — `tests/test_market_strength.py`:

```python
import pytest

from winspool.marketstrength import HALF_LIFE_WEEKS, strength_from_spreads


def test_it_recovers_the_strengths_that_generated_the_spreads():
    # True strengths, in points. A spread is s_away - s_home - HFA, i.e. the
    # home-favoured-negative convention, so we generate from known values and
    # check the solve inverts it.
    true = {"KC": 6.0, "BUF": 3.0, "DEN": -3.0, "SEA": -6.0}
    from winspool.game import HFA
    games = []
    for h in true:
        for a in true:
            if h != a:
                games.append((h, a, true[a] - true[h] - HFA, 1))
    got = strength_from_spreads(games, current_week=2, ridge=1e-6)
    # recovered up to a shared additive constant, so compare centered
    c_true = {t: v - sum(true.values()) / len(true) for t, v in true.items()}
    c_got = {t: v - sum(got.values()) / len(got) for t, v in got.items()}
    for t in true:
        assert c_got[t] == pytest.approx(c_true[t], abs=0.05), f"{t}: {c_got} vs {c_true}"


def test_recent_weeks_outweigh_old_ones():
    from winspool.game import HFA
    # KC was 7 points better than BUF long ago, and 7 points worse last week.
    old = [("KC", "BUF", -7.0 - HFA, 1)] * 3
    recent = [("BUF", "KC", -7.0 - HFA, 9)] * 3
    got = strength_from_spreads(old + recent, current_week=10,
                                half_life=HALF_LIFE_WEEKS, ridge=1e-6)
    assert got["BUF"] > got["KC"], "the recent result must dominate"
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/test_market_strength.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'winspool.marketstrength'`

- [ ] **Step 3: Implement** — create `src/winspool/marketstrength.py`:

```python
"""Team strength inverted from every closing spread we have recorded.

Per-game odds used to do one job — set this week's win probabilities — while
the odds log accumulated more of them every hour. But a spread is a direct
measurement of the difference between two teams, so a season of them
over-determines all 32 strengths. Opponent adjustment is automatic here: the
system is nothing but relative comparisons.
"""
import numpy as np

from .game import HFA
from .gameodds import GameOdds, to_prob
from .teams import resolve

HALF_LIFE_WEEKS = 4.0   # a spread this old counts half as much as last week's
RIDGE = 1e-3            # keeps September solvable, when games < teams
SOURCE_ORDER = ("book", "nflverse", "kalshi")


def _spread_from(o: GameOdds) -> float | None:
    """A spread for this source, home-favoured-negative. Kalshi quotes no
    spread, so its price is converted through the same normal the rest of the
    model uses."""
    if o.spread is not None:
        return float(o.spread)
    p = to_prob(o)
    if p is None or not 0.0 < p < 1.0:
        return None
    from scipy.stats import norm
    from .game import SCALE
    return float(-norm.ppf(p) * SCALE)


def closing_spreads(store, season: int, weeks) -> list:
    """(home, away, spread, week) per game, from the last read before kickoff.

    The odds log's retention pass preserves that closing read specifically
    because it must never be thinned away; this is the thing it was preserved
    for."""
    out = []
    for week in weeks:
        rows = store.odds_for_week(season, week)
        best: dict[tuple, dict] = {}          # (home, away) -> {source: GameOdds}
        for row in sorted(rows, key=lambda r: float(r.get("fetched_at") or 0.0)):
            if row["source"] == "model":
                continue
            for g in row.get("games") or []:
                home, away = resolve(g["home"]), resolve(g["away"])
                if not home or not away:
                    continue
                best.setdefault((home, away), {})[row["source"]] = GameOdds(
                    source=row["source"], home=home, away=away,
                    fetched_at=float(row.get("fetched_at") or 0.0),
                    spread=g.get("spread"), total=g.get("total"),
                    ml_home=g.get("ml_home"), ml_away=g.get("ml_away"),
                    yes_home=g.get("yes_home"), yes_away=g.get("yes_away"))
        for (home, away), by_source in best.items():
            for name in SOURCE_ORDER:
                if name in by_source:
                    s = _spread_from(by_source[name])
                    if s is not None:
                        out.append((home, away, s, week))
                        break
    return out


def strength_from_spreads(games, current_week: int,
                          half_life: float = HALF_LIFE_WEEKS,
                          ridge: float = RIDGE) -> dict:
    """Least squares over `spread = s_away - s_home - HFA`, weighted by recency.

    Strength drifts across a season, so a week-1 spread should not count as much
    as last week's. Returns {} when there is nothing to solve."""
    games = [g for g in games if g[2] is not None]
    if not games:
        return {}
    teams = sorted({t for h, a, _s, _w in games for t in (h, a)})
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    X = np.zeros((len(games), n))
    y = np.zeros(len(games))
    w = np.zeros(len(games))
    for r, (home, away, spread, week) in enumerate(games):
        X[r, idx[away]] = 1.0
        X[r, idx[home]] = -1.0
        y[r] = float(spread) + HFA
        w[r] = 0.5 ** (max(0, current_week - week) / half_life)

    W = np.diag(w)
    A = X.T @ W @ X + ridge * np.eye(n)
    beta = np.linalg.solve(A, X.T @ W @ y)
    beta -= beta.mean()                       # strengths are relative
    return {t: float(beta[idx[t]]) for t in teams}
```

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/test_market_strength.py -q && uv run pytest -q
git add src/winspool/marketstrength.py tests/test_market_strength.py
git commit -m "feat(ratings): invert team strength from the closing-spread log"
```

---

### Task 5: The ratings refresh job and its endpoint

**Files:**
- Create: `src/winspool/ratingsjob.py`
- Modify: `src/winspool/api_league.py` — new internal endpoint
- Create: `deploy/pi/winspool-ratings.service`, `deploy/pi/winspool-ratings.timer`
- Test: `tests/test_ratingsjob.py`

**Interfaces:**
- Consumes: `store.add_rating`, `fetch.registry.default_sources`, `fetch.kalshi` season fetch, `fetch.scrapers.epa_ratings`, `marketstrength.{closing_spreads, strength_from_spreads}`.
- Produces:
  - `MAX_AGE_S: dict[str, float]` — per-source staleness limit
  - `refresh_ratings(store, *, season, week, sources=None, now=None) -> dict` returning `{"written": {source: n_teams}, "errors": {source: msg}}`
  - `stale(store, now=None) -> dict[str, float]` — source → age in seconds, for any source past its limit

**Test budget: 1 test function.**

- [ ] **Step 1: Write the failing test** — `tests/test_ratingsjob.py`:

```python
from winspool.ratingsjob import MAX_AGE_S, refresh_ratings, stale
from winspool.store import InMemoryStore


def test_a_failing_source_is_recorded_without_masking_the_last_good_one():
    store = InMemoryStore({})

    def ok(season, week):
        return {"KC": 5.0, "BUF": 2.0}

    def boom(season, week):
        raise RuntimeError("espn is down")

    out = refresh_ratings(store, season=2026, week=3,
                          sources={"espn_fpi": ("power", ok)}, now=100.0)
    assert out["written"] == {"espn_fpi": 2} and out["errors"] == {}

    out = refresh_ratings(store, season=2026, week=4,
                          sources={"espn_fpi": ("power", boom)}, now=200.0)
    assert "espn is down" in out["errors"]["espn_fpi"]
    assert out["written"] == {}

    # the good row still stands, and the failure is visible in history
    latest = store.latest_ratings()
    assert latest["espn_fpi"]["doc"]["KC"] == 5.0
    assert [r["ok"] for r in store.ratings_history("espn_fpi")] == [True, False]

    # ...and the source is now stale, because its last SUCCESS is old
    aged = stale(store, now=100.0 + MAX_AGE_S["espn_fpi"] + 1)
    assert "espn_fpi" in aged
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/test_ratingsjob.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'winspool.ratingsjob'`

- [ ] **Step 3: Implement** — create `src/winspool/ratingsjob.py`:

```python
"""Fetch every live rating source and append what it said.

A source that fails leaves its last good row in place rather than dropping out
of the ensemble — the old CSV pipeline wrote one column per source that
succeeded, so a dead scraper silently changed what the model was. Per-source
rows remove that class of bug. Staleness is surfaced instead, and makes the
health check fail rather than the model quietly age.
"""
import time

DAY = 86400.0

# A source past this age has not merely blipped — something is wrong and the
# ensemble is drifting on stale information. These make the endpoint 503.
MAX_AGE_S = {
    "espn_fpi": 10 * DAY,        # weekly
    "kalshi": 2 * DAY,           # daily
    "covers": 2 * DAY,           # daily
    "epa_adj": 10 * DAY,         # weekly
    "market_strength": 10 * DAY,  # weekly
}

KIND = {"espn_fpi": "power", "kalshi": "distribution", "covers": "totals",
        "epa_adj": "power", "market_strength": "power"}


def default_sources() -> dict:
    """{name: (kind, fn(season, week) -> {team: value})}. Kept as a function so
    a caller — or a test — can substitute one without touching the others."""
    from .fetch.scrapers import covers_totals, epa_ratings, espn_fpi
    from .fetch.kalshi import kalshi_distributions
    from .marketstrength import closing_spreads, strength_from_spreads

    def _market(season, week):
        games = closing_spreads(None, season, range(1, max(1, week)))
        return strength_from_spreads(games, current_week=week)

    return {
        "espn_fpi": ("power", lambda s, w: espn_fpi()),
        "covers": ("totals", lambda s, w: covers_totals()),
        "kalshi": ("distribution", lambda s, w: kalshi_distributions()),
        "epa_adj": ("power", lambda s, w: epa_ratings()),
        "market_strength": ("power", _market),
    }


def refresh_ratings(store, *, season: int, week: int, sources=None,
                    now: float | None = None) -> dict:
    stamp = now if now is not None else time.time()
    src = default_sources() if sources is None else sources
    written, errors = {}, {}
    for name, (kind, fn) in src.items():
        try:
            doc = fn(season, week)
        except Exception as e:                    # noqa: BLE001 - recorded, not raised
            errors[name] = f"{type(e).__name__}: {e}"[:200]
            store.add_rating({"source": name, "kind": kind, "fetched_at": stamp,
                              "ok": False, "doc": {"error": errors[name]}})
            continue
        if not doc:
            errors[name] = "empty result"
            store.add_rating({"source": name, "kind": kind, "fetched_at": stamp,
                              "ok": False, "doc": {"error": "empty result"}})
            continue
        store.add_rating({"source": name, "kind": kind, "fetched_at": stamp,
                          "ok": True, "doc": doc})
        written[name] = len(doc)
    return {"season": int(season), "week": int(week),
            "written": written, "errors": errors}


def stale(store, now: float | None = None) -> dict:
    """{source: age_seconds} for every source whose last SUCCESS is past its
    limit. A source that has never succeeded counts as infinitely stale."""
    stamp = now if now is not None else time.time()
    latest = store.latest_ratings()
    out = {}
    for name, limit in MAX_AGE_S.items():
        row = latest.get(name)
        age = float("inf") if row is None else stamp - float(row["fetched_at"])
        if age > limit:
            out[name] = age
    return out
```

Note the `_market` closure takes `None` for the store; wire the real store in Step 4 by binding it — change `default_sources()` to `default_sources(store)` and pass `store` through from `refresh_ratings`.

- [ ] **Step 4: Bind the store into the market source**

Change the signature to `def default_sources(store) -> dict:` and `_market` to use it:

```python
    def _market(season, week):
        games = closing_spreads(store, season, range(1, max(1, week)))
        return strength_from_spreads(games, current_week=week)
```

and in `refresh_ratings`, `src = default_sources(store) if sources is None else sources`.

- [ ] **Step 5: Add the endpoint**

In `src/winspool/api_league.py`, add `from . import ratingsjob as _ratingsjob` and, beside the other internal endpoints:

```python
@router.post("/internal/refresh-ratings", include_in_schema=False)
def internal_refresh_ratings(x_refresh_token: str | None = Header(default=None)):
    _check_refresh_token(x_refresh_token)
    store = get_store()
    try:
        df = _live._load_schedule_cached()
        out = _ratingsjob.refresh_ratings(store, season=SEASON,
                                          week=_live.week_of(df))
    except Exception as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(e)[:200]})
    aged = _ratingsjob.stale(store)
    # A stale source means the ensemble is drifting on old information. Fail
    # loudly so the systemd unit goes red, but keep what DID land.
    if out["errors"] or aged:
        return JSONResponse(status_code=503, content={
            "ok": False, **out, "stale": {k: round(v) for k, v in aged.items()}})
    return {"ok": True, **out}
```

- [ ] **Step 6: The systemd units**

Create `deploy/pi/winspool-ratings.service`, matching `winspool-odds.service` exactly in structure. **Note it must NOT use `--retry`**: this POST appends to a log, so retrying a 503 would write duplicate rows.

```ini
[Unit]
Description=Refresh the live rating sources
After=winspool.service
Requires=winspool.service

[Service]
Type=oneshot
TimeoutStartSec=1800
EnvironmentFile=/etc/winspool/env
ExecStart=/usr/bin/curl -fsS --max-time 1500 \
    -X POST -H "X-Refresh-Token: ${REFRESH_TOKEN}" \
    http://127.0.0.1:8080/internal/refresh-ratings
```

The long timeout is for the play-by-play download, which is the slowest thing the Pi does.

Create `deploy/pi/winspool-ratings.timer`, declaring `Unit=` explicitly the way its neighbours do:

```ini
[Unit]
Description=winspool ratings refresh (daily 05:40)

[Timer]
OnCalendar=*-*-* 05:40:00
Persistent=true
Unit=winspool-ratings.service

[Install]
WantedBy=timers.target
```

Daily at 05:40 covers the daily sources; the weekly ones simply return the same numbers on days they have not published, which costs one cheap fetch. 05:40 avoids the backup at 03:30 and the odds snapshot at :20 past.

`scripts/pi-deploy.sh` already installs and enables every timer in `deploy/pi/` by glob, so no script change is needed.

- [ ] **Step 7: Run and commit**

```bash
uv run pytest -q
git add src/winspool/ratingsjob.py src/winspool/api_league.py deploy/pi/winspool-ratings.* tests/test_ratingsjob.py
git commit -m "feat(ratings): scheduled refresh job, loud on staleness"
```

---

### Task 6: Store-backed loading, and the equivalence property

This is the task the whole plan turns on. These inputs feed the number five people use to settle a season-long bet.

**Files:**
- Modify: `src/winspool/data.py` — store-backed loaders
- Modify: `src/winspool/recommend.py` — `_assemble_sources` gains a store path
- Test: `tests/test_ratings_equivalence.py`

**Interfaces:**
- Consumes: `store.latest_ratings()` from Task 1.
- Produces:
  - `data.sources_from_store(store) -> tuple[dict, np.ndarray]`. Values are either a strength array (`kind == "power"`) or the marker tuple `("__totals__", arr)` for totals/distribution sources, which the caller resolves through `backout_market` because only it knows the schedule. Task 6 Step 5 does that resolution.
  - `recommend._assemble_sources(totals_path, power_path, home, away, kalshi_dist_path, store=None)` — when `store` is given it is used and the paths are ignored

**Test budget: 1 test function — the golden one.**

- [ ] **Step 1: Write the failing test** — `tests/test_ratings_equivalence.py`:

```python
import numpy as np
import pandas as pd

from winspool.recommend import _assemble_sources
from winspool.store import InMemoryStore

FIX = "tests/fixtures"


def test_the_store_path_reproduces_the_file_path_exactly():
    """The load-bearing property of the whole ratings migration.

    Same numbers in, identical strengths out — exactly, not approximately.
    If this cannot pass, the store-backed loader is wrong and the migration
    stops."""
    sched = pd.read_csv(f"{FIX}/schedule_2026.csv")
    sched = sched[sched["game_type"].str.upper() == "REG"]
    from winspool.teams import TEAM_INDEX
    home = sched["home_team"].map(TEAM_INDEX).to_numpy(dtype=int)
    away = sched["away_team"].map(TEAM_INDEX).to_numpy(dtype=int)

    from_files, sd_files = _assemble_sources(
        f"{FIX}/win_totals.csv", f"{FIX}/power_ratings.csv", home, away, None)

    # Load the same CSVs into a store as ratings rows.
    store = InMemoryStore({})
    totals = pd.read_csv(f"{FIX}/win_totals.csv")
    store.add_rating({"source": "covers", "kind": "totals", "fetched_at": 1.0,
                      "ok": True,
                      "doc": {r["team"]: float(r["win_total"]) for _, r in totals.iterrows()}})
    power = pd.read_csv(f"{FIX}/power_ratings.csv").set_index("team")
    for col in power.select_dtypes("number").columns:
        store.add_rating({"source": col, "kind": "power", "fetched_at": 1.0,
                          "ok": True,
                          "doc": {c: float(v) for c, v in power[col].items()}})

    from_store, sd_store = _assemble_sources(None, None, home, away, None, store=store)

    # The file path names the totals voice "vegas"; the store names it by its
    # source. Compare the strength vectors, which is what the model consumes.
    assert set(from_store) == {"covers"} | set(power.select_dtypes("number").columns)
    np.testing.assert_array_equal(from_store["covers"], from_files["vegas"])
    for col in power.select_dtypes("number").columns:
        np.testing.assert_array_equal(from_store[col], from_files[col])
    np.testing.assert_array_equal(sd_store, sd_files)
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/test_ratings_equivalence.py -q`
Expected: FAIL, `TypeError: _assemble_sources() got an unexpected keyword argument 'store'`

- [ ] **Step 3: Add the store-backed loader**

Append to `src/winspool/data.py`:

```python
def sources_from_store(store):
    """({name: strength}, target_sd) from the newest good row per source.

    The file path and this path must produce identical strengths — see
    tests/test_ratings_equivalence.py, which is what makes the migration safe.
    """
    from .game import HFA, SCALE
    from .ratings import backout_market
    latest = store.latest_ratings()
    sources, target_sd = {}, np.full(N_TEAMS, np.nan)
    for name, row in latest.items():
        doc, kind = row["doc"], row["kind"]
        if kind == "power":
            arr = np.zeros(N_TEAMS)
            for code, val in doc.items():
                if code in TEAM_INDEX:
                    arr[TEAM_INDEX[code]] = float(val)
            sources[name] = arr
    return sources, target_sd
```

- [ ] **Step 4: Handle totals and distributions**

Extend the loop, mirroring `_assemble_sources`'s existing arithmetic exactly — including its "teams with no posted number default to the mean of those posted" rule, which the equivalence test will catch if it drifts:

```python
        elif kind == "totals":
            totals = np.full(N_TEAMS, np.nan)
            for code, val in doc.items():
                if code in TEAM_INDEX:
                    totals[TEAM_INDEX[code]] = float(val)
            totals[np.isnan(totals)] = np.nanmean(totals)
            sources[name] = ("__totals__", totals)
        elif kind == "distribution":
            from .fetch.kalshi import pmf_line, pmf_sd
            line = np.full(N_TEAMS, np.nan)
            for code, pmf in doc.items():
                if code in TEAM_INDEX:
                    line[TEAM_INDEX[code]] = pmf_line(np.asarray(pmf, dtype=float))
                    target_sd[TEAM_INDEX[code]] = pmf_sd(np.asarray(pmf, dtype=float))
            line[np.isnan(line)] = np.nanmean(line)
            sources[name] = ("__totals__", line)
```

The `("__totals__", arr)` marker defers `backout_market` to the caller, which is the only place that knows the schedule. Resolve it in `_assemble_sources`.

- [ ] **Step 5: Give `_assemble_sources` the store path**

In `src/winspool/recommend.py`, change the signature to
`def _assemble_sources(totals_path, power_path, home, away, kalshi_dist_path, store=None):`
and make the store path the first branch:

```python
    if store is not None:
        from .data import sources_from_store
        from .ratings import backout_market
        from .game import HFA, SCALE
        raw, target_sd = sources_from_store(store)
        sources = {}
        for name, val in raw.items():
            if isinstance(val, tuple) and val[0] == "__totals__":
                sources[name] = backout_market(val[1], home, away, hfa=HFA, scale=SCALE)
            else:
                sources[name] = val
        return sources, target_sd
```

Everything below it is unchanged, so every existing caller and test keeps working.

- [ ] **Step 6: Run the equivalence test, then the whole suite**

Run: `uv run pytest tests/test_ratings_equivalence.py -q`
Expected: PASS.

**If it fails on a numerical difference, do not loosen the assertion to `assert_allclose`.** An exact mismatch means the two paths disagree about something real — most likely the nan-to-mean fill or the order of operations in `backout_market`. Find it and fix the loader. If you cannot, stop and report rather than shipping an approximate equivalence.

Then `uv run pytest -q`.

- [ ] **Step 7: Commit**

```bash
git add src/winspool/data.py src/winspool/recommend.py tests/test_ratings_equivalence.py
git commit -m "feat(ratings): load sources from the store, proven equivalent to files"
```

---

### Task 7: Prefer the store everywhere, and delete the CSVs

**Files:**
- Modify: `src/winspool/live.py` — `_ensemble`, `source_matrix_for_week`, `refresh_live`
- Modify: `src/winspool/simmodel.py`
- Delete: `data/cache/win_totals.csv`, `data/cache/power_ratings.csv`, `data/cache/kalshi_distributions.csv`, `data/cache/sources_meta.json`
- Modify: `Makefile` — drop the `refresh-ratings` target that commits CSVs

**Test budget: 0 new tests.** The equivalence test from Task 6 is the safety net.

- [ ] **Step 0: Delete `vegas_share`, because its premise is now false**

`live.source_matrix_for_week` scales one source's weight by `vegas_share(week)`,
selected by the literal string `"vegas"`. Two things break here at once, and the
second matters more than the first:

1. Under store-backed naming the totals voice is called `covers`, not `vegas`,
   so the branch `if "vegas" in sources` would simply stop matching. The fade
   would silently stop applying, with nothing to notice it. A rename that
   quietly disables a weighting rule is exactly the failure mode this codebase
   keeps producing.
2. More importantly, **the fade's stated reason is no longer true.** Its
   docstring says "Pre-season win totals stop updating once the season starts,
   so their voice fades linearly from full weight at week 1 to nothing from week
   9." As of this plan, covers win totals are fetched *daily* from a live
   futures market. A source that updates every day should not be discounted for
   being stale.

So remove `vegas_share` and the branch that applies it, rather than re-keying it
to `covers`. Every live source carries equal weight until phase 3's calibration
has evidence to weight them differently.

**This is a deliberate change to the projection**, not a refactor: from week 2
onward the totals voice stops being discounted, so pool-win numbers will move.
That is intended — it was being discounted for a staleness it no longer has.
Note it in the commit message so the change is findable later.

Delete `vegas_share`, delete the `if "vegas" in sources` block in
`source_matrix_for_week`, and delete the test that pins the fade curve
(`grep -n "vegas_share" tests/`).

- [ ] **Step 1: Thread the store through `live._ensemble`**

`_ensemble` currently memoises on the CSV files' mtimes. Replace that key with the newest `fetched_at` across `store.latest_ratings()`, so a refresh invalidates the cache and nothing else does. Pass `store` down from `refresh_live`, which already has it.

- [ ] **Step 2: Same for `simmodel`**

`simmodel.refresh_model` takes a store already; thread it into its `_assemble_sources` call.

- [ ] **Step 3: Keep the CLI working from files**

`winspool recommend` and `winspool analyze` run on a laptop with no store. They keep passing paths, and the path branch of `_assemble_sources` is unchanged, so they need no edits. Verify by running one:

```bash
uv run winspool analyze
```

- [ ] **Step 4: Delete the CSVs**

```bash
git rm data/cache/win_totals.csv data/cache/power_ratings.csv \
       data/cache/kalshi_distributions.csv data/cache/sources_meta.json
```

Keep `tests/fixtures/*.csv` — the equivalence test and the existing model tests read those, and they are fixtures, not live data.

Remove the `refresh-ratings` target from the `Makefile`: it fetched, committed CSVs to a branch and pushed, which is exactly the manual laptop workflow this plan replaces.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest -q
git add -A && git commit -m "feat(ratings): the store is the source of truth"
```

---

### Task 8: `GET /api/admin/health`

**Files:**
- Modify: `src/winspool/api_league.py`
- Test: `tests/test_api_league.py` (extend an existing test — no new function)

**Interfaces:**
- Produces: `GET /api/admin/health`, commissioner-only, returning

```json
{"sources": [{"name": "espn_fpi", "last_ok": 1789..., "age_s": 3600,
              "max_age_s": 864000, "stale": false, "last_error": null}],
 "jobs": [{"name": "live", "at": 1789...}, {"name": "standings", "at": 1789...}]}
```

**Test budget: 0 new test functions** — fold one assertion into an existing commissioner-gating test.

- [ ] **Step 1: Add the route**

```python
@router.get("/api/admin/health")
def admin_health(_: str = Depends(require_commissioner)):
    store = get_store()
    latest = store.latest_ratings()
    now = time.time()
    sources = []
    for name, limit in _ratingsjob.MAX_AGE_S.items():
        row = latest.get(name)
        hist = store.ratings_history(name)
        last_err = next((r["doc"].get("error") for r in reversed(hist)
                         if not r["ok"]), None)
        age = None if row is None else now - float(row["fetched_at"])
        sources.append({"name": name,
                        "last_ok": None if row is None else row["fetched_at"],
                        "age_s": None if age is None else round(age),
                        "max_age_s": limit,
                        "stale": age is None or age > limit,
                        "last_error": last_err})
    live_doc = store.get_live() or {}
    standings = store.get_standings() or {}
    jobs = [{"name": "live", "at": live_doc.get("computed_at")},
            {"name": "standings", "at": standings.get("fetched_at")}]
    return {"sources": sources, "jobs": jobs}
```

Ensure `time` is imported in that module.

- [ ] **Step 2: Extend an existing gating test**

Find the test that asserts a commissioner-only route rejects a non-commissioner (`grep -n "require_commissioner\|commissioner_only" tests/test_api_league.py`) and add `/api/admin/health` to whatever list it exercises. Do not add a new test function.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest -q
git add src/winspool/api_league.py tests/test_api_league.py
git commit -m "feat(api): commissioner-only pipeline health"
```

---

### Task 9: The admin panel

**Files:**
- Create: `web/src/components/Admin.tsx`
- Modify: `web/src/App.tsx` — tab union, tab list, `LABEL`, render block
- Modify: `web/src/league.ts` — `AdminHealth` types and `getAdminHealth()`
- Modify: `web/src/live.css`

**Test budget: 0 tests** — no TypeScript test suite exists.

- [ ] **Step 1: Types and client**

Append to `web/src/league.ts`, following the file's existing conventions:

```ts
export interface AdminSource {
  name: string; last_ok: number | null; age_s: number | null;
  max_age_s: number; stale: boolean; last_error: string | null;
}
export interface AdminJob { name: string; at: number | null }
export interface AdminHealth { sources: AdminSource[]; jobs: AdminJob[] }
export const getAdminHealth = () => call<AdminHealth>('/api/admin/health');
```

- [ ] **Step 2: The component**

One card, a row per source: name, how long ago it last succeeded in human terms ("4h ago", "6d ago"), its limit, and its last error if any. A stale row is tinted with `var(--red)`; a healthy one is plain. Below it, a row per job with its last run.

**This tab is exempt from the game board's terse-copy allow-list.** It is an operator view, and ambiguity costs more here than words do — label things plainly. Reuse `.card` and `.eyebrow`; do not invent a parallel style system.

- [ ] **Step 3: Wire the tab**

Add `'admin'` to the `Tab` union, push it into `tabs` **only when `me?.is_commissioner`** (the same guard the `practice` tab already uses), add `admin: 'Admin'` to `LABEL`, and render it in the same block as the others.

- [ ] **Step 4: Verify**

```bash
cd web && npm run build && npx oxlint src
```

Then run the app and confirm the tab appears for the commissioner and not for anyone else:

```bash
uv run winspool-serve   # PIN 1234 for every player in dev
```

- [ ] **Step 5: Commit**

```bash
git add web/src/components/Admin.tsx web/src/App.tsx web/src/league.ts web/src/live.css
git commit -m "feat(web): commissioner-only admin panel"
```

---

### Task 10: Documentation

**Files:**
- Modify: `README.md`, `docs/pi-runbook.md`

- [ ] **Step 1: README**

Update the Data section: ratings live in SQLite, not `data/cache/`. Remove the `make refresh-ratings` instructions. Add `/internal/refresh-ratings` to the internal-endpoints list with its cadence and what it records. Note that the ensemble is five live sources and say plainly that a source which cannot update is not carried.

- [ ] **Step 2: Runbook**

Add `winspool-ratings.{service,timer}` to the Layout table and the day-to-day commands (`journalctl -u winspool-ratings -n 50`). Note that a 503 from the ratings endpoint means a source failed or is stale, that this is deliberate, and that the panel at the Admin tab says which. Note that an export now carries ratings.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/pi-runbook.md
git commit -m "docs: ratings pipeline"
```
