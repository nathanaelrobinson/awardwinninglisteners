# Raspberry Pi — operations runbook

Companion to `docs/superpowers/specs/2026-09-08-raspberry-pi-hosting-design.md`
(the design). This is the operational half: what is installed where, how to
deploy, and the cutover checklist.

## Layout

| What | Where |
| --- | --- |
| Code | `/opt/winspool` (git checkout, remote `origin`, branch `main`) |
| Virtualenv | `/opt/winspool/.venv` (built by `uv sync --extra dev`) |
| Front end | `/opt/winspool/web/dist` (built by `npm run build`) |
| Database | `/var/lib/winspool/league.db` (SQLite, WAL) |
| Backups | `/var/backups/winspool/league-YYYY-MM-DD.db` (nightly, 30 kept) |
| Secrets | `/etc/winspool/env` (mode 600, owned by root) |
| Units | `/etc/systemd/system/winspool*.{service,timer}` (source in `deploy/pi/`) |

The app listens on `127.0.0.1:8080` only. Nothing is exposed directly; the
Cloudflare tunnel is the sole ingress.

## Environment (`/etc/winspool/env`)

```
STORE=sqlite
WINSPOOL_DB=/var/lib/winspool/league.db
WINSPOOL_DATA_DIR=/opt/winspool/data/cache
WINSPOOL_WEB_DIST=/opt/winspool/web/dist
WINSPOOL_BEHIND_PROXY=1     # marks the session cookie Secure behind the tunnel
SESSION_SECRET=...          # MUST equal the Cloud Run value, or everyone is logged out
REFRESH_TOKEN=...           # only the scores timer uses it
```

`SESSION_SECRET` is not optional: with `STORE` set, the app refuses to boot
without it rather than falling back to the public dev value.

## First-time provisioning

```bash
sudo ./scripts/pi-setup.sh          # user, dirs, env template, units, timers
sudoedit /etc/winspool/env          # fill in SESSION_SECRET and REFRESH_TOKEN
sudo /opt/winspool/scripts/pi-deploy.sh
sudo systemctl enable --now winspool
sudo systemctl start winspool-scores-gameday.timer winspool-scores-offday.timer
sudo systemctl start winspool-backup.timer
```

## Deploying a change

```bash
ssh pi 'sudo /opt/winspool/scripts/pi-deploy.sh'
```

Pulls `main`, re-syncs Python deps, rebuilds the front end, restarts the
service, and polls `/api/teams` for up to 60s. On failure it prints the last 40
journal lines and exits non-zero.

## Day-to-day

Most of what follows is wrapped by the Makefile at the repo root — `make help`
lists them, and `make status` is the one-shot dashboard. The raw commands are
kept here because they work from any shell, including a rescue session where
the checkout isn't handy.


```bash
systemctl status winspool
journalctl -u winspool -f                  # live logs
journalctl -u winspool-scores -n 50        # standings refreshes
systemctl list-timers 'winspool*'          # when the next refresh/backup fires
sqlite3 /var/lib/winspool/league.db 'select count(*) from messages;'
```

Force a standings refresh: `sudo systemctl start winspool-scores.service`.

## Backup and restore

Backups are `sqlite3 .backup` (WAL-safe — never `cp` a live database):

```bash
sudo systemctl start winspool-backup.service       # take one now
ls -la /var/backups/winspool/
```

Restore:

```bash
sudo systemctl stop winspool
sudo -u winspool cp /var/backups/winspool/league-2026-09-14.db /var/lib/winspool/league.db
sudo systemctl start winspool
```

A JSON export is the portable form, and works against any store:

```bash
sudo -u winspool env $(sudo cat /etc/winspool/env | grep -v '^#' | xargs) \
  /opt/winspool/.venv/bin/winspool export --out /tmp/league_export.json
```

## The Cloudflare tunnel

Connected on 2026-09-07 via the CLI (not the dashboard token flow), so the whole
thing is reproducible from this machine.

- Tunnel name `pi`, id `261a8679-9eb0-414c-8b83-865c1188e845`
- Config `/etc/cloudflared/config.yml`, credentials
  `/etc/cloudflared/261a8679-….json` (mode 600, root)
- `cloudflared.service` is enabled and reconnects on its own after power or
  network loss. Four QUIC connections to the edge is normal.

Ingress: `awardwinninglisteners.com` and `www.` → `http://localhost:8080`;
anything else gets `http_status:404` without reaching the app. The app itself
stays bound to `127.0.0.1:8080` and is never exposed directly.

```bash
systemctl status cloudflared
cloudflared tunnel info pi                       # edge connections
journalctl -u cloudflared -n 50 --no-pager
sudo cloudflared --config /etc/cloudflared/config.yml tunnel ingress validate
sudo cloudflared --config /etc/cloudflared/config.yml tunnel ingress rule https://awardwinninglisteners.com/
```

To rebuild it from scratch: `cloudflared tunnel login`, `cloudflared tunnel
create pi`, `cloudflared tunnel route dns pi <hostname>` for each name, write
the config above, then `sudo cloudflared service install`.

**The tunnel serves nothing until the zone is active on Cloudflare** — i.e.
until the nameservers move (cutover step 5). Until then the CNAMEs exist only
inside the Cloudflare zone and public DNS still answers from Cloud DNS.

## Cutover from Cloud Run (day after the draft)

Preconditions: draft `status == done`, completion snapshot exists, Pi service
green with a test import.

1. **Freeze** — tell the group standings/comments are read-only for ~10 minutes.
2. **Export** from the laptop that has gcloud ADC:
   ```bash
   STORE=firestore GOOGLE_CLOUD_PROJECT=snowpack-pika \
     uv run winspool export --out league_export.json
   ```
3. **Copy and import** on the Pi:
   ```bash
   scp league_export.json pi:/tmp/
   sudo -u winspool env $(sudo cat /etc/winspool/env | grep -v '^#' | xargs) \
     /opt/winspool/.venv/bin/winspool import --from /tmp/league_export.json --force
   sudo systemctl restart winspool
   ```
4. **Verify locally** — `curl -fsS localhost:8080/api/teams`, then log in and
   confirm 30 picks, the full feed, the completion snapshot, and cached standings.
5. **Switch DNS** to the Cloudflare nameservers (see the design doc §4).
6. **Verify publicly** at https://awardwinninglisteners.com — existing devices
   stay logged in if `SESSION_SECRET` matched.
7. **Run the scores timer once**: `sudo systemctl start winspool-scores.service`.
8. **Wind down GCP** — pause both Cloud Scheduler jobs, set Cloud Run
   `--min-instances 0`, switch `.github/workflows/deploy.yml` to
   `workflow_dispatch` only. Keep everything for 7 days as the rollback window,
   then delete.

Rollback before step 8's deletions: point the nameservers back at
`ns-cloud-e*.googledomains.com`. Cloud DNS records and the Cloud Run service are
untouched and still hold the data as of the freeze.

## Failure modes

| Symptom | Cause | Response |
| --- | --- | --- |
| 502 from Cloudflare | tunnel or app down | `systemctl status cloudflared winspool` |
| API returns 503 "busy" | SQLite write lock held >5s | transient; check for a stuck backup |
| Service won't start, log says `SESSION_SECRET must be set` | env file incomplete | fill `/etc/winspool/env` |
| Standings stale | Pi was offline when the timer fired | `systemctl start winspool-scores.service` |
| `import` refuses | target already has a league | intended; pass `--force` |
