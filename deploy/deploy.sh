#!/usr/bin/env bash
#
# deploy.sh — one-stop deploy for the OpenBench `general-chat` example.
#
# Architecture (see deploy/DEPLOY.md for the full runbook):
#   browser → Firebase Hosting (SPA) → https://<sslip host> (VM nginx, TLS)
#           → openbench-api container (127.0.0.1:8080) on the GCE VM
#   auth = Firebase Google ID token + email allowlist (enforced in the API)
#
# Usage:
#   bash deploy/deploy.sh <command>
#
# Commands:
#   backend        Build the API image (Cloud Build) and roll it out on the VM
#   frontend       Build the SPA and deploy it to Firebase Hosting
#   mcp-image      Build the forked db_server MCP image (Cloud Build) + pull on VM
#   nginx          Sync compose + nginx reverse-proxy config to the VM, reload nginx
#   add-user EMAIL    Add an email to the backend allowlist and restart the API
#   remove-user EMAIL Remove an email from the backend allowlist and restart the API
#   init-appdb     Create the appdata DB + mart schema + mcp_app role on Cloud SQL
#   seed-mcp-db FILE  Load a .sql file into the appdata Postgres DB (db_server data)
#   verify         Probe the live deployment (health/auth/hardening/network)
#   all            backend → frontend → verify
#   help           Print this help + the resource inventory
#
# Requirements (on PATH): gcloud, firebase, pnpm, ssh (via gcloud). Run from
# git-bash / WSL / Cloud Shell. Secrets (GOOGLE_API_KEY, DB password, OAuth
# secret) live only in the VM's .env.gcp — never here.
#
# Every value below can be overridden by an env var or by an optional, git-
# ignored deploy/deploy.env (sourced if present). The VITE_FIREBASE_* values
# are the public web-app config (shipped in the JS bundle) — not secrets.

set -euo pipefail

# --- locate repo root (this script lives in <repo>/deploy) -------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# --- optional local overrides ------------------------------------------------
# shellcheck disable=SC1091
[ -f "$SCRIPT_DIR/deploy.env" ] && source "$SCRIPT_DIR/deploy.env"

# --- configuration (override via env or deploy/deploy.env) -------------------
PROJECT_ID="${PROJECT_ID:-sss-poc1-corporate}"
REGION="${REGION:-us-central1}"
IMAGE="${IMAGE:-us-central1-docker.pkg.dev/sss-poc1-corporate/openbench/general-chat:latest}"
CLOUDBUILD_CONFIG="${CLOUDBUILD_CONFIG:-cloudbuild.general-chat.yaml}"

# db_server MCP data lives in Cloud SQL (appdata). init/seed run psql from a
# throwaway container joined to the shared docker network.
PSQL_IMAGE="${PSQL_IMAGE:-postgres:16}"
APPNET="${APPNET:-openbench-appnet}"

# db_server MCP forked image (Postgres + materialize): source dir + Cloud Build.
MCP_IMAGE="${MCP_IMAGE:-us-central1-docker.pkg.dev/sss-poc1-corporate/openbench/mcp-db-server:1.3.1-ob1}"
MCP_CLOUDBUILD_CONFIG="${MCP_CLOUDBUILD_CONFIG:-cloudbuild.mcp-db-server.yaml}"
MCP_IMAGE_DIR="${MCP_IMAGE_DIR:-examples/general-chat/mcp/db-server}"

VM_NAME="${VM_NAME:-openbench-general-chat}"
VM_ZONE="${VM_ZONE:-us-central1-a}"
VM_DEPLOY_DIR="${VM_DEPLOY_DIR:-/home/Admin/openbench-deploy}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.gce.yml}"

PUBLIC_HOST="${PUBLIC_HOST:-35-188-138-52.sslip.io}"
API_URL="${API_URL:-https://$PUBLIC_HOST}"
VM_PUBLIC_IP="${VM_PUBLIC_IP:-35.188.138.52}"
HOSTING_URL="${HOSTING_URL:-https://sss-poc1-corporate.web.app}"

FRONTEND_DIR="${FRONTEND_DIR:-examples/general-chat/frontend}"
CHATUI_DIR="${CHATUI_DIR:-studio/chat-ui}"
FIREBASE_DIR="${FIREBASE_DIR:-examples/general-chat}"
NGINX_CONF="${NGINX_CONF:-deploy/nginx-openbench-api.conf}"
NGINX_SITE_PATH="${NGINX_SITE_PATH:-/etc/nginx/sites-available/openbench-api}"

# Public Firebase web-app config (baked into the SPA bundle; not secret).
export VITE_BACKEND_URL="${VITE_BACKEND_URL:-$API_URL}"
export VITE_FIREBASE_API_KEY="${VITE_FIREBASE_API_KEY:-AIzaSyBQgUsMi2ctcnMzt13SfUoHkjctS-BOG3o}"
export VITE_FIREBASE_AUTH_DOMAIN="${VITE_FIREBASE_AUTH_DOMAIN:-sss-poc1-corporate.firebaseapp.com}"
export VITE_FIREBASE_PROJECT_ID="${VITE_FIREBASE_PROJECT_ID:-sss-poc1-corporate}"
export VITE_FIREBASE_STORAGE_BUCKET="${VITE_FIREBASE_STORAGE_BUCKET:-sss-poc1-corporate.firebasestorage.app}"
export VITE_FIREBASE_MESSAGING_SENDER_ID="${VITE_FIREBASE_MESSAGING_SENDER_ID:-920070146333}"
export VITE_FIREBASE_APP_ID="${VITE_FIREBASE_APP_ID:-1:920070146333:web:1ebd29612bfe6a4d04f9f4}"
export VITE_FIREBASE_MEASUREMENT_ID="${VITE_FIREBASE_MEASUREMENT_ID:-G-8V67WBHK4K}"

# gcloud/firebase may be .cmd shims on Windows git-bash.
GCLOUD="${GCLOUD:-gcloud}"; command -v "$GCLOUD" >/dev/null 2>&1 || GCLOUD="gcloud.cmd"
FIREBASE="${FIREBASE:-firebase}"; command -v "$FIREBASE" >/dev/null 2>&1 || FIREBASE="firebase.cmd"
PNPM="${PNPM:-pnpm}"; command -v "$PNPM" >/dev/null 2>&1 || PNPM="pnpm.cmd"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  OK %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  !! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  XX %s\033[0m\n' "$*" >&2; exit 1; }

# Run a command on the VM over SSH.
vm_ssh() { "$GCLOUD" compute ssh "$VM_NAME" --zone "$VM_ZONE" --command="$1"; }

# HTTP status of a URL. Uses curl on Linux/Cloud Shell. On Windows git-bash the
# bundled Schannel curl errors (43) on some hostnames, so fall back to PowerShell
# Invoke-WebRequest when curl can't get a code.
http_code() {
  local url="$1" t="${2:-20}" code
  code="$(curl -s -o /dev/null -w '%{http_code}' --ssl-no-revoke --max-time "$t" "$url" 2>/dev/null || true)"
  if [ -z "$code" ] || [ "$code" = "000" ]; then
    if command -v powershell.exe >/dev/null 2>&1; then
      code="$(powershell.exe -NoProfile -Command "try { (Invoke-WebRequest -Uri '$url' -UseBasicParsing -TimeoutSec $t).StatusCode } catch { if (\$_.Exception.Response) { [int]\$_.Exception.Response.StatusCode } else { 0 } }" 2>/dev/null | tr -d '\r' || echo 0)"
    fi
  fi
  printf '%s' "${code:-000}"
}

# --- backend -----------------------------------------------------------------
cmd_backend() {
  log "Building API image via Cloud Build ($IMAGE)"
  local build_id
  build_id="$("$GCLOUD" builds submit --async --config "$CLOUDBUILD_CONFIG" . \
    --format='value(id)')" || die "Cloud Build submit failed"
  [ -n "$build_id" ] || die "Could not capture Cloud Build id"
  ok "submitted build $build_id — polling"

  local status=""
  while :; do
    status="$("$GCLOUD" builds describe "$build_id" --format='value(status)' 2>/dev/null || echo '')"
    case "$status" in
      SUCCESS) ok "build $build_id SUCCESS"; break ;;
      FAILURE|TIMEOUT|CANCELLED|EXPIRED) die "build $build_id ended: $status" ;;
      *) printf '  ... %s\n' "${status:-pending}"; sleep 15 ;;
    esac
  done

  log "Rolling out new image on the VM ($VM_NAME)"
  vm_ssh "cd $VM_DEPLOY_DIR && sudo docker pull $IMAGE && sudo docker-compose --env-file .env.gcp -f $COMPOSE_FILE up -d" \
    || die "VM rollout failed"

  log "Waiting for API to come healthy (boot can take ~60s)"
  local tries=0
  until [ "$(http_code "$API_URL/health")" = "200" ]; do
    tries=$((tries+1)); [ "$tries" -gt 40 ] && die "API did not become healthy at $API_URL/health"
    printf '  ... booting\n'; sleep 5
  done
  ok "API healthy at $API_URL/health"
}

# --- mcp-image ---------------------------------------------------------------
# Build the forked db_server MCP image (Postgres + materialize) via Cloud Build
# and pull it on the VM so the API can spawn it with `docker run`.
cmd_mcp_image() {
  log "Building db_server MCP image via Cloud Build ($MCP_IMAGE)"
  local build_id
  build_id="$("$GCLOUD" builds submit --async --config "$MCP_CLOUDBUILD_CONFIG" "$MCP_IMAGE_DIR" \
    --format='value(id)')" || die "Cloud Build submit failed"
  [ -n "$build_id" ] || die "Could not capture Cloud Build id"
  ok "submitted build $build_id — polling"

  local status=""
  while :; do
    status="$("$GCLOUD" builds describe "$build_id" --format='value(status)' 2>/dev/null || echo '')"
    case "$status" in
      SUCCESS) ok "build $build_id SUCCESS"; break ;;
      FAILURE|TIMEOUT|CANCELLED|EXPIRED) die "build $build_id ended: $status" ;;
      *) printf '  ... %s\n' "${status:-pending}"; sleep 15 ;;
    esac
  done

  log "Pulling MCP image on the VM ($VM_NAME)"
  vm_ssh "sudo docker pull $MCP_IMAGE" || die "VM pull of $MCP_IMAGE failed"
  ok "db_server MCP image ready on the VM"
}

# --- frontend ----------------------------------------------------------------
cmd_frontend() {
  log "Building workspace SDK ($CHATUI_DIR) so the SPA bundles the latest chat-ui"
  "$PNPM" -C "$CHATUI_DIR" build || die "chat-ui build failed"
  # pnpm caches file: deps as a store copy keyed by path, not content, so a
  # changed dist is NOT picked up without a forced reinstall.
  "$PNPM" -C "$FRONTEND_DIR" install --force || die "frontend dep refresh failed"
  ok "rebuilt $CHATUI_DIR/dist and refreshed the SPA dep"

  log "Building SPA ($FRONTEND_DIR) → VITE_BACKEND_URL=$VITE_BACKEND_URL"
  "$PNPM" -C "$FRONTEND_DIR" build || die "frontend build failed"
  ok "built $FRONTEND_DIR/dist"

  log "Deploying to Firebase Hosting (project $PROJECT_ID)"
  ( cd "$FIREBASE_DIR" && "$FIREBASE" deploy --only hosting --project "$PROJECT_ID" ) \
    || die "firebase deploy failed"
  ok "Hosting deployed → $HOSTING_URL"
}

# --- nginx + compose sync ----------------------------------------------------
cmd_nginx() {
  log "Syncing compose + nginx config to the VM"
  "$GCLOUD" compute scp "$COMPOSE_FILE" "$VM_NAME:$VM_DEPLOY_DIR/$COMPOSE_FILE" --zone "$VM_ZONE" \
    || die "scp compose failed"
  "$GCLOUD" compute scp "$NGINX_CONF" "$VM_NAME:/tmp/openbench-api.nginx" --zone "$VM_ZONE" \
    || die "scp nginx conf failed"
  vm_ssh "sudo cp $NGINX_SITE_PATH ${NGINX_SITE_PATH}.bak-\$(date +%s) 2>/dev/null; sudo cp /tmp/openbench-api.nginx $NGINX_SITE_PATH && sudo nginx -t && sudo systemctl reload nginx && echo NGINX_RELOADED" \
    || die "nginx reload failed"
  ok "nginx reloaded"
}

# --- add-user ----------------------------------------------------------------
cmd_add_user() {
  local email="${1:-}"
  [ -n "$email" ] || die "usage: deploy.sh add-user EMAIL"
  log "Adding $email to GENERAL_CHAT_ALLOWED_EMAILS on the VM"
  # Idempotent: append only if not already present; back up .env.gcp first.
  vm_ssh "cd $VM_DEPLOY_DIR && cp .env.gcp .env.gcp.bak-\$(date +%s) && \
    cur=\$(grep '^GENERAL_CHAT_ALLOWED_EMAILS=' .env.gcp | cut -d= -f2-) && \
    if echo \",\$cur,\" | grep -qi \",$email,\"; then echo ALREADY_PRESENT; \
    else if [ -n \"\$cur\" ]; then new=\"\$cur,$email\"; else new=\"$email\"; fi; \
      sed -i \"s|^GENERAL_CHAT_ALLOWED_EMAILS=.*|GENERAL_CHAT_ALLOWED_EMAILS=\$new|\" .env.gcp && \
      sudo docker-compose --env-file .env.gcp -f $COMPOSE_FILE up -d openbench-api && echo ADDED; fi && \
    grep '^GENERAL_CHAT_ALLOWED_EMAILS=' .env.gcp" \
    || die "add-user failed"
  ok "allowlist updated (API restarting if changed)"
}

# --- remove-user -------------------------------------------------------------
cmd_remove_user() {
  local email="${1:-}"
  [ -n "$email" ] || die "usage: deploy.sh remove-user EMAIL"
  log "Removing $email from GENERAL_CHAT_ALLOWED_EMAILS on the VM"
  # Idempotent: rewrite only if present; back up .env.gcp first. Splits the
  # list on commas and drops the matching entry (any position, no dangling
  # commas) via a case-insensitive whole-line awk filter.
  vm_ssh "cd $VM_DEPLOY_DIR && cp .env.gcp .env.gcp.bak-\$(date +%s) && \
    cur=\$(grep '^GENERAL_CHAT_ALLOWED_EMAILS=' .env.gcp | cut -d= -f2-) && \
    if echo \",\$cur,\" | grep -qi \",$email,\"; then \
      new=\$(echo \"\$cur\" | tr ',' '\n' | awk -v e=\"$email\" 'tolower(\$0)!=tolower(e)' | paste -sd, -); \
      sed -i \"s|^GENERAL_CHAT_ALLOWED_EMAILS=.*|GENERAL_CHAT_ALLOWED_EMAILS=\$new|\" .env.gcp && \
      sudo docker-compose --env-file .env.gcp -f $COMPOSE_FILE up -d openbench-api && echo REMOVED; \
    else echo NOT_PRESENT; fi && \
    grep '^GENERAL_CHAT_ALLOWED_EMAILS=' .env.gcp" \
    || die "remove-user failed"
  ok "allowlist updated (API restarting if changed)"
}

# --- init-appdb --------------------------------------------------------------
# Create the appdata database + mart schema + mcp_app role on Cloud SQL. Runs
# deploy/appdb/roles.sql against a maintenance connection via a throwaway psql
# container on the shared network. Idempotent. Reads secrets from the VM .env.gcp.
cmd_init_appdb() {
  log "Initializing appdata DB + mart schema + mcp_app role"
  "$GCLOUD" compute scp deploy/appdb/roles.sql "$VM_NAME:/tmp/appdb-roles.sql" --zone "$VM_ZONE" \
    || die "scp of roles.sql failed"
  vm_ssh "admin=\$(grep '^APPDATA_ADMIN_URL=' $VM_DEPLOY_DIR/.env.gcp | cut -d= -f2-); \
    mcpurl=\$(grep '^MCP_DB_DATABASE_URL=' $VM_DEPLOY_DIR/.env.gcp | cut -d= -f2-); \
    [ -n \"\$admin\" ] || { echo 'APPDATA_ADMIN_URL missing in .env.gcp'; exit 1; }; \
    maint=\"\${admin%/*}/postgres\"; \
    pw=\$(printf '%s' \"\$mcpurl\" | sed -E 's#.*://[^:]+:([^@]+)@.*#\1#'); \
    sudo docker run --rm -i --network $APPNET $PSQL_IMAGE \
      psql \"\$maint\" -v ON_ERROR_STOP=1 -v mcp_password=\"\$pw\" -f - < /tmp/appdb-roles.sql && \
    rm -f /tmp/appdb-roles.sql && echo INITED" \
    || die "init-appdb failed"
  ok "appdata + mart + mcp_app ready"
}

# --- seed-mcp-db -------------------------------------------------------------
# Load a .sql file into the appdata Postgres DB (the db_server MCP data). Copies
# the file to the VM and applies it with a throwaway psql container on the shared
# network, using the admin connection from .env.gcp. This is the ".sql" data path
# (DBeaver over a local cloud-sql-proxy is the manual path — see DEPLOY.md).
cmd_seed_mcp_db() {
  local file="${1:-}"
  [ -n "$file" ] || die "usage: deploy.sh seed-mcp-db FILE.sql"
  [ -f "$file" ] || die "no such file: $file"
  log "Seeding appdata (Postgres) on the VM from $file"
  "$GCLOUD" compute scp "$file" "$VM_NAME:/tmp/appdb-seed.sql" --zone "$VM_ZONE" \
    || die "scp of seed file failed"
  vm_ssh "admin=\$(grep '^APPDATA_ADMIN_URL=' $VM_DEPLOY_DIR/.env.gcp | cut -d= -f2-); \
    [ -n \"\$admin\" ] || { echo 'APPDATA_ADMIN_URL missing in .env.gcp'; exit 1; }; \
    sudo docker run --rm -i --network $APPNET $PSQL_IMAGE \
      psql \"\$admin\" -v ON_ERROR_STOP=1 -f - < /tmp/appdb-seed.sql && \
    rm -f /tmp/appdb-seed.sql && echo SEEDED" \
    || die "seed failed"
  ok "appdata seeded — db_server reads it live"
}

# --- verify ------------------------------------------------------------------
cmd_verify() {
  log "Verifying live deployment"
  local fail=0
  check() { # name url expected
    local code; code="$(http_code "$2")"
    if [ "$code" = "$3" ]; then ok "$1: $code"; else warn "$1: got $code, want $3"; fail=1; fi
  }
  check "API /health (public)"        "$API_URL/health"       "200"
  check "API /persona (no token)"     "$API_URL/persona"      "401"
  check "API /openapi.json (hardened)" "$API_URL/openapi.json" "404"
  check "Hosting SPA"                  "$HOSTING_URL"          "200"
  # 8080 must NOT be publicly reachable (expect connection failure → 000).
  local raw; raw="$(http_code "http://$VM_PUBLIC_IP:8080/health" 8)"
  if [ "$raw" = "000" ] || [ "$raw" = "0" ]; then ok "raw :8080 unreachable (private)"; else warn "raw :8080 reachable ($raw) — should be private"; fail=1; fi
  [ "$fail" -eq 0 ] && ok "all checks passed" || die "one or more checks failed"
}

# --- help --------------------------------------------------------------------
cmd_help() {
  # Print the leading comment header (stop at the first non-comment line).
  awk 'NR>1 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"
  cat <<EOF

Resource inventory:
  Project        $PROJECT_ID ($REGION)
  Image          $IMAGE
  Cloud Build    $CLOUDBUILD_CONFIG
  VM             $VM_NAME ($VM_ZONE), dir $VM_DEPLOY_DIR
  Compose        $COMPOSE_FILE  (openbench-api @127.0.0.1:8080 + openbench-worker)
  TLS front door $API_URL  (host nginx → 127.0.0.1:8080, Let's Encrypt)
  Hosting SPA    $HOSTING_URL  (from $FRONTEND_DIR/dist)
  Runbook        deploy/DEPLOY.md
EOF
}

# --- dispatch ----------------------------------------------------------------
case "${1:-help}" in
  backend)  cmd_backend ;;
  frontend) cmd_frontend ;;
  mcp-image) cmd_mcp_image ;;
  nginx)    cmd_nginx ;;
  add-user) shift; cmd_add_user "${1:-}" ;;
  remove-user) shift; cmd_remove_user "${1:-}" ;;
  init-appdb) cmd_init_appdb ;;
  seed-mcp-db) shift; cmd_seed_mcp_db "${1:-}" ;;
  verify)   cmd_verify ;;
  all)      cmd_backend; cmd_frontend; cmd_verify ;;
  help|-h|--help) cmd_help ;;
  *) die "unknown command '$1' (try: backend|frontend|mcp-image|nginx|add-user|remove-user|init-appdb|seed-mcp-db|verify|all|help)" ;;
esac
