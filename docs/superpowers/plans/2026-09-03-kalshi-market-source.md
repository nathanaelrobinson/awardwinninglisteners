# Kalshi Market-Implied Win Distributions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Kalshi `KXNFLWINS` as a market-implied data source — full per-team win distribution, a standalone market-view CLI, and the implied line blended into `win_totals` alongside covers.

**Architecture:** A pure ladder→PMF parser (unit-tested against a saved fixture) plus a thin public-API fetcher in `fetch/kalshi.py`. A separate `market.py` consumes the PMF artifact for the independent "market view" (line / mean / SD / independent sampling). The implied line registers as a normal `totals` Source, so it rides the existing `refresh()` blend into `win_totals.csv` and the mixture-of-models sim with **no change to the correlated sim core**.

**Tech Stack:** Python 3.11, `requests`, `numpy`, `pandas`, `pytest`, run via `uv`.

## Global Constraints

- Run everything with `uv run` (e.g. `uv run pytest`, `uv run winspool ...`). Never `pip`/bare `python`.
- Follow the existing pure↔network split: pure parse/compute functions are unit-tested against fixtures; network fetchers get a live smoke test only.
- Team codes resolve via `winspool.teams.resolve`; Kalshi event tickers are `KXNFLWINS-27<CODE>` — strip the leading season digits, then apply `_KALSHI_FIX = {"LAR": "LA", "JAC": "JAX"}` before `resolve`.
- Ladder convention: market `floor_strike = k` means `P(team wins ≥ k)`; price fields are dollar strings (`yes_bid_dollars`, `yes_ask_dollars`, `last_price_dollars`).
- Public endpoint, no auth: `https://external-api.kalshi.com/trade-api/v2/events?series_ticker=KXNFLWINS&with_nested_markets=true&limit=200`.
- Chart/column headers: plain descriptive labels, no editorializing.
- Commit after each task. Branch is `implement-model-core` (never push to main without approval).

---

### Task 1: PMF construction from a ladder (pure)

**Files:**
- Create: `src/winspool/fetch/kalshi.py`
- Test: `tests/test_kalshi.py`
- Fixture (already captured): `tests/fixtures/kalshi_kxnflwins.json` (BUF + ARI events)

**Interfaces:**
- Consumes: nothing (pure numpy).
- Produces:
  - `ladder_to_pmf(markets: list[dict]) -> np.ndarray` — length-18 PMF over wins 0..17, sums to 1.
  - `pmf_mean(pmf) -> float`, `pmf_sd(pmf) -> float`, `pmf_line(pmf) -> float` (interpolated 0.5-CDF crossing).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kalshi.py
import json
import numpy as np
import pytest
from winspool.fetch.kalshi import ladder_to_pmf, pmf_mean, pmf_sd, pmf_line


def _markets(entries):
    # entries: list of (floor_strike, yes_bid, yes_ask) in dollars
    return [{"floor_strike": k, "yes_bid_dollars": str(b),
             "yes_ask_dollars": str(a), "last_price_dollars": None}
            for k, b, a in entries]


def test_ladder_to_pmf_is_normalized_and_nonnegative():
    # simple 3-rung ladder: P(>=1)=1.0, P(>=2)=0.5, P(>=3)=0.0
    pmf = ladder_to_pmf(_markets([(1, 1.0, 1.0), (2, 0.5, 0.5), (3, 0.0, 0.0)]))
    assert pmf.shape == (18,)
    assert pytest.approx(pmf.sum(), abs=1e-9) == 1.0
    assert (pmf >= 0).all()
    # P(W=1) = P>=1 - P>=2 = 0.5 ; P(W=2) = 0.5 ; rest 0
    assert pytest.approx(pmf[1], abs=1e-9) == 0.5
    assert pytest.approx(pmf[2], abs=1e-9) == 0.5


def test_ladder_to_pmf_enforces_monotonic_cdf():
    # deliberately non-monotone: P(>=2) printed HIGHER than P(>=1) (bid/ask noise)
    pmf = ladder_to_pmf(_markets([(1, 0.6, 0.6), (2, 0.8, 0.8), (3, 0.1, 0.1)]))
    assert (pmf >= 0).all()
    assert pytest.approx(pmf.sum(), abs=1e-9) == 1.0


def test_pmf_moments_and_line():
    pmf = ladder_to_pmf(_markets([(1, 1.0, 1.0), (2, 0.5, 0.5), (3, 0.0, 0.0)]))
    assert pytest.approx(pmf_mean(pmf), abs=1e-9) == 1.5   # 0.5*1 + 0.5*2
    assert pmf_sd(pmf) > 0
    # survival P(>=2)=0.5 exactly, so the 0.5-crossing O/U line resolves to 2.0
    assert pytest.approx(pmf_line(pmf), abs=1e-9) == 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kalshi.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'winspool.fetch.kalshi'` / functions not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# src/winspool/fetch/kalshi.py
"""Kalshi KXNFLWINS market source: per-team implied win distributions.

Pure functions (ladder -> PMF, moments) are unit-tested against a fixture.
The network fetchers hit Kalshi's PUBLIC endpoint (no auth) and are smoke-tested.
"""
import numpy as np

MAX_WINS = 17


def _price(m):
    """Usable yes-price for a rung: bid/ask mid when present, else last."""
    def f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    yb, ya, last = f(m.get("yes_bid_dollars")), f(m.get("yes_ask_dollars")), f(m.get("last_price_dollars"))
    if yb is not None and ya is not None and (yb > 0 or ya > 0):
        return (yb + ya) / 2.0
    return last


def ladder_to_pmf(markets):
    """A team's 17-rung ladder -> normalized PMF over wins 0..17 (length 18).

    floor_strike=k prices P(W>=k). We build the survival curve P(W>=k), force it
    non-increasing (cummin) to remove bid/ask crossing noise, then difference it
    into a PMF, clip negatives, and renormalize (removes vig/underround)."""
    surv = np.full(MAX_WINS + 1, np.nan)   # surv[k] = P(W >= k)
    surv[0] = 1.0
    for m in markets:
        k = int(m["floor_strike"])
        p = _price(m)
        if p is not None and 0 <= k <= MAX_WINS:
            surv[k] = p
    # fill gaps by carrying the last known survival value forward
    last = 1.0
    for k in range(MAX_WINS + 1):
        if np.isnan(surv[k]):
            surv[k] = last
        last = surv[k]
    surv = np.minimum.accumulate(surv)     # enforce non-increasing survival
    pmf = np.zeros(MAX_WINS + 1)
    for k in range(MAX_WINS + 1):
        upper = surv[k + 1] if k < MAX_WINS else 0.0
        pmf[k] = max(surv[k] - upper, 0.0)
    total = pmf.sum()
    return pmf / total if total > 0 else pmf


def pmf_mean(pmf):
    k = np.arange(len(pmf))
    return float((k * pmf).sum())


def pmf_sd(pmf):
    k = np.arange(len(pmf))
    mean = float((k * pmf).sum())
    var = float(((k - mean) ** 2 * pmf).sum())
    return float(np.sqrt(max(var, 0.0)))


def pmf_line(pmf):
    """Continuous O/U line: interpolated k where the survival CDF crosses 0.5."""
    surv = 1.0 - np.cumsum(pmf) + pmf      # surv[k] = P(W >= k)
    for k in range(1, len(pmf)):
        if surv[k - 1] >= 0.5 >= surv[k] and surv[k - 1] != surv[k]:
            return float((k - 1) + (surv[k - 1] - 0.5) / (surv[k - 1] - surv[k]))
    return pmf_mean(pmf)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_kalshi.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/winspool/fetch/kalshi.py tests/test_kalshi.py tests/fixtures/kalshi_kxnflwins.json
git commit -m "feat(kalshi): ladder -> normalized win PMF + moments"
```

---

### Task 2: Team-code extraction + fixture-driven parse

**Files:**
- Modify: `src/winspool/fetch/kalshi.py`
- Test: `tests/test_kalshi.py`

**Interfaces:**
- Consumes: `ladder_to_pmf` (Task 1), `winspool.teams.resolve`.
- Produces:
  - `team_from_event_ticker(ticker: str) -> str | None` — `"KXNFLWINS-27BUF"` → `"BUF"`, `"...-27LAR"` → `"LA"`.
  - `events_to_distributions(events: list[dict]) -> dict[str, np.ndarray]` — `{code: pmf}` from a parsed events payload (as returned by the API with `with_nested_markets`).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_kalshi.py
from winspool.fetch.kalshi import team_from_event_ticker, events_to_distributions


def test_team_from_event_ticker_strips_season_and_maps_aliases():
    assert team_from_event_ticker("KXNFLWINS-27BUF") == "BUF"
    assert team_from_event_ticker("KXNFLWINS-27LAR") == "LA"    # Kalshi LAR -> our LA
    assert team_from_event_ticker("KXNFLWINS-27JAC") == "JAX"   # Kalshi JAC -> our JAX
    assert team_from_event_ticker("KXNFLWINS-27ZZZ") is None


def test_events_to_distributions_from_fixture():
    events = json.load(open("tests/fixtures/kalshi_kxnflwins.json"))["events"]
    dists = events_to_distributions(events)
    assert set(dists) == {"BUF", "ARI"}
    for code, pmf in dists.items():
        assert pmf.shape == (18,)
        assert pytest.approx(pmf.sum(), abs=1e-6) == 1.0
    # sanity: BUF (a good team) has a higher implied mean than ARI (a weak team)
    assert pmf_mean(dists["BUF"]) > pmf_mean(dists["ARI"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kalshi.py -k "ticker or fixture" -v`
Expected: FAIL — `team_from_event_ticker` / `events_to_distributions` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/winspool/fetch/kalshi.py (top: add `import re` and the teams import)
import re
from ..teams import resolve

_KALSHI_FIX = {"LAR": "LA", "JAC": "JAX"}


def team_from_event_ticker(ticker):
    raw = re.sub(r"^\d+", "", ticker.split("-")[-1])   # "27BUF" -> "BUF"
    return _KALSHI_FIX.get(raw) or resolve(raw)


def events_to_distributions(events):
    out = {}
    for e in events:
        code = team_from_event_ticker(e.get("event_ticker", ""))
        markets = e.get("markets", [])
        if not code or not markets:
            continue
        pmf = ladder_to_pmf(markets)
        if pmf.sum() > 0:
            out[code] = pmf
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_kalshi.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/winspool/fetch/kalshi.py tests/test_kalshi.py
git commit -m "feat(kalshi): event-ticker team mapping + events->distributions"
```

---

### Task 3: Network fetchers + distribution artifact writer

**Files:**
- Modify: `src/winspool/fetch/kalshi.py`
- Test: `tests/test_kalshi.py`

**Interfaces:**
- Consumes: `events_to_distributions`, `pmf_line` (Tasks 1–2).
- Produces:
  - `fetch_events() -> list[dict]` — one public GET, returns `events` list (network).
  - `kalshi_distributions() -> dict[str, np.ndarray]` (network).
  - `kalshi_totals() -> dict[str, float]` — `{code: pmf_line}`, a `Source`-compatible fetch (network).
  - `write_distributions(dists: dict[str, np.ndarray], cache_dir: str) -> str` — writes `kalshi_distributions.csv` (columns `team,p0..p17`), returns the path.

- [ ] **Step 1: Write the failing test** (writer is pure; network fns get a marked smoke test)

```python
# add to tests/test_kalshi.py
import numpy as np
import pandas as pd
from winspool.fetch.kalshi import write_distributions


def test_write_distributions_roundtrip(tmp_path):
    dists = {"BUF": np.full(18, 1 / 18), "ARI": np.eye(18)[4]}
    path = write_distributions(dists, str(tmp_path))
    df = pd.read_csv(path).set_index("team")
    assert list(df.columns) == [f"p{k}" for k in range(18)]
    assert pytest.approx(df.loc["BUF"].sum(), abs=1e-9) == 1.0
    assert pytest.approx(df.loc["ARI", "p4"], abs=1e-9) == 1.0


@pytest.mark.network
def test_kalshi_totals_live_smoke():
    from winspool.fetch.kalshi import kalshi_totals
    totals = kalshi_totals()
    assert len(totals) == 32
    assert all(0.0 <= v <= 17.0 for v in totals.values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kalshi.py::test_write_distributions_roundtrip -v`
Expected: FAIL — `write_distributions` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/winspool/fetch/kalshi.py (top: add `import os`, `import requests`, `import pandas as pd`)
import os
import requests
import pandas as pd

SERIES = "KXNFLWINS"
BASE = "https://external-api.kalshi.com/trade-api/v2"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
TIMEOUT = 30


def fetch_events():
    r = requests.get(f"{BASE}/events", headers=HEADERS, timeout=TIMEOUT,
                     params={"series_ticker": SERIES, "with_nested_markets": "true", "limit": 200})
    r.raise_for_status()
    return r.json().get("events", [])


def kalshi_distributions():
    return events_to_distributions(fetch_events())


def kalshi_totals():
    return {code: pmf_line(pmf) for code, pmf in kalshi_distributions().items()}


def write_distributions(dists, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    cols = [f"p{k}" for k in range(MAX_WINS + 1)]
    rows = [{"team": code, **{c: float(v) for c, v in zip(cols, pmf)}}
            for code, pmf in sorted(dists.items())]
    path = os.path.join(cache_dir, "kalshi_distributions.csv")
    pd.DataFrame(rows, columns=["team", *cols]).to_csv(path, index=False)
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_kalshi.py::test_write_distributions_roundtrip -v`
Then the live smoke test explicitly: `uv run pytest tests/test_kalshi.py -m network -v`
Expected: writer test PASS; smoke test PASS (needs network; 32 teams).

- [ ] **Step 5: Register the `network` marker so it isn't collected by default**

Add to `pyproject.toml` under `[tool.pytest.ini_options]` (create the section if absent):

```toml
[tool.pytest.ini_options]
markers = ["network: hits live external endpoints (deselect with -m 'not network')"]
addopts = "-m 'not network'"
```

Run: `uv run pytest tests/test_kalshi.py -v`
Expected: the 6 non-network tests PASS; the network smoke test is deselected.

- [ ] **Step 6: Commit**

```bash
git add src/winspool/fetch/kalshi.py tests/test_kalshi.py pyproject.toml
git commit -m "feat(kalshi): public-API fetchers + distributions artifact writer"
```

---

### Task 4: Register Kalshi as a totals source + write distributions on fetch

**Files:**
- Modify: `src/winspool/fetch/registry.py`
- Modify: `src/winspool/cli.py` (the `fetch` subcommand block, around lines 53-73)
- Test: `tests/test_fetch_pipeline.py`

**Interfaces:**
- Consumes: `kalshi_totals`, `kalshi_distributions`, `write_distributions` (Task 3), `Source` (`fetch/pipeline.py`).
- Produces: `default_sources()` includes a `Source("kalshi", "totals", kalshi_totals)`; `winspool fetch` writes `kalshi_distributions.csv` alongside the cache.

- [ ] **Step 1: Write the failing test** (registry wiring; keep it offline via a stub)

```python
# add to tests/test_fetch_pipeline.py
def test_default_sources_includes_kalshi():
    from winspool.fetch.registry import default_sources
    names = {s.name for s in default_sources()}
    assert "kalshi" in names
    kal = next(s for s in default_sources() if s.name == "kalshi")
    assert kal.kind == "totals"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fetch_pipeline.py::test_default_sources_includes_kalshi -v`
Expected: FAIL — `"kalshi"` not in names.

- [ ] **Step 3: Add the source to the registry**

In `src/winspool/fetch/registry.py`, add the import and the Source:

```python
# in the existing scrapers import line, this stays; add:
from .kalshi import kalshi_totals

# inside default_sources(), add to the returned list (a totals source):
        Source("kalshi", "totals", kalshi_totals),   # Kalshi KXNFLWINS implied line
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fetch_pipeline.py -v`
Expected: PASS (all pipeline tests).

- [ ] **Step 5: Wire the distribution write into the `fetch` CLI command**

In `src/winspool/cli.py`, inside the `if args.cmd == "fetch":` block, after the
`meta = refresh(...)` loop that prints sources, add (before `return 0`):

```python
        try:
            from .fetch.kalshi import kalshi_distributions, write_distributions
            dists = kalshi_distributions()
            path = write_distributions(dists, args.cache)
            print(f"kalshi distributions: {len(dists)} teams -> {path}")
        except Exception as e:
            print(f"  WARNING: kalshi distributions failed, skipping: "
                  f"{type(e).__name__}: {e}")
```

- [ ] **Step 6: Verify the full command runs (live)**

Run: `uv run winspool fetch`
Expected: source lines include `kalshi   totals   32 teams`, plus a
`kalshi distributions: 32 teams -> data/cache/kalshi_distributions.csv` line.
Confirm the file exists: `uv run python -c "import pandas as pd; print(pd.read_csv('data/cache/kalshi_distributions.csv').shape)"` → `(32, 19)`.

- [ ] **Step 7: Commit**

```bash
git add src/winspool/fetch/registry.py src/winspool/cli.py tests/test_fetch_pipeline.py
git commit -m "feat(kalshi): register implied line as totals source + write distributions on fetch"
```

---

### Task 5: Market-view module (load / summarize / independent sample)

**Files:**
- Create: `src/winspool/market.py`
- Test: `tests/test_market.py`

**Interfaces:**
- Consumes: `kalshi_distributions.csv` (Task 3 format), `winspool.teams.TEAMS`/`TEAM_INDEX`/`N_TEAMS`.
- Produces:
  - `load_distributions(path) -> (codes: list[str], pmf_matrix: np.ndarray[n, 18])`.
  - `summarize(codes, pmf_matrix) -> list[dict]` — per team `{team, line, mean, sd}`.
  - `sample_independent(pmf_matrix, n_seasons, rng) -> np.ndarray[n_seasons, n]` — i.i.d. draws per team.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_market.py
import numpy as np
import pandas as pd
import pytest
from winspool.market import load_distributions, summarize, sample_independent


def _write_csv(tmp_path):
    cols = [f"p{k}" for k in range(18)]
    buf = np.zeros(18); buf[11] = 1.0            # BUF always 11 wins
    ari = np.zeros(18); ari[4] = 1.0             # ARI always 4 wins
    df = pd.DataFrame([{"team": "BUF", **dict(zip(cols, buf))},
                       {"team": "ARI", **dict(zip(cols, ari))}])
    p = tmp_path / "kalshi_distributions.csv"
    df.to_csv(p, index=False)
    return str(p)


def test_load_and_summarize(tmp_path):
    codes, mat = load_distributions(_write_csv(tmp_path))
    assert mat.shape == (2, 18)
    s = {d["team"]: d for d in summarize(codes, mat)}
    assert pytest.approx(s["BUF"]["mean"], abs=1e-9) == 11.0
    assert pytest.approx(s["ARI"]["mean"], abs=1e-9) == 4.0
    assert s["BUF"]["sd"] == 0.0                 # degenerate PMF -> zero spread


def test_sample_independent_recovers_means(tmp_path):
    codes, mat = load_distributions(_write_csv(tmp_path))
    rng = np.random.default_rng(0)
    draws = sample_independent(mat, 5000, rng)
    assert draws.shape == (5000, 2)
    assert draws[:, codes.index("BUF")].mean() == 11.0   # degenerate -> exact
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_market.py -v`
Expected: FAIL — `No module named 'winspool.market'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/winspool/market.py
"""Standalone market view over Kalshi-implied per-team win distributions.

Independent of the correlated season sim: this reads the PMF artifact and reports
the market's implied line, mean, and SD (confidence), and can draw season win
totals i.i.d. per team. Explicitly NOT the pick decision engine (no schedule
correlation) — a pure market lens."""
import numpy as np
import pandas as pd
from .fetch.kalshi import pmf_mean, pmf_sd, pmf_line


def load_distributions(path):
    df = pd.read_csv(path).set_index("team")
    cols = [f"p{k}" for k in range(18)]
    codes = list(df.index)
    mat = df[cols].to_numpy(dtype=float)
    return codes, mat


def summarize(codes, pmf_matrix):
    out = []
    for code, pmf in zip(codes, pmf_matrix):
        out.append({"team": code, "line": pmf_line(pmf),
                    "mean": pmf_mean(pmf), "sd": pmf_sd(pmf)})
    return out


def sample_independent(pmf_matrix, n_seasons, rng):
    n_teams = pmf_matrix.shape[0]
    wins = np.zeros((n_seasons, n_teams), dtype=np.int16)
    outcomes = np.arange(pmf_matrix.shape[1])
    for t in range(n_teams):
        wins[:, t] = rng.choice(outcomes, size=n_seasons, p=pmf_matrix[t])
    return wins
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_market.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/winspool/market.py tests/test_market.py
git commit -m "feat(market): Kalshi market-view load/summarize/independent-sample"
```

---

### Task 6: `winspool market` CLI subcommand

**Files:**
- Modify: `src/winspool/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `winspool.market.load_distributions`, `summarize` (Task 5).
- Produces: `winspool market [--dist data/cache/kalshi_distributions.csv]` prints a per-team table sorted by implied mean, columns `team / line / mean / sd`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_cli.py (follow the file's existing invocation pattern)
def test_market_subcommand(tmp_path, capsys):
    import pandas as pd, numpy as np
    from winspool.cli import main
    cols = [f"p{k}" for k in range(18)]
    buf = np.zeros(18); buf[11] = 1.0
    p = tmp_path / "d.csv"
    pd.DataFrame([{"team": "BUF", **dict(zip(cols, buf))}]).to_csv(p, index=False)
    rc = main(["market", "--dist", str(p)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "BUF" in out and "line" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_market_subcommand -v`
Expected: FAIL — argparse errors on unknown command `market` (SystemExit) or rc != 0.

- [ ] **Step 3: Add the subcommand**

In `src/winspool/cli.py`, register the parser next to the others (after the `fet`
block):

```python
    mkt = sub.add_parser("market")
    mkt.add_argument("--dist", default="data/cache/kalshi_distributions.csv")
```

And add the handler (before the final `return 1`):

```python
    if args.cmd == "market":
        from .market import load_distributions, summarize
        codes, mat = load_distributions(args.dist)
        rows = sorted(summarize(codes, mat), key=lambda r: r["mean"], reverse=True)
        print(f"{'team':<5}{'line':>7}{'mean':>7}{'sd':>7}")
        for r in rows:
            print(f"{r['team']:<5}{r['line']:>7.2f}{r['mean']:>7.2f}{r['sd']:>7.2f}")
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_market_subcommand -v`
Expected: PASS.

- [ ] **Step 5: Verify against real data (live, optional)**

Run: `uv run winspool market`
Expected: 32-row table sorted by implied mean (LA/BUF/SEA near the top).

- [ ] **Step 6: Commit**

```bash
git add src/winspool/cli.py tests/test_cli.py
git commit -m "feat(cli): winspool market — per-team implied line/mean/sd"
```

---

### Task 7: Full-suite green + README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest -q`
Expected: all tests PASS (non-network); no new warnings introduced by our modules.

- [ ] **Step 2: Document the source and the command**

In `README.md`, under the Data section, add a bullet:

```markdown
- `kalshi_distributions.csv` — Kalshi `KXNFLWINS` market-implied per-team win
  distributions (public API, no auth). Its implied line is blended into
  `win_totals.csv` alongside covers; the full distribution powers `winspool market`.
```

And under the CLI section:

```markdown
uv run winspool market                  # per-team market-implied line / mean / SD (confidence)
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document Kalshi source and winspool market"
```

---

## Self-Review Notes

- **Spec coverage:** Fetch+PMF (Tasks 1–3) ✓; standalone market view + CLI (Tasks 5–6) ✓; decision-engine blend via totals source (Task 4) ✓; testing/fixture (Tasks 1–6) ✓; resilient-fetch reuse — Kalshi rides the already-committed per-source try/except, and the distribution write has its own try/except (Task 4 Step 5) ✓. Phase-2 items (per-team SD injection; Kalshi as its own mixture voice) intentionally excluded.
- **Monotonic/normalize edge cases:** Task 1 tests both a clean and a non-monotone ladder; gap-fill carries survival forward.
- **Team aliases:** `_KALSHI_FIX = {"LAR": "LA", "JAC": "JAX"}` verified against all 32 live event tickers.
- **Types consistent across tasks:** `ladder_to_pmf`/`pmf_mean`/`pmf_sd`/`pmf_line`, `events_to_distributions`, `kalshi_totals`/`kalshi_distributions`/`write_distributions`, `load_distributions`/`summarize`/`sample_independent` names match between producer and consumer tasks.
