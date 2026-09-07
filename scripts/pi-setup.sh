#!/usr/bin/env bash
# One-time Raspberry Pi provisioning: service user, data dirs, systemd units.
# Idempotent — safe to re-run after a units change. Run with sudo.
#
#   sudo ./scripts/pi-setup.sh
#
# It deliberately does NOT write secrets. On a fresh box it drops an env
# template at /etc/winspool/env; fill in SESSION_SECRET before starting.
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/winspool}
DATA_DIR=${DATA_DIR:-/var/lib/winspool}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/winspool}
ENV_FILE=${ENV_FILE:-/etc/winspool/env}
USER_NAME=winspool

[[ $EUID -eq 0 ]] || { echo "run me with sudo" >&2; exit 1; }

UNITS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy/pi"
[[ -d $UNITS_DIR ]] || { echo "missing $UNITS_DIR" >&2; exit 1; }

echo "==> service user"
id -u "$USER_NAME" &>/dev/null || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$USER_NAME"

echo "==> directories"
install -d -o "$USER_NAME" -g "$USER_NAME" -m 750 "$DATA_DIR" "$BACKUP_DIR"
install -d -m 755 "$(dirname "$ENV_FILE")"

if [[ ! -f $ENV_FILE ]]; then
  echo "==> $ENV_FILE (template — fill in the secrets)"
  cat > "$ENV_FILE" <<ENVEOF
STORE=sqlite
WINSPOOL_DB=$DATA_DIR/league.db
WINSPOOL_DATA_DIR=$APP_DIR/data/cache
WINSPOOL_WEB_DIST=$APP_DIR/web/dist
WINSPOOL_BEHIND_PROXY=1
# MUST match the Cloud Run revision, or every player is logged out on cutover.
SESSION_SECRET=
REFRESH_TOKEN=
ENVEOF
  chmod 600 "$ENV_FILE"
else
  echo "==> $ENV_FILE exists, leaving it alone"
fi

echo "==> systemd units"
install -m 644 "$UNITS_DIR"/*.service "$UNITS_DIR"/*.timer /etc/systemd/system/
systemctl daemon-reload

echo "==> enabling timers"
systemctl enable winspool-scores-gameday.timer winspool-scores-offday.timer \
                 winspool-backup.timer >/dev/null

echo
echo "Provisioned. Remaining steps:"
grep -q '^SESSION_SECRET=$' "$ENV_FILE" && echo "  - set SESSION_SECRET (and REFRESH_TOKEN) in $ENV_FILE"
echo "  - $APP_DIR must be a checkout with a built .venv and web/dist (scripts/pi-deploy.sh)"
echo "  - systemctl enable --now winspool && systemctl start winspool-scores-gameday.timer"
