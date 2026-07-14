# Controlled Source Chat — Deployment Runbook

Single source of truth for deploying the `controlled-source-chat` example to
Google Cloud Run. A clean-memory agent (or human) should be able to read this
file and redeploy with no other context. The deploy logic lives in
[`deploy.sh`](deploy.sh) next to this file. (The sibling `general-chat` example
uses a different stack — VM + nginx + Firebase Hosting — documented in
[`deploy/DEPLOY.md`](../../deploy/DEPLOY.md); do not mix the two.)

> **TL;DR** — from the repo root, in git-bash / WSL / Cloud Shell with `gcloud`
> authenticated and on PATH:
> ```bash
> bash examples/controlled-source-chat/deploy.sh all      # build image + deploy + verify
> bash examples/controlled-source-chat/deploy.sh image    # rebuild image only (Cloud Build)
> bash examples/controlled-source-chat/deploy.sh run      # roll out Cloud Run service
> bash examples/controlled-source-chat/deploy.sh verify   # probe the live service
> ```

## Architecture

```
 Browser
   │  (HTTPS)
   ▼
 Cloud Run service "controlled-source-chat"        us-central1, project sss-poc1-corporate
   │  single container, max-instances=1, --allow-unauthenticated at the LB
   │  (app-level auth: local username/password → HMAC bearer token)
   │
   │  FastAPI (uvicorn :8080) — one origin serves everything:
   │   ├─ React SPA (frontend/dist baked into the image, GENERAL_CHAT_STATIC_DIR)
   │   ├─ /auth/login /auth/me — local accounts admin + guest (no Firebase;
   │   │    OPENBENCH_AUTH_DISABLED=1, guests blocked from admin routes)
   │   └─ agent → Gemini API (GOOGLE_API_KEY)
   │
   └── unix socket /cloudsql/… (--add-cloudsql-instances)
         ▼
       Cloud SQL Postgres "openbench-postgres" — database controlled_chat
         curated sources (openbench_sources) + chat sessions + agent memory
```

Why this shape:

- **Same-origin SPA** — the API's catch-all serves the built frontend
  (`GENERAL_CHAT_STATIC_DIR`), so there is no Firebase Hosting site, no CORS,
  no `VITE_BACKEND_URL`. One URL is the whole app.
- **Postgres for all durable state** — Cloud Run's filesystem is ephemeral.
  Setting `GENERAL_CHAT_DATABASE_URL` switches the source store, session store,
  and agent memory store to Postgres (`PostgresSourceStore`,
  `PostgresSessionStore`, `PostgresMemoryStore`; all `CREATE TABLE IF NOT
  EXISTS` on first use — no migrations to run). The admin-curated knowledge
  base survives restarts, redeploys, and scale-to-zero.
- **No GCS bucket / Pub/Sub worker** — uploads are parsed inline and the parsed
  content lands in the Postgres source records. See caveats.
- **`CONTROLLED_CHAT_AUTH_SECRET` pinned via env** — otherwise the HMAC signing
  secret is auto-generated on local disk and every instance recycle would
  invalidate all login tokens.
- **max-instances=1** — a few minor stores (admin-created extra users,
  published dashboards, custom functions) still write local files; one instance
  keeps them coherent for a demo. Do not raise this without moving that state.

## Resource inventory

| Resource | Value |
|---|---|
| GCP project | `sss-poc1-corporate` |
| Cloud Run service | `controlled-source-chat`, region `us-central1`, 2 GiB / 2 CPU / 300 s / max 1 instance |
| Image | `us-central1-docker.pkg.dev/sss-poc1-corporate/openbench/controlled-source-chat:latest` |
| Dockerfile | [`Dockerfile.controlled-source-chat`](../../Dockerfile.controlled-source-chat) (repo root, multi-stage: node builds SPA → python runtime) |
| Cloud Build config | [`cloudbuild.controlled-source-chat.yaml`](../../cloudbuild.controlled-source-chat.yaml) (repo root) |
| Cloud SQL | existing instance `openbench-postgres` (`sss-poc1-corporate:us-central1:openbench-postgres`), **database `controlled_chat`**, user `controlled-chat-app` |
| Runtime service account | default compute SA (`920070146333-compute@…`, has `roles/editor` → Cloud SQL connect) |
| Live URL | `gcloud run services describe controlled-source-chat --region us-central1 --format='value(status.url)'` |

The image contains the whole repo (the example imports the sibling
`general_chat` package by path), the SDK installed with
`[google,chat,search,gcp,mcp,epub,media]` extras, and the pre-built SPA.
No playwright/chromium — see caveats.

## Environment variables (Cloud Run service)

Set by `deploy.sh run` from the **gitignored** `examples/controlled-source-chat/.env`:

| Var | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Gemini key (falls back to `examples/general-chat/.env` locally) |
| `GENERAL_CHAT_DATABASE_URL` | `postgresql://controlled-chat-app:<pass>@/controlled_chat?host=/cloudsql/sss-poc1-corporate:us-central1:openbench-postgres` |
| `CONTROLLED_CHAT_AUTH_SECRET` | pins HMAC token signing across restarts (`openssl rand -hex 32`) |
| `TAVILY_API_KEY` | optional, source discovery/web search |

Baked into the image: `GENERAL_CHAT_STATIC_DIR` (SPA dist), `PORT=8080`.
Everything else (storage root, soul dir, strict agent goal, shared-sources
thread, `OPENBENCH_AUTH_DISABLED=1`) comes from `server.py` defaults.

Optional overrides you can add to `.env` before `deploy.sh run`:
`GENERAL_CHAT_MODEL` (default `gemini-3-flash-preview`),
`CONTROLLED_CHAT_ADMIN_PASSWORD` / `CONTROLLED_CHAT_GUEST_PASSWORD` (defaults
`admin123` / `guest123`).

## Accounts

Local auth only — no Google sign-in, no allowlist. Built-in accounts:

- `admin` — control panel (sources, MCP registry, users) + chat
- `guest` — chat only (403 on all management routes)

Passwords are the code defaults unless overridden via env (see above). The
login screen intentionally does **not** display them. Admin can create extra
users in the control panel, but those live in a local JSON file and are lost
on instance recycle (built-ins always work).

## One-time setup (already done — repeat only for a fresh project)

```bash
# 1. Database + user on the existing Cloud SQL instance
gcloud sql databases create controlled_chat --instance=openbench-postgres --project=sss-poc1-corporate
gcloud sql users create controlled-chat-app --instance=openbench-postgres \
  --project=sss-poc1-corporate --password="$(openssl rand -hex 24)"
# (gcloud-created users join cloudsqlsuperuser → may create tables; stores
#  auto-create their tables on first request, no DDL needed)

# 2. Local secrets file (gitignored) — examples/controlled-source-chat/.env
GENERAL_CHAT_DATABASE_URL=postgresql://controlled-chat-app:<pass>@/controlled_chat?host=/cloudsql/sss-poc1-corporate:us-central1:openbench-postgres
CONTROLLED_CHAT_AUTH_SECRET=<openssl rand -hex 32>
# GOOGLE_API_KEY=<key>            # optional if examples/general-chat/.env has it

# 3. Deploy
bash examples/controlled-source-chat/deploy.sh all
```

Secrets live only in the gitignored `.env` and in the Cloud Run service's env
config — never in the repo. `.gcloudignore` excludes `**/.env` and this
example's local state dirs from the build context.

## Verify

`bash examples/controlled-source-chat/deploy.sh verify` checks:
`/health` = 200 · `/` serves the SPA shell with no credential hint ·
`POST /auth/login` (admin) issues a token · `/auth/me` = 200 with it ·
`/persona` = 401 without it.

Manual smoke test: log in as `admin`, add a text source in the control panel,
then log in as `guest` and ask about it — the answer must cite the source by
name. Persistence: `gcloud run services update controlled-source-chat --region
us-central1 --update-env-vars DEPLOY_BUMP=$(date +%s)` forces a new revision;
the curated source list must survive.

## Caveats

- **Ephemeral files**: original uploaded file bytes (`uploads/`), generated
  downloads, published dashboards, custom functions, and admin-created extra
  users live on the instance filesystem and vanish on recycle. Parsed source
  content, sessions, and memory are in Postgres and survive.
- **Default demo passwords** are kept deliberately (demo). Anyone with the URL
  can sign in as admin — rotate via `CONTROLLED_CHAT_ADMIN_PASSWORD` /
  `CONTROLLED_CHAT_GUEST_PASSWORD` env when that stops being acceptable.
- **No dashboard PDF export**: chromium/playwright is not installed in this
  image (kept slim). `POST /dashboard/export/pdf` will fail.
- **MCP registry**: `GENERAL_CHAT_MCP_ENABLED=0` and there is no Docker socket
  on Cloud Run, so admin-registered MCP servers that need local containers
  won't run. Registry entries themselves are stored locally (ephemeral).
- **Scale**: max-instances=1 is a correctness requirement, not a tuning knob
  (see architecture notes). Cold starts after idle take ~10–30 s.

## Rollback

Cloud Run keeps prior revisions:

```bash
gcloud run revisions list --service controlled-source-chat --region us-central1
gcloud run services update-traffic controlled-source-chat --region us-central1 \
  --to-revisions <REVISION>=100
```
