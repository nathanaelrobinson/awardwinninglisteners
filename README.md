# Wins Pool 2026

Draft optimizer + season simulator for a 5-player, 6-team-per-player, winner-take-all NFL wins pool.
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
- `kalshi_distributions.csv` — Kalshi `KXNFLWINS` market-implied per-team win
  distributions (public API, no auth). Kalshi is its own forecast voice (not blended
  into `win_totals.csv`); the full distribution calibrates the sim's per-team season
  variance to match Kalshi's implied volatility, and powers `winspool market`.

## Run the draft app

```bash
uv run winspool-serve          # serves API + UI at http://127.0.0.1:8000
```

Open http://127.0.0.1:8000, pick your slot, and click teams as they're drafted; the board
shows live pick recommendations. Toggle **Deep analysis** for the opponent-aware rollout.

Dev mode (hot reload): `uv run winspool-serve` in one terminal, `cd web && npm run dev` in
another (Vite proxies `/api` to `:8000`).

## Live league (Cloud Run)

Shared live draft + standings for the 5-person league. Each player logs in with their name
and a personal PIN; the commissioner (Nate) is the only one who sees the optimizer.

**Deploy:**

```bash
export SESSION_SECRET=...   # must be the SAME value on every redeploy, or all sessions are invalidated
./scripts/deploy.sh
```

Builds from a clean `git archive HEAD` plus the local `data/cache/` — so `data/cache/sim_matrix.npz`
must exist and be current (run `uv run winspool-serve` once locally to build it). GCP project
`snowpack-pika`, region `us-west1`, service `pika`.

**Initialize / reset the league** (wipes picks; run before draft night):

```bash
STORE=firestore GOOGLE_CLOUD_PROJECT=snowpack-pika uv run winspool league-init \
  --players "Nate Robinson,Evan Goguillon-Bader,Logan Borgelt,Eric Whitley,Mitch Fischer" \
  --commissioner "Nate Robinson" [--pins "Name=1234,..."] [--force]
```

Without `--pins` it generates a random 4-digit PIN per player and prints them once — text each
person theirs. `--force` is required if picks exist. Messages live in the Firestore subcollection
`leagues/2026/messages` and are not wiped by `league-init`; delete them in the console if needed.

**Local dev:** `uv run winspool-serve` seeds an in-memory league; every player's PIN is `1234`
(override with `LEAGUE_DEV_PIN`).

**Standings:** regular-season wins from `nfl_data_py`, cached in Firestore (`leagues/2026/cache/standings`)
so all players read one stored result instead of each triggering a live fetch; the commissioner can
override a team's wins by clicking the number.

`POST /internal/refresh-standings` (header `X-Refresh-Token: $REFRESH_TOKEN`) refreshes the cache;
Cloud Scheduler calls it every 15 minutes on Sun/Mon/Thu and every 4 hours otherwise.

## CLI (no UI)

```bash
uv run winspool recommend --slot 3 --taken KC,BUF,PHI --rollouts 200
uv run winspool analyze                 # per-team variance / ceiling / floor / SOS
uv run winspool positional              # which draft slot is best for you
uv run winspool market                  # per-team market-implied line / mean / SD (confidence)
```

## Tests

```bash
uv run pytest -q
```

See `docs/superpowers/specs/` and `docs/superpowers/plans/` for the design and build plan.
