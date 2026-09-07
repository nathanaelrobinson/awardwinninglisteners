# Raspberry Pi Hosting — Design

Date: 2026-09-08. Move the live league app off Cloud Run onto Nate's always-on
Raspberry Pi (16 GB RAM, 1 TB storage), keep https://awardwinninglisteners.com,
and retire the GCP dependencies (Firestore, Cloud Scheduler, Cloud Run).

Cutover happens the day after the draft, once the draft result is final. Until
then Cloud Run stays authoritative. This document is written so a Claude Code
session running on the Pi can execute it end to end; the sections marked
**Nate** need a human.

## Goals

- Same app, same URL, same login cookies (sessions survive the move).
- Zero cloud cost: no Firestore, no Cloud Run, no Cloud Scheduler.
- Draft results, comments, snapshots, and standings history carried over intact.
- Deploy is `git pull` + restart. Nightly local backups.

## Non-goals

- Multi-node or high availability. One Pi, one process.
- Changing any UI or API behavior. The frontend is untouched.
- Keeping GCP as a hot standby beyond a short rollback window.

## Architecture

```
Internet ──TLS──▶ Cloudflare edge ──tunnel──▶ cloudflared (Pi) ──▶ uvicorn :8080
                                                              │
                                                    SQLite /var/lib/winspool/league.db
systemd timer (scores refresh) ──▶ POST localhost:8080/internal/refresh-standings
```

- **App**: the existing FastAPI service, run by uvicorn under systemd, `STORE=sqlite`.
- **Store**: a new `SqliteStore` implementing the existing `Store` protocol
  (`get, put, update, add_message, messages, get_standings, put_standings,
  add_snapshot, clear_messages, list_snapshots`). Single file DB, WAL mode.
- **Ingress**: Cloudflare Tunnel. No port forwarding, no public IP, no certificate
  management. Cloudflare terminates TLS and forwards to `localhost:8080`.
- **DNS**: the zone moves from Cloud DNS to Cloudflare (required for the tunnel).
  The registrar stays Cloud Domains; only the nameservers change.
- **Scheduler**: a systemd timer replaces the two Cloud Scheduler jobs.
- **Backups**: nightly `sqlite3 .backup` to `/var/backups/winspool/`, keep 30.

## Components

### 1. `SqliteStore` (`src/winspool/store.py`)

Schema (created on first open):

```sql
CREATE TABLE IF NOT EXISTS league    (id TEXT PRIMARY KEY, doc TEXT NOT NULL);           -- id='2026', doc=JSON
CREATE TABLE IF NOT EXISTS messages  (id TEXT PRIMARY KEY, by TEXT, text TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS messages_ts ON messages(ts);
CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, taken_at REAL, reason TEXT,
                                      n_picks INTEGER, status TEXT, doc TEXT NOT NULL); -- doc=full snapshot JSON
CREATE TABLE IF NOT EXISTS kv        (k TEXT PRIMARY KEY, v TEXT NOT NULL);              -- k='standings'
```

Behavior:

- `__init__(path)` opens with `check_same_thread=False`, `PRAGMA journal_mode=WAL`,
  `PRAGMA busy_timeout=5000`. One connection guarded by a `threading.Lock`.
- `update(fn)` runs `BEGIN IMMEDIATE; SELECT doc; fn(doc); UPDATE; COMMIT` under the
  lock. This is the transactional guarantee that Firestore gave us; SQLite's
  writer lock plus `BEGIN IMMEDIATE` provides the same "one pick at a time" semantics.
- `messages(since)` returns oldest-first, capped at `MSG_CAP` (200): with `since`
  the first 200 after `since`, without it the newest 200 (same as Firestore path).
- `add_message` generates `uuid4().hex` ids and `time.time()` timestamps.
- `list_snapshots()` newest first, limit 50, fields `{id, taken_at, reason, n_picks, status}`.
- `clear_messages()` returns the deleted row count.
- Selected by `STORE=sqlite`; path from `WINSPOOL_DB` (default `./data/league.db`).

Tests: parametrize the existing store-level tests over `InMemoryStore` and
`SqliteStore(tmp_path / "t.db")` so both pass the same suite. Add one concurrency
test: 20 threads each calling `update(lambda d: {**d, "n": d.get("n", 0) + 1})`
end with `n == 20`.

### 2. Export / import (`src/winspool/cli.py`)

- `winspool export --out league_export.json` — reads from whatever `STORE` is
  configured (run once with `STORE=firestore GOOGLE_CLOUD_PROJECT=snowpack-pika` on
  a machine with `gcloud auth application-default login`) and writes
  `{league, messages (all, no cap — page through Firestore), snapshots (full docs),
  standings, exported_at}`.
- `winspool import --from league_export.json` — writes all of it into the configured
  store (`STORE=sqlite`). Refuses if the target already has a league unless `--force`.
- Round-trip test: export from an `InMemoryStore` with picks, messages, two
  snapshots, standings → import into a fresh `SqliteStore` → identical `view()`,
  message list, snapshot list, standings doc.

The Firestore message read must bypass `MSG_CAP`: add an internal
`FirestoreStore.all_messages()` (ordered by `ts`, no limit) used only by export.

### 3. Pi runtime

Paths and users:

- Code: `/opt/winspool` (git clone of `github.com/nathanaelrobinson/awardwinninglisteners`, branch `main`).
- Data: `/var/lib/winspool/league.db` (owned by service user `winspool`).
- Env: `/etc/winspool/env` (mode 600):
  ```
  STORE=sqlite
  WINSPOOL_DB=/var/lib/winspool/league.db
  WINSPOOL_DATA_DIR=/opt/winspool/data/cache
  WINSPOOL_WEB_DIST=/opt/winspool/web/dist
  SESSION_SECRET=<same value as the Cloud Run revision — copy it, do not regenerate, or everyone is logged out>
  REFRESH_TOKEN=<same value as today, or a new one; only the timer uses it>
  ```
- Python: `uv` installed for the service user; `uv sync --extra dev` in `/opt/winspool`
  (Python 3.11 via `.python-version`; ARM64 wheels exist for numpy/pandas/scipy).
- Node 22 for `cd web && npm ci && npm run build`.
- `data/cache/` is tracked in git, so the sim matrix comes with the clone.

`/etc/systemd/system/winspool.service`:

```ini
[Unit]
Description=Wins pool app
After=network-online.target
Wants=network-online.target

[Service]
User=winspool
WorkingDirectory=/opt/winspool
EnvironmentFile=/etc/winspool/env
ExecStart=/opt/winspool/.venv/bin/winspool-serve --host 127.0.0.1 --port 8080
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/winspool-scores.service` (oneshot) runs:

```
/usr/bin/curl -fsS -X POST -H "X-Refresh-Token: ${REFRESH_TOKEN}" http://127.0.0.1:8080/internal/refresh-standings
```

with `EnvironmentFile=/etc/winspool/env`. Two timers:

```ini
# winspool-scores-gameday.timer
[Timer]
OnCalendar=Sun,Mon,Thu *-*-* *:00/15
Persistent=true
Unit=winspool-scores.service

# winspool-scores-offday.timer
[Timer]
OnCalendar=Tue,Wed,Fri,Sat *-*-* 00/4:00
Persistent=true
Unit=winspool-scores.service
```

Timezone: set the Pi to `America/Los_Angeles` (`timedatectl set-timezone`) so these match
the Cloud Scheduler schedules.

Backups: `/etc/systemd/system/winspool-backup.{service,timer}` daily at 03:30 running

```
sqlite3 /var/lib/winspool/league.db ".backup /var/backups/winspool/league-$(date +%F).db" && find /var/backups/winspool -name 'league-*.db' -mtime +30 -delete
```

Optional: `rclone copy /var/backups/winspool <remote>:winspool-backups` if an
off-Pi copy is wanted later.

Deploy script `scripts/pi-deploy.sh` (committed):

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /opt/winspool
git pull --ff-only
uv sync --extra dev
(cd web && npm ci && npm run build)
sudo systemctl restart winspool
curl -fsS http://127.0.0.1:8080/api/teams >/dev/null && echo "ok"
```

### 4. Ingress: Cloudflare Tunnel

**Nate** (one-time, ~15 min):

1. Create a free Cloudflare account, "Add a site" → `awardwinninglisteners.com`, Free plan.
   Cloudflare shows two nameservers (e.g. `xxx.ns.cloudflare.com`). Do not import
   the old A/AAAA records; the tunnel creates its own CNAME.
2. Point the registrar at Cloudflare. The domain is registered in Cloud Domains
   (project `snowpack-pika`), so:
   ```
   gcloud domains registrations configure dns awardwinninglisteners.com \
     --project snowpack-pika --name-servers=<ns1>.ns.cloudflare.com,<ns2>.ns.cloudflare.com
   ```
   Propagation is usually minutes, up to a few hours. Cloud DNS records stay in
   place (harmless, and the rollback path).
3. In Cloudflare Zero Trust → Networks → Tunnels → Create tunnel (name `pi`),
   choose "Cloudflared", copy the install command + token for Debian/ARM64.
4. Add a Public Hostname: `awardwinninglisteners.com` → `http://localhost:8080`.
   Add a second: `www.awardwinninglisteners.com` → same. Cloudflare writes the
   CNAMEs automatically.
5. SSL/TLS mode: "Full" is fine (tunnel is encrypted end to end anyway).
   Turn on "Always use HTTPS".

**Pi**: install `cloudflared` as a service with the token from step 3
(`sudo cloudflared service install <token>`). It reconnects on its own after
power or network loss.

The app already sets the session cookie `secure` only when `K_SERVICE` is set
(Cloud Run). Behind Cloudflare the browser still sees HTTPS, so add `secure=True`
when `WINSPOOL_BEHIND_PROXY=1` is in the env file; `auth.set_cookie` reads it.
Also trust `X-Forwarded-Proto` is not needed (nothing in the app inspects the scheme).

### 5. Cutover plan (day after the draft)

Preconditions: draft is `done`; the completion snapshot exists in Firestore;
Pi build is green (`pytest`, web build, `winspool-serve` runs on `pi:8080` with an
imported copy of an earlier export).

1. **Freeze**: tell the group standings/comments are read-only for 10 minutes.
2. **Export** (Nate's laptop, has gcloud ADC):
   `STORE=firestore GOOGLE_CLOUD_PROJECT=snowpack-pika uv run winspool export --out league_export.json`
3. **Import** on the Pi: `scp` the file, then
   `sudo -u winspool env $(cat /etc/winspool/env | xargs) /opt/winspool/.venv/bin/winspool import --from league_export.json --force`
4. **Verify locally on the Pi**: `curl localhost:8080/api/league` (login with a cookie
   first) shows `status done`, 30 picks, rosters; `/api/messages` shows the full
   feed; `/api/league/snapshots` lists the completion snapshot; `/api/standings`
   returns the last cached wins.
5. **Switch DNS** (Nate, step 4.2 above if not already done). Once
   `dig NS awardwinninglisteners.com` returns Cloudflare, the tunnel serves the site.
6. **Verify publicly**: log in on a phone at https://awardwinninglisteners.com;
   existing devices stay logged in (same `SESSION_SECRET`).
7. **Run the scores timer once**: `sudo systemctl start winspool-scores.service`;
   standings "Updated" time changes.
8. **Wind down GCP**: pause both Cloud Scheduler jobs
   (`gcloud scheduler jobs pause pika-scores-gameday …`), set Cloud Run
   `--min-instances 0`. Leave the service and Firestore for 7 days as rollback,
   then delete the Cloud Run service, scheduler jobs, and Firestore data. Keep the
   project for Cloud Domains (registrar) — or transfer the registration to
   Cloudflare Registrar later and delete the project entirely.

Rollback at any point before step 8's deletions: point nameservers back at the
four `ns-cloud-e*.googledomains.com` servers. Cloud DNS still has the A/AAAA
records and Cloud Run still has the data as of the freeze.

### 6. CI/CD after the move

GitHub Actions `ci.yml` keeps running tests on every push. `deploy.yml` (Cloud Run)
is disabled by renaming the trigger to `workflow_dispatch` only. Deploys to the Pi
are `ssh pi 'sudo /opt/winspool/scripts/pi-deploy.sh'` after merging to `main`.
A self-hosted runner on the Pi can automate that later; not needed now.

## Error handling

- SQLite locked → `busy_timeout` 5 s, then `sqlite3.OperationalError` → mapped to
  503 in `_run` (same path as Firestore contention today).
- Tunnel down → Cloudflare returns 502; app data is unaffected; `cloudflared`
  auto-reconnects.
- Pi offline on a game day → standings stale until it returns; the `stale` flag
  and "Updated" time already show this.
- Import into a non-empty DB without `--force` → refused.

## Testing

- `pytest` full suite green on the Pi (ARM64) with `STORE` unset (in-memory) and
  with the store fixture parametrized to SQLite.
- Concurrency test for `SqliteStore.update`.
- Export → import round-trip test.
- Manual: mock draft against `pi:8080` with the dev league (all PINs `1234`) before
  cutover; Restart draft; verify snapshot rows appear in `snapshots`.

## Overnight task list for the Pi session

1. Clone repo to `/opt/winspool`, create `winspool` user, install uv + Node 22,
   `uv sync --extra dev`, build web, run `pytest` (must be green on ARM64).
2. Implement `SqliteStore` + tests; implement `export`/`import` + round-trip test;
   add `WINSPOOL_BEHIND_PROXY` cookie flag. Commit on a branch `pi-hosting`; open a PR
   to `main` (CI must pass). Do not merge without Nate.
3. Write systemd units, timers, backup job, `scripts/pi-deploy.sh`; enable the
   service with `STORE=sqlite` and the dev league; verify `curl localhost:8080/api/teams`.
4. Install `cloudflared` but do not connect the tunnel until Nate has created it
   (needs his Cloudflare login). Leave a note with the exact command to run.
5. Report: what's built, test results, and the remaining Nate steps (Cloudflare
   account, nameserver change, export from laptop, PR merge).
