#!/usr/bin/env bash
# ============================================================
# Deploy Controlled Source Chat → Google Cloud Run
#
#   bash examples/controlled-source-chat/deploy.sh all      # image + run + verify
#   bash examples/controlled-source-chat/deploy.sh image    # build image (Cloud Build)
#   bash examples/controlled-source-chat/deploy.sh run      # deploy/refresh Cloud Run service
#   bash examples/controlled-source-chat/deploy.sh verify   # probe the live service
#
# Architecture + one-time setup: see DEPLOY.md next to this script.
# Secrets come from the gitignored examples/controlled-source-chat/.env:
#   GOOGLE_API_KEY               (falls back to ../general-chat/.env)
#   GENERAL_CHAT_DATABASE_URL    (Cloud SQL socket URL, database controlled_chat)
#   CONTROLLED_CHAT_AUTH_SECRET  (pins HMAC tokens across restarts)
#   TAVILY_API_KEY               (optional)
# ============================================================

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-sss-poc1-corporate}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-controlled-source-chat}"
IMAGE="${IMAGE:-us-central1-docker.pkg.dev/${PROJECT_ID}/openbench/controlled-source-chat:latest}"
CLOUDBUILD_CONFIG="cloudbuild.controlled-source-chat.yaml"
SQL_CONNECTION="${SQL_CONNECTION:-sss-poc1-corporate:us-central1:openbench-postgres}"
MEMORY="${MEMORY:-2Gi}"
CPU="${CPU:-2}"
TIMEOUT="${TIMEOUT:-300}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
EXAMPLE_DIR="${REPO_ROOT}/examples/controlled-source-chat"
ENV_FILE="${EXAMPLE_DIR}/.env"
FALLBACK_ENV_FILE="${REPO_ROOT}/examples/general-chat/.env"

# gcloud may be a .cmd shim on Windows git-bash.
GCLOUD="${GCLOUD:-gcloud}"; command -v "$GCLOUD" >/dev/null 2>&1 || GCLOUD="gcloud.cmd"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  OK %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  !! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  XX %s\033[0m\n' "$*" >&2; exit 1; }

# Read KEY=value from an env file (first match, strips CR).
# `|| true` keeps a missing key from tripping set -e/pipefail.
env_value() {
  local key="$1" file="$2"
  [ -f "$file" ] || return 0
  (grep -E "^${key}=" "$file" || true) | head -n1 | cut -d= -f2- | tr -d '\r'
}

service_url() {
  "$GCLOUD" run services describe "$SERVICE_NAME" --project "$PROJECT_ID" \
    --region "$REGION" --format='value(status.url)' 2>/dev/null || true
}

# --- image -------------------------------------------------------------------
cmd_image() {
  log "Building image via Cloud Build ($IMAGE)"
  cd "$REPO_ROOT"
  local build_id
  build_id="$("$GCLOUD" builds submit --async --project "$PROJECT_ID" \
    --config "$CLOUDBUILD_CONFIG" . --format='value(id)')" || die "Cloud Build submit failed"
  [ -n "$build_id" ] || die "Could not capture Cloud Build id"
  ok "submitted build $build_id — polling"

  local status=""
  while :; do
    status="$("$GCLOUD" builds describe "$build_id" --project "$PROJECT_ID" \
      --format='value(status)' 2>/dev/null || echo '')"
    case "$status" in
      SUCCESS) ok "build $build_id SUCCESS"; break ;;
      FAILURE|TIMEOUT|CANCELLED|EXPIRED) die "build $build_id ended: $status" ;;
      *) printf '  ... %s\n' "${status:-pending}"; sleep 15 ;;
    esac
  done
}

# --- run ---------------------------------------------------------------------
cmd_run() {
  log "Deploying Cloud Run service ($SERVICE_NAME @ $REGION)"

  local google_api_key database_url auth_secret tavily_key
  google_api_key="$(env_value GOOGLE_API_KEY "$ENV_FILE")"
  [ -n "$google_api_key" ] || google_api_key="$(env_value GOOGLE_API_KEY "$FALLBACK_ENV_FILE")"
  [ -n "$google_api_key" ] || die "GOOGLE_API_KEY not found in $ENV_FILE or $FALLBACK_ENV_FILE"
  database_url="$(env_value GENERAL_CHAT_DATABASE_URL "$ENV_FILE")"
  [ -n "$database_url" ] || die "GENERAL_CHAT_DATABASE_URL not set in $ENV_FILE (see DEPLOY.md one-time setup)"
  auth_secret="$(env_value CONTROLLED_CHAT_AUTH_SECRET "$ENV_FILE")"
  [ -n "$auth_secret" ] || die "CONTROLLED_CHAT_AUTH_SECRET not set in $ENV_FILE (openssl rand -hex 32)"
  tavily_key="$(env_value TAVILY_API_KEY "$ENV_FILE")"
  [ -n "$tavily_key" ] || tavily_key="$(env_value TAVILY_API_KEY "$FALLBACK_ENV_FILE")"

  # ^##^ delimiter: values (DB URL) may contain commas/colons.
  local env_vars="GOOGLE_API_KEY=${google_api_key}"
  env_vars="${env_vars}##GENERAL_CHAT_DATABASE_URL=${database_url}"
  env_vars="${env_vars}##CONTROLLED_CHAT_AUTH_SECRET=${auth_secret}"
  if [ -n "$tavily_key" ]; then env_vars="${env_vars}##TAVILY_API_KEY=${tavily_key}"; fi

  "$GCLOUD" run deploy "$SERVICE_NAME" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --image "$IMAGE" \
    --allow-unauthenticated \
    --memory "$MEMORY" \
    --cpu "$CPU" \
    --timeout "$TIMEOUT" \
    --max-instances 1 \
    --add-cloudsql-instances "$SQL_CONNECTION" \
    --set-env-vars "^##^${env_vars}" \
    || die "Cloud Run deploy failed"

  local url; url="$(service_url)"
  ok "service deployed: $url"
}

# --- verify ------------------------------------------------------------------
cmd_verify() {
  local url; url="$(service_url)"
  [ -n "$url" ] || die "Service $SERVICE_NAME not found in $REGION"
  log "Verifying $url"

  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$url/health")"
  [ "$code" = "200" ] || die "/health returned $code (expected 200)"
  ok "/health 200"

  local index
  index="$(curl -s --max-time 60 "$url/")"
  echo "$index" | grep -qi '<div id="root">' || die "/ did not return the SPA shell"
  ok "/ serves the SPA"
  if echo "$index" | grep -q 'admin123'; then die "login page still leaks demo credentials"; fi
  ok "no credential hint in page"

  local token
  token="$(curl -s --max-time 60 -X POST "$url/auth/login" \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"admin123"}' | \
    python -c 'import json,sys; print(json.load(sys.stdin).get("token",""))' 2>/dev/null || true)"
  [ -n "$token" ] || die "admin login failed"
  ok "admin login issues token"

  # Assert JSON bodies, not just status codes: the SPA catch-all serves
  # index.html with 200 for unknown GET paths, which once masked a route-order
  # bug that shadowed these endpoints.
  local me_user
  me_user="$(curl -s --max-time 60 -H "Authorization: Bearer $token" "$url/auth/me" | \
    python -c 'import json,sys; print(json.load(sys.stdin).get("username",""))' 2>/dev/null || true)"
  [ "$me_user" = "admin" ] || die "/auth/me did not return JSON for admin (got: '$me_user')"
  ok "/auth/me returns admin JSON"

  local users_first
  users_first="$(curl -s --max-time 60 -H "Authorization: Bearer $token" "$url/controlled/users" | head -c 1)"
  [ "$users_first" = "[" ] || die "/controlled/users did not return a JSON list"
  ok "/controlled/users returns JSON list"

  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$url/persona")"
  [ "$code" = "401" ] || die "/persona returned $code without token (expected 401)"
  ok "/persona 401 without token"

  ok "verify passed — $url"
}

# --- main --------------------------------------------------------------------
case "${1:-}" in
  image)  cmd_image ;;
  run)    cmd_run ;;
  verify) cmd_verify ;;
  all)    cmd_image; cmd_run; cmd_verify ;;
  *)      echo "Usage: $0 {image|run|verify|all}"; exit 1 ;;
esac
