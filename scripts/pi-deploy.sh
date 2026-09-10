#!/usr/bin/env bash
# Deploy the current main onto the Pi: pull, rebuild, restart, health-check.
#
#   ssh pi '/home/nate/awardwinninglisteners/scripts/pi-deploy.sh'
#
# Run as the checkout's owner (nate). git/uv/npm run as that user; only the
# service restart needs sudo. If invoked via sudo it re-execs as the owner.
set -euo pipefail

APP_DIR=${APP_DIR:-/home/nate/awardwinninglisteners}
PORT=${PORT:-8080}
BRANCH=${BRANCH:-main}

cd "$APP_DIR"

OWNER=$(stat -c %U .)
if [[ $EUID -eq 0 && $OWNER != root ]]; then
  exec sudo -u "$OWNER" -H env APP_DIR="$APP_DIR" PORT="$PORT" BRANCH="$BRANCH" "$0" "$@"
fi
SUDO=""; [[ $EUID -eq 0 ]] || SUDO=sudo

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
$SUDO systemctl restart winspool

echo -n "==> waiting for health"
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/api/teams" >/dev/null 2>&1; then
    echo " ok (${i}s)"
    # Build the Simulations model now rather than making the first visitor wait
    # for it. It is stored, so this is a one-off after a restart.
    echo -n "==> warming the simulation model"
    curl -fsS --max-time 120 "http://127.0.0.1:$PORT/api/league/sim-model" >/dev/null 2>&1 \
      && echo " ok" || echo " skipped"
    exit 0
  fi
  echo -n "."
  sleep 1
done

echo " FAILED"
echo "--- last 40 log lines ---"
$SUDO journalctl -u winspool -n 40 --no-pager
exit 1
