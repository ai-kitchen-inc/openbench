#!/usr/bin/env bash
#
# deploy.sh — one-stop deploy for the OpenBench `general-chat` (SSS) example.
#
# Architecture (see deploy/DEPLOY.md for the full runbook):
#   browser → https://chat.serebrum.co.id (VM nginx, TLS)
#           → openbench-api container (127.0.0.1:8080) on the GCE VM
#             which serves BOTH the API and the SPA (single origin,
#             GENERAL_CHAT_STATIC_DIR baked into the image)
#   auth = Firebase Google ID token (sign-in only) + `openbench_users`
#          role table managed from the in-app admin panel
#
# Usage:
#   bash deploy/deploy.sh <command>
#
# Commands:
#   backend        Build API+SPA image (Cloud Build) and roll it out on the VM
#   frontend       Alias of backend — the SPA ships inside the API image
#   mcp-image      Build the forked db_server MCP image (Cloud Build) + pull on VM
#   fn-image       Build the custom_function MCP image (Cloud Build) + pull on VM
#   grafana        Provision + start the self-hosted Grafana on the VM (subpath /grafana/)
#   nginx          Sync compose + nginx reverse-proxy config to the VM, reload nginx
#   add-user EMAIL [ROLE]  Break-glass: upsert a user row (openbench_users) via psql.
#                  Primary flow is the in-app admin panel (Pengguna page).
#   remove-user EMAIL      Break-glass: delete a user row via psql
#   init-appdb     Create the appdata DB + mart schema + mcp_app role on Cloud SQL
#   seed-mcp-db FILE  Load a .sql file into the appdata Postgres DB (db_server data)
#   wipe-chat-data DESTRUCTIVE: drop all chat sessions/memory/sources/uploads
#   backups        Enable + verify Cloud SQL automated backups + PITR (idempotent)
#   verify         Probe the live deployment (health/auth/hardening/network)
#   all            backend → verify
#   help           Print this help + the resource inventory
#
# Requirements (on PATH): gcloud, ssh (via gcloud). Run from
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
# throwaway container that reaches Cloud SQL over its public IP (same path the
# app already uses), so no special docker network is needed.
PSQL_IMAGE="${PSQL_IMAGE:-postgres:16}"

# Shared Cloud SQL instance hosting the `openbench` (chat), `controlled_chat`,
# and `appdata` databases — target of `deploy.sh backups`.
SQL_INSTANCE="${SQL_INSTANCE:-openbench-postgres}"

# db_server MCP forked image (Postgres + materialize): source dir + Cloud Build.
MCP_IMAGE="${MCP_IMAGE:-us-central1-docker.pkg.dev/sss-poc1-corporate/openbench/mcp-db-server:1.3.1-ob1}"
MCP_CLOUDBUILD_CONFIG="${MCP_CLOUDBUILD_CONFIG:-cloudbuild.mcp-db-server.yaml}"
MCP_IMAGE_DIR="${MCP_IMAGE_DIR:-examples/general-chat/mcp/db-server}"

# custom_function MCP (sandboxed user Python): source dir + Cloud Build.
FN_IMAGE="${FN_IMAGE:-us-central1-docker.pkg.dev/sss-poc1-corporate/openbench/custom-function-mcp:0.1.0}"
FN_CLOUDBUILD_CONFIG="${FN_CLOUDBUILD_CONFIG:-cloudbuild.custom-function-mcp.yaml}"
FN_IMAGE_DIR="${FN_IMAGE_DIR:-mcp/custom-function-mcp}"

VM_NAME="${VM_NAME:-openbench-general-chat}"
VM_ZONE="${VM_ZONE:-us-central1-a}"
VM_DEPLOY_DIR="${VM_DEPLOY_DIR:-/home/Admin/openbench-deploy}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.gce.yml}"

PUBLIC_HOST="${PUBLIC_HOST:-chat.serebrum.co.id}"
API_URL="${API_URL:-https://$PUBLIC_HOST}"
VM_PUBLIC_IP="${VM_PUBLIC_IP:-34.135.198.188}"

FRONTEND_DIR="${FRONTEND_DIR:-examples/general-chat/frontend}"
CHATUI_DIR="${CHATUI_DIR:-studio/chat-ui}"
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

# gcloud may be a .cmd shim on Windows git-bash.
GCLOUD="${GCLOUD:-gcloud}"; command -v "$GCLOUD" >/dev/null 2>&1 || GCLOUD="gcloud.cmd"

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
  log "Building API+SPA image via Cloud Build ($IMAGE)"
  # Firebase web config (public, not secret) is baked into the SPA bundle.
  local subs="_VITE_FIREBASE_API_KEY=$VITE_FIREBASE_API_KEY"
  subs="$subs,_VITE_FIREBASE_AUTH_DOMAIN=$VITE_FIREBASE_AUTH_DOMAIN"
  subs="$subs,_VITE_FIREBASE_PROJECT_ID=$VITE_FIREBASE_PROJECT_ID"
  subs="$subs,_VITE_FIREBASE_APP_ID=$VITE_FIREBASE_APP_ID"
  local build_id
  build_id="$("$GCLOUD" builds submit --async --config "$CLOUDBUILD_CONFIG" . \
    --substitutions "$subs" \
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

# --- fn-image ------------------------------------------------------------------
# Build the custom_function MCP image (sandboxed user Python) via Cloud Build,
# pull it on the VM, and ensure the functions volume dir exists.
cmd_fn_image() {
  log "Building custom_function MCP image via Cloud Build ($FN_IMAGE)"
  local build_id
  build_id="$("$GCLOUD" builds submit --async --config "$FN_CLOUDBUILD_CONFIG" "$FN_IMAGE_DIR" \
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

  log "Pulling custom_function image on the VM ($VM_NAME)"
  vm_ssh "sudo docker pull $FN_IMAGE && sudo mkdir -p /app-data/custom-functions" \
    || die "VM pull of $FN_IMAGE failed"
  ok "custom_function MCP image + functions dir ready on the VM"
}

# --- grafana -------------------------------------------------------------------
# Provision + start the self-hosted Grafana (nginx serves it at /grafana/).
# Idempotent: generates missing env keys on the VM, syncs datasource
# provisioning + compose, (re)starts the container, waits for /api/health.
cmd_grafana() {
  log "Syncing Grafana provisioning + compose to the VM"
  "$GCLOUD" compute scp deploy/grafana/datasources.yaml "$VM_NAME:/tmp/grafana-datasources.yaml" --zone "$VM_ZONE" \
    || die "scp of datasources.yaml failed"
  "$GCLOUD" compute scp "$COMPOSE_FILE" "$VM_NAME:$VM_DEPLOY_DIR/$COMPOSE_FILE" --zone "$VM_ZONE" \
    || die "scp of compose file failed"

  log "Preparing env + volumes and starting Grafana"
  vm_ssh "set -e; cd $VM_DEPLOY_DIR && \
    sudo mkdir -p /app-data/grafana && sudo chown -R 472:472 /app-data/grafana && \
    mkdir -p grafana-provisioning && mv /tmp/grafana-datasources.yaml grafana-provisioning/datasources.yaml && \
    cp .env.gcp .env.gcp.bak-grafana-\$(date +%Y%m%d-%H%M%S) && \
    grep -q '^GRAFANA_ADMIN_PASSWORD=' .env.gcp || echo \"GRAFANA_ADMIN_PASSWORD=\$(openssl rand -hex 16)\" >> .env.gcp; \
    grep -q '^GRAFANA_PG_PASSWORD=' .env.gcp || { \
      pgpw=\$(grep '^MCP_DB_DATABASE_URL=' .env.gcp | sed -E 's#.*://[^:]+:([^@]+)@.*#\1#' | tr -d '\r'); \
      [ -n \"\$pgpw\" ] || { echo 'cannot derive GRAFANA_PG_PASSWORD (MCP_DB_DATABASE_URL missing)'; exit 1; }; \
      echo \"GRAFANA_PG_PASSWORD=\$pgpw\" >> .env.gcp; }; \
    grep -q '^GRAFANA_PUBLIC_URL=' .env.gcp || echo 'GRAFANA_PUBLIC_URL=$API_URL/grafana' >> .env.gcp; \
    sudo docker-compose --env-file .env.gcp -f $COMPOSE_FILE up -d grafana && \
    for i in \$(seq 1 30); do \
      code=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/grafana/api/health || true); \
      code2=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/api/health || true); \
      { [ \"\$code\" = '200' ] || [ \"\$code2\" = '200' ]; } && { echo GRAFANA_HEALTHY; exit 0; }; sleep 3; \
    done; echo 'grafana did not become healthy'; sudo docker logs --tail 30 \$(sudo docker ps -q -f name=grafana); exit 1" \
    || die "grafana rollout failed"
  ok "Grafana healthy on the VM (127.0.0.1:3000, public at $API_URL/grafana/ after 'nginx')"
}

# --- frontend ----------------------------------------------------------------
# Single-origin: the SPA is built inside the API image (Dockerfile stage 1)
# and served by FastAPI via GENERAL_CHAT_STATIC_DIR. Firebase Hosting is no
# longer part of the deployment — this command simply triggers `backend`.
cmd_frontend() {
  warn "SPA ships inside the API image now — running 'backend' instead."
  cmd_backend
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
# Break-glass user management against the `openbench_users` table (chat DB).
# The primary flow is the in-app admin panel (Pengguna page); use this only
# for lockout recovery (e.g. the last admin lost access). Idempotent upsert.
cmd_add_user() {
  local email="${1:-}"
  local role="${2:-admin}"
  [ -n "$email" ] || die "usage: deploy.sh add-user EMAIL [admin|user]"
  case "$role" in admin|user) ;; *) die "role must be 'admin' or 'user'" ;; esac
  local email_lc; email_lc="$(printf '%s' "$email" | tr '[:upper:]' '[:lower:]')"
  log "Upserting $email_lc (role=$role) into openbench_users on Cloud SQL"
  vm_ssh "dburl=\$(grep '^GENERAL_CHAT_DATABASE_URL=' $VM_DEPLOY_DIR/.env.gcp | cut -d= -f2-); \
    [ -n \"\$dburl\" ] || { echo 'GENERAL_CHAT_DATABASE_URL missing in .env.gcp'; exit 1; }; \
    sudo docker run --rm -i $PSQL_IMAGE psql \"\$dburl\" -v ON_ERROR_STOP=1 -c \
      \"INSERT INTO openbench_users (email, role, display_name, created_at, added_by) \
        VALUES ('$email_lc', '$role', '', now()::text, 'deploy.sh') \
        ON CONFLICT (email) DO UPDATE SET role = EXCLUDED.role;\" && echo UPSERTED" \
    || die "add-user failed"
  ok "$email_lc is now role=$role (effective immediately, no restart needed)"
}

# --- remove-user -------------------------------------------------------------
cmd_remove_user() {
  local email="${1:-}"
  [ -n "$email" ] || die "usage: deploy.sh remove-user EMAIL"
  local email_lc; email_lc="$(printf '%s' "$email" | tr '[:upper:]' '[:lower:]')"
  log "Deleting $email_lc from openbench_users on Cloud SQL"
  vm_ssh "dburl=\$(grep '^GENERAL_CHAT_DATABASE_URL=' $VM_DEPLOY_DIR/.env.gcp | cut -d= -f2-); \
    [ -n \"\$dburl\" ] || { echo 'GENERAL_CHAT_DATABASE_URL missing in .env.gcp'; exit 1; }; \
    sudo docker run --rm -i $PSQL_IMAGE psql \"\$dburl\" -v ON_ERROR_STOP=1 -c \
      \"DELETE FROM openbench_users WHERE email = '$email_lc';\" && echo DELETED" \
    || die "remove-user failed"
  ok "$email_lc removed (access revoked immediately)"
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
    sudo docker run --rm -i $PSQL_IMAGE \
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
    sudo docker run --rm -i $PSQL_IMAGE \
      psql \"\$admin\" -v ON_ERROR_STOP=1 -f - < /tmp/appdb-seed.sql && \
    rm -f /tmp/appdb-seed.sql && echo SEEDED" \
    || die "seed failed"
  ok "appdata seeded — db_server reads it live"
}

# --- wipe-chat-data ------------------------------------------------------------
# One-time destructive reset of all per-user chat data (sessions, agent memory,
# sources, uploads, downloads). Used for the user-isolation rollout: the old
# rows have no owner column values and would be invisible/unmigrated, so they
# are dropped instead (decision: wipe, no migration). Leaves published
# dashboards, MCP registry, custom functions, Grafana and image-search data
# untouched. The API containers are stopped during the wipe and restarted.
cmd_wipe_chat_data() {
  log "Wiping chat data (sessions, memory, sources, uploads, downloads) on the VM"
  # The chat database referenced by GENERAL_CHAT_DATABASE_URL may not exist yet
  # (observed in prod: URL points at db 'openbench' that was never created), so
  # create it when missing and only then drop the chat tables.
  vm_ssh "cd $VM_DEPLOY_DIR && \
    sudo docker-compose --env-file .env.gcp -f $COMPOSE_FILE stop openbench-api openbench-worker && \
    dburl=\$(grep '^GENERAL_CHAT_DATABASE_URL=' .env.gcp | cut -d= -f2-); \
    [ -n \"\$dburl\" ] || { echo 'GENERAL_CHAT_DATABASE_URL missing in .env.gcp'; exit 1; }; \
    dbname=\${dburl##*/}; dbname=\${dbname%%\?*}; maint=\"\${dburl%/*}/postgres\"; \
    exists=\$(sudo docker run --rm -i $PSQL_IMAGE psql \"\$maint\" -tAc \
      \"SELECT 1 FROM pg_database WHERE datname='\$dbname'\") || exit 1; \
    if [ \"\$exists\" != \"1\" ]; then \
      echo \"creating missing database \$dbname\"; \
      sudo docker run --rm -i $PSQL_IMAGE psql \"\$maint\" -v ON_ERROR_STOP=1 \
        -c \"CREATE DATABASE \\\"\$dbname\\\";\" || exit 1; \
    fi; \
    sudo docker run --rm -i $PSQL_IMAGE psql \"\$dburl\" -v ON_ERROR_STOP=1 \
      -c 'DROP TABLE IF EXISTS openbench_sessions, openbench_sources, openbench_messages;' && \
    sudo rm -rf /app-data/openbench/sources /app-data/openbench/sessions.db /app-data/openbench/memory.db && \
    sudo find /app-data/uploads -mindepth 1 -maxdepth 1 -exec rm -rf {} + && \
    sudo find /app-data/downloads -mindepth 1 -maxdepth 1 -exec rm -rf {} + && \
    sudo docker-compose --env-file .env.gcp -f $COMPOSE_FILE up -d && echo WIPED" \
    || die "wipe-chat-data failed"
  ok "chat data wiped — tables recreate with the owner column on next boot"
}

# --- backups -----------------------------------------------------------------
# Enable + verify Cloud SQL automated daily backups and point-in-time recovery
# on the shared instance (covers ALL databases on it: openbench chat DB,
# controlled_chat, appdata). Idempotent — safe to run any time. Restore
# runbook: deploy/DEPLOY.md "Backups & restore".
cmd_backups() {
  log "Cloud SQL backup config on $SQL_INSTANCE ($PROJECT_ID)"
  local enabled pitr
  enabled="$("$GCLOUD" sql instances describe "$SQL_INSTANCE" --project "$PROJECT_ID" \
    --format='value(settings.backupConfiguration.enabled)')" \
    || die "cannot describe $SQL_INSTANCE (check gcloud auth / cloudsql.admin role)"
  pitr="$("$GCLOUD" sql instances describe "$SQL_INSTANCE" --project "$PROJECT_ID" \
    --format='value(settings.backupConfiguration.pointInTimeRecoveryEnabled)')"
  if [ "$enabled" = "True" ] && [ "$pitr" = "True" ]; then
    ok "automated backups + PITR already enabled"
  else
    warn "current: backups=$enabled pitr=$pitr — patching"
    # 18:00 UTC = 01:00 WIB (off-hours for this deployment). Enabling PITR
    # turns on WAL archiving and can briefly restart the instance.
    "$GCLOUD" sql instances patch "$SQL_INSTANCE" --project "$PROJECT_ID" \
      --backup-start-time=18:00 \
      --enable-point-in-time-recovery \
      --retained-backups-count=14 \
      --retained-transaction-log-days=7 \
      || die "backup patch failed"
    ok "automated daily backups (14 kept) + PITR (7 days of WAL) enabled"
  fi
  log "Most recent backups"
  "$GCLOUD" sql backups list --instance="$SQL_INSTANCE" --project "$PROJECT_ID" --limit=5 || true
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
  check "API /account/me (no token)"  "$API_URL/account/me"   "401"
  check "API /admin/users (no token)" "$API_URL/admin/users"  "401"
  # /openapi.json must not serve an API schema. With the same-origin SPA the
  # catch-all answers unknown paths with index.html (200) — that is fine; a
  # leaked JSON schema is not.
  local schema_head
  schema_head="$(curl -s --ssl-no-revoke --max-time 20 "$API_URL/openapi.json" 2>/dev/null | head -c 200 || true)"
  if printf '%s' "$schema_head" | grep -q '"openapi"'; then
    warn "API /openapi.json leaks the schema"; fail=1
  else
    ok "API /openapi.json (hardened): no schema (SPA fallback)"
  fi
  check "Same-origin SPA (/)"          "$API_URL/"             "200"
  # Signed downloads: with OPENBENCH_DOWNLOAD_SECRET set on the VM, an unsigned
  # request must be rejected (403). 404 = secret unset (legacy public mode) —
  # flagged but not fatal so verify still passes before the secret rollout.
  local dl; dl="$(http_code "$API_URL/downloads/nope.pdf")"
  if [ "$dl" = "403" ]; then ok "downloads unsigned probe rejected: 403"
  elif [ "$dl" = "404" ]; then warn "downloads in public mode (404) — set OPENBENCH_DOWNLOAD_SECRET in .env.gcp"
  else warn "downloads unsigned probe: got $dl, want 403"; fail=1; fi
  check "Grafana /grafana/api/health"  "$API_URL/grafana/api/health" "200"
  # 8080 must NOT be publicly reachable (expect connection failure → 000).
  local raw; raw="$(http_code "http://$VM_PUBLIC_IP:8080/health" 8)"
  if [ "$raw" = "000" ] || [ "$raw" = "0" ]; then ok "raw :8080 unreachable (private)"; else warn "raw :8080 reachable ($raw) — should be private"; fail=1; fi
  # Grafana's raw port must be private too.
  local rawg; rawg="$(http_code "http://$VM_PUBLIC_IP:3000/api/health" 8)"
  if [ "$rawg" = "000" ] || [ "$rawg" = "0" ]; then ok "raw :3000 unreachable (private)"; else warn "raw :3000 reachable ($rawg) — should be private"; fail=1; fi
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
  Cloud SQL      $SQL_INSTANCE (backups: deploy.sh backups)
  Compose        $COMPOSE_FILE  (openbench-api @127.0.0.1:8080 + openbench-worker)
  TLS front door $API_URL  (host nginx → 127.0.0.1:8080, Let's Encrypt)
  SPA            served same-origin by the API (GENERAL_CHAT_STATIC_DIR in image)
  Legacy Hosting https://sss-poc1-corporate.web.app  (disabled 2026-07-23 — firebase hosting:disable)
  Runbook        deploy/DEPLOY.md
EOF
}

# --- dispatch ----------------------------------------------------------------
case "${1:-help}" in
  backend)  cmd_backend ;;
  frontend) cmd_frontend ;;
  mcp-image) cmd_mcp_image ;;
  fn-image) cmd_fn_image ;;
  grafana)  cmd_grafana ;;
  nginx)    cmd_nginx ;;
  add-user) shift; cmd_add_user "${1:-}" ;;
  remove-user) shift; cmd_remove_user "${1:-}" ;;
  init-appdb) cmd_init_appdb ;;
  seed-mcp-db) shift; cmd_seed_mcp_db "${1:-}" ;;
  wipe-chat-data) cmd_wipe_chat_data ;;
  backups)  cmd_backups ;;
  verify)   cmd_verify ;;
  all)      cmd_backend; cmd_verify ;;
  help|-h|--help) cmd_help ;;
  *) die "unknown command '$1' (try: backend|frontend|mcp-image|fn-image|grafana|nginx|add-user|remove-user|init-appdb|seed-mcp-db|wipe-chat-data|backups|verify|all|help)" ;;
esac
