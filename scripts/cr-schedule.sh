#!/usr/bin/env bash
# Cloud Scheduler jobs that keep the Cloud Run deployment fresh.
#   refresh-standings: real wins from nfl_data_py    (~1s)
#   refresh-live:      in-season projection + views  (~1s warm, ~10s cold)
# Game days (Sun/Mon/Thu) every 15 min, other days every 4 h; live runs 5 min
# after standings. Idempotent: creates or updates. Reads the refresh token from
# the running service so it never has to be typed.
#   scripts/cr-schedule.sh          # create/update all four jobs
#   make cr-refresh                 # trigger standings + live right now
set -euo pipefail
PROJECT=snowpack-pika
REGION=us-west1
SERVICE=pika
TZ_NAME=America/Los_Angeles

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')
TOKEN=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format json \
  | python3 -c 'import json,sys; env=json.load(sys.stdin)["spec"]["template"]["spec"]["containers"][0]["env"]; print(next(e["value"] for e in env if e["name"]=="REFRESH_TOKEN"))')
[ -n "$TOKEN" ] || { echo "REFRESH_TOKEN not set on $SERVICE" >&2; exit 1; }

upsert() {  # name schedule path deadline
  local name=$1 schedule=$2 path=$3 deadline=$4 verb=create hdr=--headers
  if gcloud scheduler jobs describe "$name" --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
    verb=update; hdr=--update-headers
  fi
  gcloud scheduler jobs "$verb" http "$name" \
    --project "$PROJECT" --location "$REGION" \
    --schedule "$schedule" --time-zone "$TZ_NAME" \
    --uri "$URL$path" --http-method POST \
    "$hdr" "X-Refresh-Token=$TOKEN" \
    --attempt-deadline "$deadline" --quiet >/dev/null
  echo "  $verb  $name  '$schedule'  $path"
}

echo "scheduling against $URL"
upsert pika-scores-gameday '*/15 * * * 0,1,4'   /internal/refresh-standings 120s
upsert pika-scores-offday  '0 */4 * * 2,3,5,6'   /internal/refresh-standings 120s
upsert pika-live-gameday   '5-59/15 * * * 0,1,4' /internal/refresh-live      600s
upsert pika-live-offday    '5 */4 * * 2,3,5,6'   /internal/refresh-live      600s
