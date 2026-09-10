# Raspberry Pi — operations runbook

Companion to `docs/superpowers/specs/2026-09-08-raspberry-pi-hosting-design.md`
(the design). This is the operational half: what is installed where, how to
deploy, and the cutover checklist.

## Layout

| What | Where |
| --- | --- |
| Code | `/home/nate/awardwinninglisteners` (nate's checkout, remote `origin`, branch `main`) |
| Virtualenv | `/home/nate/awardwinninglisteners/.venv` (built by `uv sync --extra dev`) |
| Front end | `/home/nate/awardwinninglisteners/web/dist` (built by `npm run build`) |
| Database | `/var/lib/winspool/league.db` (SQLite, WAL) |
| Backups | `/var/backups/winspool/league-YYYY-MM-DD.db` (nightly, 30 kept) |
| Secrets | `/etc/winspool/env` (mode 600, owned by root) |
| Units | `/etc/systemd/system/winspool*.{service,timer}` (source in `deploy/pi/`) |

The service runs as the `winspool` user but reads code from nate's home
checkout. That needs `winspool` in the `nate` group, `/home/nate` at mode 750,
and `ProtectHome=read-only` in the unit (all set by the steps below).

The app listens on `127.0.0.1:8080` only. Nothing is exposed directly; the
Cloudflare tunnel is the sole ingress.

## Environment (`/etc/winspool/env`)

```
STORE=sqlite
WINSPOOL_DB=/var/lib/winspool/league.db
WINSPOOL_DATA_DIR=/home/nate/awardwinninglisteners/data/cache
WINSPOOL_WEB_DIST=/home/nate/awardwinninglisteners/web/dist
WINSPOOL_BEHIND_PROXY=1     # marks the session cookie Secure behind the tunnel
SESSION_SECRET=...          # changing it invalidates every session cookie
REFRESH_TOKEN=...           # only the scores timer uses it
```

`SESSION_SECRET` is not optional: with `STORE` set, the app refuses to boot
without it rather than falling back to the public dev value.

## First-time provisioning

```bash
sudo ./scripts/pi-setup.sh          # user, dirs, env template, units, timers
sudo usermod -aG nate winspool && chmod 750 /home/nate   # let the service read the checkout
sudoedit /etc/winspool/env          # fill in SESSION_SECRET and REFRESH_TOKEN
/home/nate/awardwinninglisteners/scripts/pi-deploy.sh
sudo systemctl enable --now winspool
sudo systemctl start winspool-scores-gameday.timer winspool-scores-offday.timer
sudo systemctl start winspool-backup.timer
```

## Deploying a change

```bash
ssh pi '/home/nate/awardwinninglisteners/scripts/pi-deploy.sh'
```

Runs as nate (re-execs via sudo if launched as root). Pulls `main`, re-syncs Python deps, rebuilds the front end, restarts the
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
  /home/nate/awardwinninglisteners/.venv/bin/winspool export --out /tmp/league_export.json
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

## Failure modes

| Symptom | Cause | Response |
| --- | --- | --- |
| 502 from Cloudflare | tunnel or app down | `systemctl status cloudflared winspool` |
| API returns 503 "busy" | SQLite write lock held >5s | transient; check for a stuck backup |
| Service won't start, log says `SESSION_SECRET must be set` | env file incomplete | fill `/etc/winspool/env` |
| Standings stale | Pi was offline when the timer fired | `systemctl start winspool-scores.service` |
| `import` refuses | target already has a league | intended; pass `--force` |

## Weekly ratings refresh (manual)

Tuesday morning, from a laptop with Chromium available for nfelo:

    git checkout -b ratings/$(date +%F) origin/main
    make refresh-ratings

Open the PR, merge, then on the Pi `make deploy`. The scores timer calls
`/internal/refresh-live` after every standings refresh, so the live projection
picks up the new ratings on its next run. If a week is skipped the Standings
footer shows the stale chip once ratings are more than 8 days old.

The target restores `win_totals.csv` after the fetch; pre-season totals stay
frozen on purpose.
