#!/usr/bin/env bash
# ============================================================
# Deploy LCI Mini
# - Frontend → Firebase Hosting (multi-site: lci-mini.web.app)
# - Backend  → Google Cloud Run (service: lci-mini)
# ============================================================

set -euo pipefail

PROJECT_ID="openbench-lci"
REGION="us-central1"
SERVICE_NAME="lci-mini"
HOSTING_SITE="lci-mini"
MEMORY="1Gi"
TIMEOUT="300"

# Paths (relative to repo root)
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LCI_DIR="${REPO_ROOT}/examples/lci-mini"
CHAT_UI_DIR="${REPO_ROOT}/studio/chat-ui"
FRONTEND_DIR="${LCI_DIR}/frontend"
ENV_FILE="${LCI_DIR}/.env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
err()  { echo -e "${RED}[error]${NC} $1"; exit 1; }

# ── Preflight checks ──
command -v gcloud >/dev/null || err "gcloud CLI not found"
command -v firebase >/dev/null || err "firebase CLI not found (npm install -g firebase-tools)"
command -v pnpm >/dev/null || err "pnpm not found (npm install -g pnpm)"
[ -f "$ENV_FILE" ] || err ".env file not found at $ENV_FILE"

# ── Parse args ──
DEPLOY_TARGET="${1:-all}"  # all | api | web

case "$DEPLOY_TARGET" in
  all|api|web) ;;
  *) echo "Usage: $0 [all|api|web]"; exit 1 ;;
esac

# ── Set project ──
log "Setting project: $PROJECT_ID"
gcloud config set project "$PROJECT_ID" --quiet

# ============================================================
# Deploy API (Cloud Run)
# ============================================================
deploy_api() {
    log "Deploying API to Cloud Run..."

    # Copy Dockerfile to repo root (gcloud --source requirement)
    cp "${LCI_DIR}/Dockerfile" "${REPO_ROOT}/Dockerfile"

    # Build env vars from .env
    ENV_VARS=$(grep -v '^#' "$ENV_FILE" | grep -v '^$' | grep '=' | tr '\n' ',' | sed 's/,$//')
    # Append runtime env vars
    ENV_VARS="${ENV_VARS},LCI_MINI_UPLOAD_DIR=/app/uploads"
    ENV_VARS="${ENV_VARS},LCI_MINI_DOWNLOAD_DIR=/app/downloads"
    ENV_VARS="${ENV_VARS},OPENBENCH_EXPORT_DIR=/app/downloads"
    ENV_VARS="${ENV_VARS},OPENBENCH_EXPORT_URL_BASE=/downloads"
    ENV_VARS="${ENV_VARS},OPENBENCH_PROFILE_DIR=/app/profiles"
    # NOTE: no LCI_MINI_STATIC_DIR — frontend served by Firebase Hosting

    cd "$REPO_ROOT"
    gcloud run deploy "$SERVICE_NAME" \
        --source . \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --allow-unauthenticated \
        --memory "$MEMORY" \
        --timeout "$TIMEOUT" \
        --set-env-vars "$ENV_VARS"

    # Cleanup
    rm -f "${REPO_ROOT}/Dockerfile"

    # Get URL
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format="value(status.url)")
    log "API deployed: $SERVICE_URL"

    # Verify
    if curl -sf "${SERVICE_URL}/health" > /dev/null 2>&1; then
        log "Health check: OK"
    else
        warn "Health check failed (may need IAM: allow unauthenticated)"
    fi
}

# ============================================================
# Deploy Web (Firebase Hosting multi-site)
# ============================================================
deploy_web() {
    log "Building @openbench/chat-ui..."
    cd "$CHAT_UI_DIR"
    pnpm install --frozen-lockfile 2>/dev/null || pnpm install
    pnpm build

    log "Building frontend..."
    cd "$FRONTEND_DIR"
    pnpm install --frozen-lockfile 2>/dev/null || pnpm install
    pnpm build

    log "Ensuring Firebase site '${HOSTING_SITE}' exists..."
    if ! firebase hosting:sites:list --project "$PROJECT_ID" 2>/dev/null | grep -q "${HOSTING_SITE}"; then
        log "Creating Firebase Hosting site: ${HOSTING_SITE}"
        firebase hosting:sites:create "$HOSTING_SITE" --project "$PROJECT_ID" || \
            warn "Site creation failed (may already exist or need manual creation)"
    fi

    log "Applying hosting target..."
    cd "$LCI_DIR"
    firebase target:apply hosting "$HOSTING_SITE" "$HOSTING_SITE" --project "$PROJECT_ID" 2>/dev/null || true

    log "Deploying to Firebase Hosting (target: ${HOSTING_SITE})..."
    firebase deploy --only "hosting:${HOSTING_SITE}" --project "$PROJECT_ID"

    log "Frontend deployed: https://${HOSTING_SITE}.web.app"
}

# ============================================================
# Execute
# ============================================================
case "$DEPLOY_TARGET" in
  api)
    deploy_api
    ;;
  web)
    deploy_web
    ;;
  all)
    deploy_api
    deploy_web
    ;;
esac

log "Done!"
echo ""
echo "  Frontend: https://${HOSTING_SITE}.web.app"
echo "  API:      Cloud Run ($SERVICE_NAME @ $REGION)"
echo ""
