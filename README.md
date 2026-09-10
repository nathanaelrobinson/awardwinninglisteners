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

## Make targets

`make` (or `make help`) lists everything — dev tasks and, on the Pi, operations:

```bash
make install     # Python + web dependencies
make check       # tests + web build + lint, i.e. everything CI runs
make serve       # run locally on :8000 with a dev league (PINs 1234)

make status      # on the Pi: services, memory, endpoint, tunnel, database
make restart     # restart the app after an env or code change
make logs        # follow the app log
make deploy      # pull main, rebuild, restart, health-check
make backup      # take a database backup now
make export      # dump the live league to JSON (mode 600 — PIN hashes)
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

## Live league (Raspberry Pi)

Shared live draft + standings for the 5-person league. Each player logs in with their name
and a personal PIN; the commissioner (Nate) is the only one who sees the optimizer.

The app runs on a Pi with SQLite and a Cloudflare Tunnel — no cloud bill, no port
forwarding. Design: `docs/superpowers/specs/2026-09-08-raspberry-pi-hosting-design.md`.
Operations: `docs/pi-runbook.md`.

```bash
sudo ./scripts/pi-setup.sh                     # user, dirs, env template, systemd units
sudoedit /etc/winspool/env                     # fill in SESSION_SECRET and REFRESH_TOKEN
./scripts/pi-deploy.sh                         # pull, build, install/enable units, restart, health-check
```

`pi-deploy.sh` installs and enables every timer under `deploy/pi/` on each run, so a
newly added timer starts working on the next deploy — no re-run of `pi-setup.sh` needed.

**Initialize / reset the league** (wipes picks; run before draft night):

```bash
STORE=sqlite WINSPOOL_DB=/var/lib/winspool/league.db uv run winspool league-init \
  --players "Nate Robinson,Evan Goguillon-Bader,Logan Borgelt,Eric Whitley,Mitch Fischer" \
  --commissioner "Nate Robinson" [--pins "Name=1234,..."] [--force]
```

Without `--pins` it generates a random 4-digit PIN per player and prints them once — text each
person theirs. `--force` is required if picks exist. Messages are not wiped by `league-init`.

**Local dev:** `uv run winspool-serve` seeds an in-memory league; every player's PIN is `1234`
(override with `LEAGUE_DEV_PIN`).

**Standings:** regular-season wins from `nfl_data_py`, cached in the store so all players read
one stored result instead of each triggering a live fetch; the commissioner can override a
team's wins by clicking the number.

**Refresh jobs.** `POST /internal/refresh-standings` refreshes the wins cache,
`POST /internal/refresh-live` recomputes the in-season projection, and
`POST /internal/refresh-odds` snapshots what each of the three betting-odds
sources says about the current week's games, hourly (all three take header
`X-Refresh-Token: $REFRESH_TOKEN`). On the Pi, systemd timers call them — see
`docs/pi-runbook.md`.

`STORE=sqlite` selects the SQLite store; the database path comes from
`WINSPOOL_DB` (default `data/league.db`). `WINSPOOL_BEHIND_PROXY=1` marks the
session cookie `Secure` when the browser reaches the app over HTTPS through the
tunnel. With `STORE` set the app refuses to start without `SESSION_SECRET`
rather than falling back to the dev value.

**Backup and restore** — export the live SQLite database to portable JSON, and
restore it into any SQLite database:

```bash
# dump the source database to JSON
STORE=sqlite WINSPOOL_DB=/var/lib/winspool/league.db uv run winspool export --out league_export.json

# load it into a database (refuses a non-empty target without --force)
STORE=sqlite WINSPOOL_DB=/path/to/restored/league.db uv run winspool import --from league_export.json
```

Export carries the league doc, every message (uncapped), full snapshots, and the
standings cache. Message ids and timestamps are preserved, so the feed's
`?since=` polling keeps working across the move.

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

## CI/CD

GitHub Actions (`.github/workflows/`) runs on every push and pull request: `ci.yml` runs the
Python test suite (`uv sync --extra dev && uv run pytest -q`) and the web build/lint
(`npm ci && npm run build && npx oxlint src`). Merging to `main` does not auto-deploy; run
`scripts/pi-deploy.sh` on the Pi (see `docs/pi-runbook.md`).
