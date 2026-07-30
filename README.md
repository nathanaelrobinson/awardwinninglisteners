# Wins Pool 2026

Draft optimizer + season simulator for a 6-player, winner-take-all NFL wins pool.
Monte-Carlo simulates the real 2026 schedule game-by-game, then ranks draft picks by
**P(you finish 1st)** — accounting for schedule correlation and variance, not just
expected wins.

## Setup (uv + node)

```bash
# Python engine + API (uv)
uv venv
uv pip install -e ".[dev]"

# Front end (Vite/React)
cd web && npm install && npm run build && cd ..
```

## Data

The tool reads two files from `data/cache/`:
- `schedule_2026.csv` — fetch the real schedule: `uv run python scripts/fetch_data.py`
- `win_totals.csv` — Vegas season win totals (`team,win_total`). A placeholder set is
  seeded; replace with real numbers. (A multi-source `winspool fetch` pipeline exists —
  see `docs/data-sources.md` — but its live scrapers need endpoint verification first.)

## Run the draft app

```bash
uv run winspool-serve          # serves API + UI at http://127.0.0.1:8000
```

Open http://127.0.0.1:8000, pick your slot, and click teams as they're drafted; the board
shows live pick recommendations. Toggle **Deep analysis** for the opponent-aware rollout.

Dev mode (hot reload): `uv run winspool-serve` in one terminal, `cd web && npm run dev` in
another (Vite proxies `/api` to `:8000`).

## CLI (no UI)

```bash
uv run winspool recommend --slot 3 --taken KC,BUF,PHI --rollouts 200
uv run winspool analyze                 # per-team variance / ceiling / floor / SOS
uv run winspool positional              # which draft slot is best for you
```

## Tests

```bash
uv run pytest -q
```

See `docs/superpowers/specs/` and `docs/superpowers/plans/` for the design and build plan.
