#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${OPENBENCH_APP_DIR:-/opt/openbench}"
IMAGE="${OPENBENCH_IMAGE:-openbench-general-chat:latest}"

if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

sudo mkdir -p "$APP_DIR"
sudo mkdir -p \
  /app-data/openbench \
  /app-data/openbench-gcs-cache \
  /app-data/uploads/_sam_debug \
  /app-data/downloads \
  /app-data/mcp-sandbox \
  /app-data/image-search/data/previews \
  /app-data/image-search/models \
  /app-data/huggingface
sudo cp docker-compose.gce.yml "$APP_DIR/docker-compose.gce.yml"
if [[ ! -f "$APP_DIR/.env.gcp" ]]; then
  sudo cp .env.example.gcp "$APP_DIR/.env.gcp"
  echo "Created $APP_DIR/.env.gcp. Fill it in before starting the service."
fi

sudo tee /etc/systemd/system/openbench-general-chat.service >/dev/null <<SERVICE
[Unit]
Description=OpenBench General Chat
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$APP_DIR
Environment=OPENBENCH_IMAGE=$IMAGE
ExecStart=/usr/bin/docker compose --env-file .env.gcp -f docker-compose.gce.yml up -d
ExecStop=/usr/bin/docker compose --env-file .env.gcp -f docker-compose.gce.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable openbench-general-chat.service

cat <<EOF
Bootstrap complete.

Next steps:
1. Edit $APP_DIR/.env.gcp. Keep OPENBENCH_API_BIND set to 127.0.0.1 unless a private VPC-only address is required.
2. Build or pull the image: $IMAGE.
3. Start: sudo systemctl start openbench-general-chat
EOF
