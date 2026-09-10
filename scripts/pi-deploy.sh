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

BEFORE_HASH=$(sha256sum "$0")

echo "==> pulling $BRANCH"
git fetch --quiet origin "$BRANCH"
git checkout --quiet "$BRANCH"
git merge --ff-only "origin/$BRANCH"
echo "    now at $(git rev-parse --short HEAD) $(git log -1 --format=%s)"

# Bash reads this file incrementally as it executes, so a pull that changes
# this script keeps running the OLD bytes for the rest of the deploy — any
# step added to the script in the same commit would silently never run (this
# happened for real: a systemd-unit-install step that never fired). Re-exec
# the freshly pulled copy so the remaining steps use the new logic. The guard
# variable stops a second re-exec even if the hash is still different next
# time, so a bug here fails fast instead of looping forever.
if [[ "$(sha256sum "$0")" != "$BEFORE_HASH" && -z "${WINSPOOL_DEPLOY_REEXEC:-}" ]]; then
  echo "==> deploy script changed, re-execing"
  exec env APP_DIR="$APP_DIR" PORT="$PORT" BRANCH="$BRANCH" WINSPOOL_DEPLOY_REEXEC=1 "$0" "$@"
fi

echo "==> python deps"
uv sync --extra dev

echo "==> web build"
(cd web && npm ci --silent && npm run build)

# Build the Simulations model before the restart, not after: it is stored, so
# the new process starts with it in hand and never serves a cold build.
echo -n "==> warming the simulation model"
curl -fsS --max-time 180 "http://127.0.0.1:$PORT/api/league/sim-model" >/dev/null 2>&1 \
  && echo " ok" || echo " skipped (will build after restart)"

# Sync units on every deploy, not just first-time setup: a unit added on this
# branch (or any future one) must not need a manual step to start firing.
echo "==> installing systemd units"
$SUDO install -m 644 deploy/pi/*.service deploy/pi/*.timer /etc/systemd/system/
$SUDO systemctl daemon-reload
for f in deploy/pi/*.service deploy/pi/*.timer; do echo "    $(basename "$f")"; done

# Enable timers only, derived from the directory rather than a hardcoded list
# — a hardcoded list is how a newly added timer went silently un-started
# before. The oneshot .service units are triggered by their timers (or, for
# winspool.service, restarted explicitly below); enabling them directly would
# fire them at the wrong moment.
echo "==> enabling timers"
for timer in deploy/pi/*.timer; do
  name=$(basename "$timer")
  $SUDO systemctl enable --now "$name" >/dev/null
  echo "    $name"
done

echo "==> restarting"
$SUDO systemctl restart winspool

echo -n "==> waiting for health"
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/api/teams" >/dev/null 2>&1; then
    echo " ok (${i}s)"
    # Cheap when the pre-restart warm worked; the real build only when it did not.
    curl -fsS --max-time 180 "http://127.0.0.1:$PORT/api/league/sim-model" >/dev/null 2>&1 || true
    exit 0
  fi
  echo -n "."
  sleep 1
done

echo " FAILED"
echo "--- last 40 log lines ---"
$SUDO journalctl -u winspool -n 40 --no-pager
exit 1
