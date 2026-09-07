#!/usr/bin/env bash
set -euo pipefail
PROJECT=snowpack-pika
REGION=us-west1
SERVICE=pika
: "${SESSION_SECRET:?set SESSION_SECRET}"
: "${REFRESH_TOKEN:?set REFRESH_TOKEN}"

REPO_ROOT="$(git rev-parse --show-toplevel)"
TMP=$(mktemp -d)
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

git archive HEAD | tar -x -C "$TMP"
printf '.git\n.gcloudignore\nweb/node_modules\n.venv\nvenv\n' > "$TMP/.gcloudignore"
cd "$TMP"

gcloud run deploy "$SERVICE" \
  --project "$PROJECT" --region "$REGION" --source . \
  --quiet \
  --allow-unauthenticated \
  --min-instances 1 --max-instances 1 --memory 768Mi --cpu 1 \
  --port 8080 \
  --set-env-vars "STORE=firestore,GOOGLE_CLOUD_PROJECT=$PROJECT,SESSION_SECRET=$SESSION_SECRET,REFRESH_TOKEN=$REFRESH_TOKEN"
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)'
