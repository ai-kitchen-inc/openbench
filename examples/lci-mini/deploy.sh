#!/usr/bin/env bash
# ============================================================
# Deploy LCI Mini to Google Cloud Run
# Single-container: backend serves frontend static files
# ============================================================

set -euo pipefail

PROJECT_ID="openbench-lci"
REGION="us-central1"
SERVICE_NAME="lci-mini"
MEMORY="1Gi"
TIMEOUT="300"

# Paths (relative to repo root)
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LCI_DIR="${REPO_ROOT}/examples/lci-mini"
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
[ -f "$ENV_FILE" ] || err ".env file not found at $ENV_FILE"

# ── Set project ──
log "Setting project: $PROJECT_ID"
gcloud config set project "$PROJECT_ID" --quiet

# ── Deploy ──
log "Deploying LCI Mini to Cloud Run..."

# Copy Dockerfile to repo root (gcloud run deploy --source needs it at root)
cp "${LCI_DIR}/Dockerfile" "${REPO_ROOT}/Dockerfile"

# Build env vars from .env (skip comments and empty lines)
ENV_VARS=$(grep -v '^#' "$ENV_FILE" | grep -v '^$' | grep '=' | tr '\n' ',' | sed 's/,$//')
# Append runtime env vars
ENV_VARS="${ENV_VARS},LCI_MINI_UPLOAD_DIR=/app/uploads"
ENV_VARS="${ENV_VARS},LCI_MINI_DOWNLOAD_DIR=/app/downloads"
ENV_VARS="${ENV_VARS},LCI_MINI_STATIC_DIR=/app/static"
ENV_VARS="${ENV_VARS},OPENBENCH_EXPORT_DIR=/app/downloads"
ENV_VARS="${ENV_VARS},OPENBENCH_EXPORT_URL_BASE=/downloads"
ENV_VARS="${ENV_VARS},OPENBENCH_PROFILE_DIR=/app/profiles"

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
log "Deployed: $SERVICE_URL"

# Verify
if curl -sf "${SERVICE_URL}/health" > /dev/null 2>&1; then
    log "Health check: OK"
else
    warn "Health check failed (may need a moment to start)"
fi

log "Done!"
echo ""
echo "  URL: $SERVICE_URL"
echo "  Project: $PROJECT_ID"
echo "  Service: $SERVICE_NAME @ $REGION"
echo ""
