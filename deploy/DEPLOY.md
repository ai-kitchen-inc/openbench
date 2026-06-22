# General Chat — Deployment Runbook

Single source of truth for deploying the `general-chat` example. A clean-memory
agent (or human) should be able to read this file and redeploy with no other
context. The deploy logic lives in [`deploy/deploy.sh`](deploy.sh).

> **TL;DR** — from the repo root, in git-bash / WSL / Cloud Shell with `gcloud`,
> `firebase`, `pnpm` authenticated and on PATH:
> ```bash
> bash deploy/deploy.sh all      # build image + roll out VM + deploy SPA + verify
> bash deploy/deploy.sh verify   # just probe the live deployment
> bash deploy/deploy.sh help     # usage + live resource inventory
> ```

## Architecture

```
 Browser
   │  (HTTPS)
   ▼
 Firebase Hosting  ── serves the React SPA (examples/general-chat/frontend/dist)
   │  https://sss-poc1-corporate.web.app
   │
   │  SPA calls the API cross-origin with a Firebase ID token (Bearer)
   ▼
 VM nginx (TLS, Let's Encrypt)         https://35-188-138-52.sslip.io
   │  reverse_proxy → 127.0.0.1:8080   (/awp has proxy_buffering off for SSE)
   ▼
 openbench-api container  (uvicorn, 127.0.0.1:8080, bound to localhost only)
   │  Firebase auth middleware: verifies ID token (Google JWKS) + email allowlist
   │  on every route except /health
   ├── openbench-worker container  (Pub/Sub → GCS file processing)
   ├── Cloud SQL (Postgres)   — persistent chat memory   (optional)
   └── Cloud Storage (GCS)    — uploads/outputs          (optional)
```

Auth boundary: Firebase admits any Google account; **authorization** is decided
server-side. `GENERAL_CHAT_ALLOWED_EMAILS` / `GENERAL_CHAT_ALLOWED_DOMAINS` gate
access (403 for non-listed). The SPA shows an "Access not authorized" screen on 403.

File support (EPUB / audio / image / video): the API image installs the `epub`
and `media` extras plus the system libs `libcairo2` (SVG rasterization) and
`libheif1` (HEIC) — see [`Dockerfile.general-chat`](../Dockerfile.general-chat).
`imageio-ffmpeg` bundles its own ffmpeg binary, so no apt `ffmpeg` is needed.
Audio/video transcription uses **Gemini native audio** (the existing
`GOOGLE_API_KEY`) — no extra STT service. Large media extraction is slow, so it
runs in the `openbench-worker` (Pub/Sub) rather than blocking uploads.

## Resource inventory

| Thing | Value |
|-------|-------|
| GCP / Firebase project | `sss-poc1-corporate` (region `us-central1`) |
| API image | `us-central1-docker.pkg.dev/sss-poc1-corporate/openbench/general-chat:latest` |
| Image build config | [`cloudbuild.general-chat.yaml`](../cloudbuild.general-chat.yaml) ← [`Dockerfile.general-chat`](../Dockerfile.general-chat) |
| Compute Engine VM | `openbench-general-chat`, zone `us-central1-a` |
| VM deploy dir | `/home/Admin/openbench-deploy` (holds `docker-compose.gce.yml` + `.env.gcp`) |
| Compose | [`docker-compose.gce.yml`](../docker-compose.gce.yml) — `openbench-api` (`127.0.0.1:8080`) + `openbench-worker` |
| TLS front door | `https://35-188-138-52.sslip.io` (VM public IP `35.188.138.52` via sslip.io) |
| Reverse proxy | host **nginx** on the VM; ref config [`deploy/nginx-openbench-api.conf`](nginx-openbench-api.conf) → `/etc/nginx/sites-available/openbench-api` |
| Frontend (SPA) | `examples/general-chat/frontend` (Vite), Hosting config [`examples/general-chat/firebase.json`](../examples/general-chat/firebase.json) |
| Hosting URL | `https://sss-poc1-corporate.web.app` |
| Firebase web app id | `1:920070146333:web:1ebd29612bfe6a4d04f9f4` |

## Prerequisites (one-time)

- `gcloud` authenticated, project set: `gcloud config set project sss-poc1-corporate`. Account needs Cloud Build, Compute SSH, and Artifact Registry access.
- `firebase` CLI logged in (`firebase login`) with access to the project.
- `pnpm` installed (frontend build).
- The VM already exists and is bootstrapped (see [`scripts/bootstrap-gce-general-chat.sh`](../scripts/bootstrap-gce-general-chat.sh)), with `/home/Admin/openbench-deploy/.env.gcp` filled in (secrets) and host nginx serving TLS.
- Firebase **Authentication → Google provider** enabled (see "Enable Google sign-in" below).

## Deploy

```bash
bash deploy/deploy.sh all        # backend → frontend → verify
```

Or individually:

| Command | Does |
|---------|------|
| `deploy/deploy.sh backend` | Cloud Build the image (async + poll), `docker pull` + `docker-compose up -d` on the VM, wait for `/health`. |
| `deploy/deploy.sh frontend` | `pnpm build` the SPA with the right `VITE_*`, `firebase deploy --only hosting`. |
| `deploy/deploy.sh nginx` | scp `docker-compose.gce.yml` + nginx conf to the VM, `nginx -t` + reload. Run only when those files change. |
| `deploy/deploy.sh add-user EMAIL` | Append `EMAIL` to the allowlist on the VM and restart the API (idempotent). |
| `deploy/deploy.sh verify` | Probe health/auth/hardening/network on the live deployment. |

All identifiers are defaults in `deploy.sh`; override any via env or a gitignored
`deploy/deploy.env` (e.g. `PUBLIC_HOST=...`, `VM_ZONE=...`).

## Environment variables

**Repo-safe (committed):** `.env.example.gcp` is the template. The public Firebase
web config (`VITE_FIREBASE_*`) is baked into `deploy.sh` (it ships in the JS bundle
— not a secret).

**VM-only secrets (never in the repo — live in `/home/Admin/openbench-deploy/.env.gcp`):**

| Var | Purpose |
|-----|---------|
| `GOOGLE_API_KEY` | Gemini API key |
| `GENERAL_CHAT_DATABASE_URL` | Cloud SQL Postgres URL (with password) |
| `GENERAL_CHAT_FIREBASE_PROJECT_ID` | enables auth; must be `sss-poc1-corporate` |
| `GENERAL_CHAT_ALLOWED_EMAILS` | comma-separated allowlist (use `add-user`) |
| `GENERAL_CHAT_ALLOWED_DOMAINS` | optional domain allowlist |
| `GENERAL_CHAT_ALLOWED_ORIGINS` | CORS allowlist → the Hosting origins |
| `GENERAL_CHAT_GCP_BUCKET` / `GENERAL_CHAT_GCP_PUBSUB_SUBSCRIPTION` | GCS + worker |
| `OPENBENCH_API_BIND=127.0.0.1` / `OPENBENCH_IMAGE` | keep API private; image to run |

Full list with defaults: [`.env.example.gcp`](../.env.example.gcp).

## Enable Google sign-in (one-time, project-level)

The Firebase project must have Authentication initialized + the Google provider
enabled, or sign-in fails with `auth/configuration-not-found`. Easiest path:
**Firebase Console → Authentication → Sign-in method → Google → Enable → set
support email → Save** (auto-provisions the OAuth client). Confirm via:
```bash
gcloud auth print-access-token >/dev/null && \
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "x-goog-user-project: sss-poc1-corporate" \
  https://identitytoolkit.googleapis.com/admin/v2/projects/sss-poc1-corporate/defaultSupportedIdpConfigs/google.com
# → {"enabled": true, "clientId": "..."}
```

## Add / remove an allowed user

```bash
bash deploy/deploy.sh add-user someone@gmail.com
```
Removal: edit `GENERAL_CHAT_ALLOWED_EMAILS` in the VM `.env.gcp` and
`sudo docker-compose --env-file .env.gcp -f docker-compose.gce.yml up -d openbench-api`.
The Firebase Console Users page only **views/disables** accounts — it does not
grant app access (the allowlist does).

## Verify

```bash
bash deploy/deploy.sh verify
```
Expected: `/health` 200 · `/persona` 401 (no token) · `/openapi.json` 404
(docs disabled) · Hosting 200 · raw `:8080` unreachable. Real end-to-end:
open the Hosting URL, sign in with an allowlisted Google account, send a message.

## Pub/Sub worker subscription

The worker consumes `openbench-worker-file-processing`. File processing must finish
within the ack deadline or messages redeliver (duplicate work + rising error rate /
oldest-unacked age). Applied settings:

```bash
gcloud pubsub subscriptions update openbench-worker-file-processing \
  --project sss-poc1-corporate \
  --ack-deadline=60 --min-retry-delay=10s --max-retry-delay=600s
```

Optional dead-letter queue (caps infinite redelivery of poison messages; needs IAM
on the Pub/Sub service agent `service-920070146333@gcp-sa-pubsub.iam.gserviceaccount.com`):

```bash
gcloud pubsub topics create openbench-worker-file-processing-dlq --project sss-poc1-corporate
gcloud pubsub subscriptions create openbench-worker-file-processing-dlq-sub \
  --topic openbench-worker-file-processing-dlq --message-retention-duration=7d --project sss-poc1-corporate
gcloud pubsub topics add-iam-policy-binding openbench-worker-file-processing-dlq \
  --member="serviceAccount:service-920070146333@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role=roles/pubsub.publisher --project sss-poc1-corporate
gcloud pubsub subscriptions add-iam-policy-binding openbench-worker-file-processing \
  --member="serviceAccount:service-920070146333@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role=roles/pubsub.subscriber --project sss-poc1-corporate
gcloud pubsub subscriptions update openbench-worker-file-processing \
  --dead-letter-topic=openbench-worker-file-processing-dlq \
  --max-delivery-attempts=5 --project sss-poc1-corporate
```

Worker subscriber bounds in-flight messages via `GENERAL_CHAT_PUBSUB_MAX_MESSAGES`
(default 8). Extraction is fast-first (pypdf/python-docx; Docling only OCRs scanned
PDFs), so per-file CPU time is low and stays well under the 60s deadline.

## Rollback

- **Frontend:** `cd examples/general-chat && firebase hosting:rollback` (or redeploy a prior build).
- **Backend:** images are tagged `:latest`; to roll back, on the VM
  `sudo docker pull <image>@<previous-sha256>` then `... up -d`, or rebuild from a
  prior git commit. Previous `.env.gcp` is backed up as `.env.gcp.bak-*` before edits.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `TypeError: NetworkError` in browser | SPA built with wrong `VITE_BACKEND_URL`. Rebuild + redeploy frontend so it targets `https://35-188-138-52.sslip.io`. |
| `auth/configuration-not-found` on sign-in | Google provider not enabled — see "Enable Google sign-in". |
| Signed-in user gets "Access not authorized" / 403 | Email not in `GENERAL_CHAT_ALLOWED_EMAILS` — run `add-user`. |
| 502 right after a deploy | API still booting (MCP seed ~60s). `deploy.sh backend` waits for `/health`; otherwise re-check shortly. |
| Chat doesn't stream | nginx `/awp` must have `proxy_buffering off` — run `deploy/deploy.sh nginx`. |
| `gcloud builds submit` exits 1 but build is fine | Log-streaming permission quirk. `deploy.sh` uses `--async` + polling to avoid it. |
| Windows git-bash `curl` errors `(43)` on the sslip.io host | Known Schannel-curl bug with the all-numeric hostname labels. `deploy.sh verify` auto-falls back to PowerShell `Invoke-WebRequest`; from Linux/Cloud Shell curl works directly. |

## Out of scope

`examples/lci-mini` (a separate example using Cloud Run, project `openbench-lci`)
is unrelated and untouched by this runbook.
