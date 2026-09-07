#!/usr/bin/env bash
# Deploy the current main onto the Pi: pull, rebuild, restart, health-check.
#
#   ssh pi 'sudo /opt/winspool/scripts/pi-deploy.sh'
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/winspool}
PORT=${PORT:-8080}
BRANCH=${BRANCH:-main}

cd "$APP_DIR"

echo "==> pulling $BRANCH"
git fetch --quiet origin "$BRANCH"
git checkout --quiet "$BRANCH"
git merge --ff-only "origin/$BRANCH"
echo "    now at $(git rev-parse --short HEAD) $(git log -1 --format=%s)"

echo "==> python deps"
uv sync --extra dev

echo "==> web build"
(cd web && npm ci --silent && npm run build)

echo "==> restarting"
systemctl restart winspool

echo -n "==> waiting for health"
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/api/teams" >/dev/null 2>&1; then
    echo " ok (${i}s)"
    exit 0
  fi
  echo -n "."
  sleep 1
done

echo " FAILED"
echo "--- last 40 log lines ---"
journalctl -u winspool -n 40 --no-pager
exit 1
