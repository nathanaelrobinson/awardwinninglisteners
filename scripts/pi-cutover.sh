#!/usr/bin/env bash
# One-shot cutover on the Pi: permissions, env paths, units, deploy, import.
#
#   ./scripts/pi-cutover.sh /tmp/league_export.json
#
# Run as nate from the checkout. Idempotent; re-run if a step fails.
set -euo pipefail

EXPORT=${1:?usage: pi-cutover.sh <league_export.json>}
APP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=/etc/winspool/env
OWNER=$(stat -c %U "$APP_DIR")
HOME_DIR=$(getent passwd "$OWNER" | cut -d: -f6)

[[ -f $EXPORT ]] || { echo "no such file: $EXPORT" >&2; exit 1; }

echo "==> let the winspool user read $APP_DIR"
sudo usermod -aG "$OWNER" winspool
sudo chmod 750 "$HOME_DIR"

echo "==> point $ENV_FILE at $APP_DIR"
sudo sed -i -E "s#^(WINSPOOL_DATA_DIR)=.*#\1=$APP_DIR/data/cache#; s#^(WINSPOOL_WEB_DIST)=.*#\1=$APP_DIR/web/dist#" "$ENV_FILE"
sudo grep -E '^WINSPOOL_(DATA_DIR|WEB_DIST)=' "$ENV_FILE"

echo "==> install units"
sudo APP_DIR="$APP_DIR" "$APP_DIR/scripts/pi-setup.sh"

echo "==> deploy"
"$APP_DIR/scripts/pi-deploy.sh"

echo "==> import $EXPORT"
# The import runs as winspool, which cannot read a 600 file owned by nate.
STAGED=/var/lib/winspool/import.json
sudo install -o winspool -g winspool -m 600 "$EXPORT" "$STAGED"
sudo -u winspool env $(sudo grep -v '^#' "$ENV_FILE" | xargs) \
  "$APP_DIR/.venv/bin/winspool" import --from "$STAGED" --force
sudo rm -f "$STAGED"
sudo systemctl restart winspool
sleep 2
curl -fsS http://127.0.0.1:8080/api/teams >/dev/null && echo "==> app healthy"
rm -f "$EXPORT"
echo "==> done. next: switch nameservers, then: sudo systemctl start winspool-scores.service"
