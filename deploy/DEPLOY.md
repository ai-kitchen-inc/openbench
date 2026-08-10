# General Chat (SSS) — Deployment Runbook

Single source of truth for deploying the `general-chat` example (product name
**SSS**, Bahasa Indonesia UI). A clean-memory agent (or human) should be able
to read this file and redeploy with no other context. The deploy logic lives
in [`deploy/deploy.sh`](deploy.sh).

> **TL;DR** — from the repo root, in git-bash / WSL / Cloud Shell with `gcloud`
> authenticated and on PATH:
> ```bash
> bash deploy/deploy.sh all      # build API+SPA image + roll out VM + verify
> bash deploy/deploy.sh verify   # just probe the live deployment
> bash deploy/deploy.sh help     # usage + live resource inventory
> ```

## Architecture

```
 Browser  ── one origin for everything: https://chat.serebrum.co.id
   │  (HTTPS; Firebase JS SDK handles Google sign-in, API calls carry the ID token)
   ▼
 VM nginx (TLS, Let's Encrypt)         https://chat.serebrum.co.id
   │  reverse_proxy → 127.0.0.1:8080   (/awp has proxy_buffering off for SSE)
   ▼
 openbench-api container  (uvicorn, 127.0.0.1:8080, bound to localhost only)
   │  serves the React SPA same-origin (GENERAL_CHAT_STATIC_DIR baked into the
   │  image) AND the API — no Firebase Hosting, no CORS in prod
   │  Firebase auth middleware: verifies ID token (Google JWKS), resolves the
   │  account's ROLE from the `openbench_users` table, and enforces the
   │  admin-managed capability flags per role — on every route except /health
   ├── openbench-worker container  (Pub/Sub → GCS file processing)
   ├── Cloud SQL (Postgres)   — chat memory, sources, users, app settings
   └── Cloud Storage (GCS)    — uploads/outputs          (optional)
```

Auth boundary: Firebase admits any Google account; **authorization** is decided
server-side by the `openbench_users` table (roles `admin` | `user`). Unknown
accounts get 403 and the SPA shows an access-denied screen. User management
lives in the in-app admin panel (Pengguna page) — no env allowlist, no restart.
`GENERAL_CHAT_ALLOWED_EMAILS` remains only as a first-boot seeding input.

Roles & capabilities: admins get the full control panel (global knowledge
sources, persona templates, capability toggles, users, MCP servers, custom
functions) and bypass all capability gates. Regular users get the chat; which
features they can touch (attachments, per-session sources, MCP management,
custom functions, dashboards, image search) is toggled live from the admin
panel (Kemampuan page) and enforced by the middleware (403 with the capability
id). The global `file_generation` flag controls whether the agent loads the
file-export skills (Excel/PDF/Markdown deliverables).

Global knowledge: admins curate shared sources (owner `shared`, thread
`global-sources`); every user's chat turn is grounded on them *in addition to*
the user's own session sources, and users can inspect them read-only via the
Sumber drawer (`GET /account/shared-sources`). The assistant's grounding
posture is an admin-selectable persona template (default `soft-grounded`:
cite sources when relevant, answer from general knowledge otherwise; `strict`
reproduces the controlled-source-chat behavior; `general` is the classic
assistant). Applying/editing a persona hot-rebuilds the agent — no restart.

Per-user isolation: chat sessions, agent memory, and sources/uploads are scoped
to the authenticated user's **lowercased email** (the `owner` column in
`openbench_sessions` / `openbench_sources`; JSON sources use a per-owner
subdirectory). Cross-user access behaves as "not found" (404 / empty list) —
existence is never leaked. The first save of a client-generated session id
claims it for that user; a save under a different user is rejected
(`SessionOwnershipError` → 404). Local dev with `OPENBENCH_AUTH_DISABLED=1`
stores everything under the sentinel owner `local`. Rollout was a clean wipe
(`deploy.sh wipe-chat-data`) — pre-isolation rows had no owner and were dropped
rather than migrated.

Accepted residual risks (documented decisions, not bugs):
- `/uploads`, `/image-search/previews` static mounts are auth-gated but not
  per-user: paths contain unguessable uuid file ids.
- `/downloads` (agent-generated deliverables) is **public-by-URL** like
  `/d/{id}`: download cards are plain anchor links that carry no Bearer
  header, so the mount is unauthenticated; filenames embed a random uuid
  suffix and the mount never lists directories.
- `GET /d/{id}` share links stay public by design (below).
- Publish store, custom functions, MCP catalogs, persona, and skills are shared
  app-level configuration. Editing them is now admin-gated (capability flags
  default MCP management and custom functions off for the `user` role), which
  retires the old "any allowlisted user can edit shared config" residual risk.
- The Pub/Sub worker updates source records without a request identity; it
  preserves the existing row's owner and never creates user-visible rows.
- The `openbench-api` container runs as **root** (no `USER` directive in
  `Dockerfile.general-chat`). A non-root user would be cosmetic here: the
  container holds the mounted docker socket to spawn on-demand MCP servers,
  and socket access is root-equivalent on the host regardless of the in-container
  uid. Meanwhile `USER app` would break VM-side realities (docker group GID,
  `/app-data` volume ownership, Playwright's browser cache under `/root`).
  The real hardening path — if ever needed — is moving MCP spawning to a
  separate socket-holding sidecar and dropping the socket from this container;
  only then does a non-root API user buy anything.

Public dashboard share links: `POST /dashboard/publish` (auth) persists a dashboard
under `$GENERAL_CHAT_STORAGE_ROOT/published/` (on the persistent `/app-data/openbench`
volume) and returns a `GET /d/{id}` URL. **`/d/{id}` is intentionally unauthenticated**
— it is the only public route besides `/health`, so anyone with the link can view that
single dashboard's self-contained HTML. No nginx/Hosting change is needed: `location /`
already proxies it to the API, and the link points at the VM directly. `/dashboard/*`
(publish + Grafana export) is auth-gated like the rest of the API.

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
| Image build config | [`cloudbuild.general-chat.yaml`](../cloudbuild.general-chat.yaml) ← [`Dockerfile.general-chat`](../Dockerfile.general-chat) ← [`.dockerignore`](../.dockerignore) — all three are **tracked in git** and are the source of truth for the deployed image; edit them in the repo, not on a laptop |
| Build context | Repo root, filtered by [`.gcloudignore`](../.gcloudignore) (**not** `.gitignore` — gcloud stops reading `.gitignore` once `.gcloudignore` exists). `mcp/*/{data,models,weights,.venv}/` is excluded: ~1.17 GB of local-dev weights that no deployed container reads. See "Build speed" below. |
| Compute Engine VM | `openbench-general-chat`, zone `us-central1-a`, **`e2-standard-2`** (2 vCPU / 8 GB), 100 GB `pd-standard` boot disk. Downsized from `e2-standard-4` on 2026-08-04 (30-day CPU median 0.9%, container peak RSS 511 MiB); resize = stop → `set-machine-type` → start, the static IP survives |
| Cloud SQL | `openbench-postgres` (POSTGRES_15, `us-central1`, zonal), **`db-custom-1-3840`** (1 vCPU / 3.75 GB), 50 GB SSD, storage auto-resize capped at **50 GB**. Serves 3 DBs: chat (`openbench`), `controlled_chat`, `appdata`. Downsized from `db-custom-2-8192` on 2026-08-04 (7-day CPU avg 6%, 113 MB data). Disk can grow but never shrink — shrinking would require a new instance + endpoint migration (grafana datasource IP, `.env.gcp`, CSC socket path) |
| VM deploy dir | `/home/Admin/openbench-deploy` (holds `docker-compose.gce.yml` + `.env.gcp`) |
| Compose | [`docker-compose.gce.yml`](../docker-compose.gce.yml) — `openbench-api` (`127.0.0.1:8080`) + `openbench-worker` |
| TLS front door | `https://chat.serebrum.co.id` (DNS A record → reserved static IP `34.135.198.188`, address `openbench-ip`) |
| Reverse proxy | host **nginx** on the VM; ref config [`deploy/nginx-openbench-api.conf`](nginx-openbench-api.conf) → `/etc/nginx/sites-available/openbench-api` |
| Frontend (SPA) | `examples/general-chat/frontend` (Vite) — built into the API image (stage 1 of [`Dockerfile.general-chat`](../Dockerfile.general-chat)), served same-origin via `GENERAL_CHAT_STATIC_DIR` |
| Legacy Hosting URL | `https://sss-poc1-corporate.web.app` — **disabled 2026-07-23** (`firebase hosting:disable`); serves "Site Not Found". Default site can only be deleted with the project; redeploy would re-enable it |
| Firebase web app id | `1:920070146333:web:1ebd29612bfe6a4d04f9f4` (sign-in only) |
| User/role table | `openbench_users` in the chat DB (managed from the admin panel) |
| App settings | `openbench_app_settings` in the chat DB (capabilities + persona) |

## Cost & sizing

Right-sized on 2026-08-04 against 30 days of metrics (~$230/mo → ~$112/mo list):

| Resource | Size | Basis | Revisit when |
|----------|------|-------|--------------|
| Cloud SQL | `db-custom-1-3840`, 50 GB SSD, auto-resize cap 50 GB | 7-day CPU avg 6% (peak 7.5%), 113 MB data, ≤2 connections | sustained CPU >40% or RAM pressure; `db-g1-small` (shared-core, ~$25/mo less) is the next step down if weeks of metrics stay flat |
| VM | `e2-standard-2` | 30-day CPU median 0.9% / p95 8.5% (only deploy-time pulls burst higher); 13-day container `memory.peak`: api 511 MiB, worker 72 MiB, grafana 97 MiB; zero OOM | sustained CPU >50% outside deploys, or OOM kills in `journalctl -k` |
| Artifact Registry | cleanup policies on all repos: keep 5 most-recent versions, delete >30 days | repo had grown to 169 GB of ~9 GB images (one per deploy, never pruned) | — |
| Cloud Build bucket | `gs://sss-poc1-corporate_cloudbuild` 30-day delete lifecycle | grew to 25 GB of source tarballs | — |
| VM boot disk | 100 GB `pd-standard` kept | `deploy.sh backend` now prunes dangling images each rollout (was 89% full from 7 dangling ~9 GB images) | shrinking needs VM re-creation — not worth $4/mo |

Deleted 2026-08-04 (stale, superseded by the VM deployment): Cloud Run services
`general-chat` (us-central1), `general-chat-openui-api` + `general-chat-openui-web`
(asia-southeast2). Only `controlled-source-chat` remains on Cloud Run.

No budget alert exists yet — creating one needs a Billing Account Administrator
(console → Billing → Budgets & alerts; suggested: $150/mo with 50/90/100% alerts).

## Prerequisites (one-time)

- `gcloud` authenticated, project set: `gcloud config set project sss-poc1-corporate`. Account needs Cloud Build, Compute SSH, and Artifact Registry access.
- The VM already exists and is bootstrapped (see [`scripts/bootstrap-gce-general-chat.sh`](../scripts/bootstrap-gce-general-chat.sh)), with `/home/Admin/openbench-deploy/.env.gcp` filled in (secrets) and host nginx serving TLS.
- Firebase **Authentication → Google provider** enabled (see "Enable Google sign-in" below).
- Firebase **Authentication → Settings → Authorized domains** must include
  `chat.serebrum.co.id` — the SPA runs on that origin, and
  `signInWithPopup` fails on unlisted domains. (`firebase` CLI and `pnpm` are
  no longer needed for deploys — the SPA builds inside the Docker image.)

## Deploy

```bash
bash deploy/deploy.sh all        # backend → verify
```

Or individually:

| Command | Does |
|---------|------|
| `deploy/deploy.sh backend` | Cloud Build the API+SPA image (SPA built in stage 1 with the `_VITE_FIREBASE_*` substitutions), `docker pull` + `docker-compose up -d` on the VM, wait for `/health`. Also ships the `aggregate_data` / `dashboard_generator` stdio MCP servers, which live *inside* the API image at `/app/mcp/<name>` (unlike `mcp-image`/`fn-image`) — redeploy `backend` to update them. |
| `deploy/deploy.sh frontend` | Alias of `backend` — the SPA ships inside the API image. |
| `deploy/deploy.sh mcp-image` | Cloud Build the forked `db_server` MCP image (`mcp-db-server:1.3.1-ob1`) and `docker pull` it on the VM. |
| `deploy/deploy.sh fn-image` | Cloud Build the `custom_function` MCP image + `docker pull` on the VM (+ functions dir). |
| `deploy/deploy.sh grafana` | Provision + start the self-hosted Grafana on the VM (env gen, datasources, health). |
| `deploy/deploy.sh nginx` | scp `docker-compose.gce.yml` + nginx conf to the VM, `nginx -t` + reload. Run only when those files change. |
| `deploy/deploy.sh add-user EMAIL [ROLE]` | **Break-glass**: upsert a row in `openbench_users` via psql (default role `admin`). Primary flow is the admin panel. |
| `deploy/deploy.sh remove-user EMAIL` | **Break-glass**: delete the `openbench_users` row via psql. |
| `deploy/deploy.sh init-appdb` | Create the `appdata` DB + `mart` schema + `mcp_app` role on Cloud SQL (idempotent). |
| `deploy/deploy.sh seed-mcp-db FILE.sql` | Load a `.sql` file into the `appdata` Postgres DB (the `db_server` data). |
| `deploy/deploy.sh wipe-chat-data` | **DESTRUCTIVE**: drop all chat sessions/memory/sources and clear uploads/downloads on the VM (leaves published dashboards, MCP registry, functions, Grafana intact). Used once for the user-isolation rollout. |
| `deploy/deploy.sh backups` | Enable + verify Cloud SQL automated daily backups + PITR on `openbench-postgres` (idempotent). See "Backups & restore". |
| `deploy/deploy.sh verify` | Probe health/auth/hardening/network on the live deployment. |

All identifiers are defaults in `deploy.sh`; override any via env or a gitignored
`deploy/deploy.env` (e.g. `PUBLIC_HOST=...`, `VM_ZONE=...`).

### Build speed

`deploy.sh backend` used to take ~20 min. Three things keep it down; if a
deploy suddenly gets slow again, check these first.

**1. Build context — keep it small.** `gcloud builds submit` tars the *repo
root*. Measure it before blaming the network:

```bash
gcloud meta list-files-for-upload . | wc -l
```

Expect **~1.1k files / ~9 MB**. It was 53,690 files / 1,236 MB until
`.gcloudignore` started excluding `mcp/*/{data,models,weights,.venv}/` —
1.17 GB of local-dev model weights and CIFAR data that no deployed container
reads (`image_search` bind-mounts `/app-data/image-search/*`; SAM's weights
are baked into `openbench/sam-segmentation-mcp:cpu` at `/models/sam3.pt`).
If that number jumps, something new landed in the tree that `.gcloudignore`
does not match.

Two traps in `.gcloudignore`: it **replaces** `.gitignore` (gcloud stops
reading `.gitignore` the moment `.gcloudignore` exists), and a blanket
`mcp/` rule must never be re-added — it breaks prod MCP discovery with
`Errno 2`, because `aggregate_data` / `dashboard_generator` run with cwd
`/app/mcp/<name>` *inside* the API image. Exclude subdirs, never the tree.

**2. Cloud Build worker.** `cloudbuild.general-chat.yaml` sets
`machineType: E2_HIGHCPU_8` (the default worker is 2 vCPU) and
`timeout: 2400s`, matching `cloudbuild.controlled-source-chat.yaml`.
Non-default machine types are outside the Cloud Build free tier.

**Do not swap the docker builder for kaniko.** It was tried (build
`c6755ac8-316b-4f90-9898-b48c7098f42c`) and died with **exit 137 (OOM)**
after 12 min — kaniko snapshots the whole filesystem after every `RUN`
layer, and torch + docling + Playwright Chromium does not fit in
`E2_HIGHCPU_8`'s 8 GB. A `--cache-from` warm-up has its own trap: pulling
the previous ~multi-GB `:latest` onto the builder can cost more than the
cache saves.

**3. There is no layer cache, and fixing that needs the Dockerfile first.**
`Dockerfile.general-chat` puts `COPY . /app` (`:59`) *before* the pip
install (`:61-63`) and the Playwright Chromium download (`:66`), so any
source edit invalidates both — no cache backend can help while that
ordering stands. Moving the `playwright install` line above `COPY . /app`
is a one-line change and the single biggest remaining win; doing the same
for pip needs a pinned requirements file plus `pip install --no-deps -e .`
at the end.

## Environment variables

**Repo-safe (committed):** `.env.example.gcp` is the template. The public Firebase
web config (`VITE_FIREBASE_*`) is baked into `deploy.sh` (it ships in the JS bundle
— not a secret).

**VM-only secrets (never in the repo — live in `/home/Admin/openbench-deploy/.env.gcp`):**

| Var | Purpose |
|-----|---------|
| `GOOGLE_API_KEY` | Gemini API key |
| `GENERAL_CHAT_DATABASE_URL` | Cloud SQL Postgres URL for chat memory (with password) |
| `MCP_DB_DATABASE_URL` | `db_server` MCP → `appdata` over the Cloud SQL public IP (`mcp_app` role) |
| `APPDATA_ADMIN_URL` | admin URL used by `init-appdb` / `seed-mcp-db` (DDL + seeding) |
| `MCP_ALLOW_WRITES` / `MCP_MAX_ROWS` | enable agent write/materialize; read-query row cap |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin login + the API's dashboard pushes |
| `GRAFANA_PG_PASSWORD` | provisioned Postgres datasource (same value as `mcp_app`) |
| `GRAFANA_PUBLIC_URL` | browser-facing Grafana base (`https://<host>/grafana`) |
| `CUSTOM_FN_DATA_PATH` | VM dir holding user-defined functions (custom_function MCP) |
| `GENERAL_CHAT_FIREBASE_PROJECT_ID` | enables auth; must be `sss-poc1-corporate` |
| `GENERAL_CHAT_BOOTSTRAP_ADMIN` | comma-separated admin emails, seeded into `openbench_users` **only when the table is empty**; also gates seeding the default `soft-grounded` persona |
| `GENERAL_CHAT_ALLOWED_EMAILS` | legacy allowlist — now only a first-boot seed (role `user`); safe to remove once users show up in the admin panel |
| `GENERAL_CHAT_ALLOWED_DOMAINS` | no longer consulted at runtime |
| `GENERAL_CHAT_ALLOWED_ORIGINS` | CORS allowlist — same-origin now; keep only localhost dev origins if needed |
| `GENERAL_CHAT_GCP_BUCKET` / `GENERAL_CHAT_GCP_PUBSUB_SUBSCRIPTION` | GCS + worker |
| `OPENBENCH_DOWNLOAD_SECRET` | HMAC secret for signed `/downloads` links (`openssl rand -hex 32`); unset = legacy public-by-URL. Old unsigned links stop working once set — users re-run the export |
| `OPENBENCH_DOWNLOAD_TTL_SECONDS` | signed-link lifetime (default `86400` = 24 h) |
| `OPENBENCH_API_BIND=127.0.0.1` / `OPENBENCH_IMAGE` | keep API private; image to run |

Full list with defaults: [`.env.example.gcp`](../.env.example.gcp).

## Source index & tabular store

Uploaded sources are chunked and embedded so a turn retrieves only the
passages that answer the question, and spreadsheets are converted to Parquet
so numeric questions are answered with SQL instead of by reading rows. Without
this, every ready source's full text goes into every prompt.

**Off by default.** Both flags below must be set; the prompt shape only changes
when `GENERAL_CHAT_SOURCE_CONTEXT_MODE` moves off `full`.

| Var | Default | Purpose |
|-----|---------|---------|
| `GENERAL_CHAT_SOURCE_INDEX_ENABLED` | `0` | chunk + embed uploads; load the retrieval skills |
| `GENERAL_CHAT_TABLE_PARQUET_ENABLED` | follows the flag above | convert spreadsheets/CSVs to Parquet |
| `GENERAL_CHAT_SOURCE_CONTEXT_MODE` | `full` | `full` = today's prompt · `auto` = cards for indexed sources · `cards` = also drop the full-text fallback |
| `GENERAL_CHAT_RETRIEVAL_TOP_K` | `6` | passages injected eagerly per turn |
| `GENERAL_CHAT_SOURCE_CARD_BUDGET` | `24000` | advisory char cap on the card block |
| `GENERAL_CHAT_SOURCE_INDEX_CONCURRENCY` | `2` | parallel embedding jobs on the local upload path |
| `GENERAL_CHAT_TABLE_MAX_ROWS` / `GENERAL_CHAT_TABLE_QUERY_TIMEOUT_S` | `1000` / `20` | DuckDB result and time caps |
| `OPENBENCH_DOC_INDEX_URL` | falls back to `GENERAL_CHAT_DATABASE_URL` | index backend; unset + no chat DB ⇒ SQLite under the storage root |
| `OPENBENCH_EMBEDDING_MODEL` / `OPENBENCH_EMBEDDING_DIM` | provider default / `1536` | keep the dimension ≤ 2000: pgvector's HNSW index does not support more |

**State it creates**

- Postgres tables `openbench_source_chunks` and `openbench_source_tables`,
  created on first use (self-migrating, `IF NOT EXISTS`).
- Parquet under `/app-data/openbench/tables/<owner>/<session>/<source_id>/` —
  inside the bind mount both `openbench-api` and `openbench-worker` already
  share, so **no compose change**. Deliberately outside `uploads/`, which the
  end-of-turn cleanup empties.
- SQLite equivalents (`source_index.sqlite3`, `source_tables.sqlite3`) when no
  database URL is set — local dev only.

The worker writes the index and the API reads it; both already have the volume
and `GENERAL_CHAT_DATABASE_URL`, so there is no new secret.

**One-time: pgvector.** Check first, as the app role usually cannot create
extensions:

```bash
psql "$GENERAL_CHAT_DATABASE_URL" -c "SELECT * FROM pg_available_extensions WHERE name='vector';"
```

If listed, enable it as a superuser: `CREATE EXTENSION IF NOT EXISTS vector;`
If not, nothing breaks — the store logs a warning and falls back to an array
column with a Python cosine scan, which is correct but slower.

**Rollout** (each step reversible on its own):

1. Enable the extension.
2. Add the vars to `.env.gcp` with `GENERAL_CHAT_SOURCE_INDEX_ENABLED=1` and
   `GENERAL_CHAT_SOURCE_CONTEXT_MODE=full`. Compose env changes do **not** apply
   on a plain `deploy.sh backend` — recreate the containers with `--env-file`
   and confirm the running container actually has the new values.
3. `bash deploy/deploy.sh backend` → `verify`. The prompt is unchanged here;
   upload a file and confirm chunks and Parquet appear, and watch upload latency.
4. Backfill existing sources:
   `python examples/general-chat/scripts/backfill_source_index.py --dry-run`,
   then without the flag. `--prune` removes artifacts whose source is gone.
5. Flip `GENERAL_CHAT_SOURCE_CONTEXT_MODE=auto` and recreate. Watch answer
   quality on real sessions — this is the behavioural risk, not the code.

**Rollback:** set `GENERAL_CHAT_SOURCE_CONTEXT_MODE=full` and recreate. The old
prompt returns exactly; chunks keep being written harmlessly.

### Optional: Pinecone vector store

The admin panel (**Pengaturan → Basis Data Vektor**) can switch the chunk index
from Postgres/pgvector to a Pinecone serverless index. The selection lives in
`openbench_app_settings` and applies to the API immediately (index singleton +
agent rebuild); the worker reads it **at startup only**.

| Var | Default | Purpose |
|-----|---------|---------|
| `PINECONE_API_KEY` | — | required for the `pinecone` selection; without it the app logs a warning and stays on the SQL index |
| `PINECONE_DOC_INDEX` | `openbench-source-chunks` | serverless index name — created on first use (metric cosine, dim = `OPENBENCH_EMBEDDING_DIM`) |
| `PINECONE_DOC_NAMESPACE` | `""` | namespace holding the chunk vectors |
| `PINECONE_CLOUD` / `PINECONE_REGION` | `aws` / `us-east-1` | serverless spec used at index creation |

**Rollout** (each step reversible on its own):

1. Add `PINECONE_API_KEY` to `.env.gcp`, then `bash deploy/deploy.sh backend`
   — the image build includes the `vector` extra (the `pinecone` SDK), and the
   rollout step recreates the containers with `--env-file`, which is what
   makes the new env var stick (a plain restart would not).
2. Copy the existing corpus — stored embeddings are reused, nothing is
   re-embedded:
   `python examples/general-chat/scripts/migrate_vectors_to_pinecone.py --dry-run`,
   then without the flag, then `--verify 20`.
3. Flip **Pengaturan → Basis Data Vektor** to `pinecone` in the admin panel.
4. Restart the worker container so new uploads index into Pinecone too.

**Rollback:** flip the setting back to `postgres` (and restart the worker).
The migration never writes to Postgres, so the pgvector corpus stays intact.

**Known limits:** keyword (full-text) recall degrades to vector-only on
Pinecone — exact rare-term lookups can miss chunks outside the vector top-k.
Postgres stays one dropdown flip away. Id listing (`--verify`, idempotent
re-index) requires a **serverless** index.

**Note:** `deploy.sh wipe-chat-data` drops the two new tables and removes the
Parquet directory. Chunks and Parquet are copies of uploaded content, so a wipe
that skipped them would leave deleted material answering questions.

`examples/controlled-source-chat` inherits all of this through `create_app()`.
It needs the same extension on its own `controlled_chat` database and the same
vars — flip it **separately, after** general-chat has soaked; its strict
grounding persona makes it the more retrieval-sensitive of the two.

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

## User & role management

**Primary flow — the admin panel.** Sign in as an admin → **Pengguna** page:
add an email + role (`admin` | `user`), change roles, or remove accounts.
Changes are effective on the user's next request — no restart. Guards: the
last admin cannot be demoted or deleted, and admins cannot delete themselves.

**Break-glass (lockout recovery)** — direct `openbench_users` upsert via psql
from the VM:

```bash
bash deploy/deploy.sh add-user someone@gmail.com admin
bash deploy/deploy.sh remove-user someone@gmail.com
```

The Firebase Console Users page only **views/disables** accounts — it does not
grant app access (the `openbench_users` table does).

## Persona & capability management (admin panel)

- **Persona** page: pick one of three templates — `soft-grounded` (default:
  cites curated/user sources when relevant, otherwise answers from general
  knowledge and says so), `strict` (answers ONLY from curated sources with
  mandatory citations — the controlled-source-chat posture), `general`
  (classic assistant) — or edit SOUL/STYLE/AGENTS/goal text directly. Saving
  hot-rebuilds the shared agent; on rebuild failure the old agent keeps
  serving and the error is shown.
- **Kemampuan** page: per-role feature toggles (attachments, session sources,
  MCP management, custom functions, dashboards, image search) + the global
  `file_generation` switch (loads/unloads the export-excel / pdf-tools /
  export-markdown skills, triggering an agent rebuild).
- **Sumber Global** page: upload files / paste text / add URLs into the shared
  knowledge base every chat turn is grounded on. Users see a read-only list in
  the chat's Sumber drawer.

## Migration (allowlist → roles table) — one-time runbook

1. Add `GENERAL_CHAT_BOOTSTRAP_ADMIN=serebrum01@serebrum.co.id` to the VM
   `.env.gcp` (keep the existing `GENERAL_CHAT_ALLOWED_EMAILS` line for the
   seed) and add `chat.serebrum.co.id` to Firebase Auth authorized domains.
2. `bash deploy/deploy.sh all` — first boot seeds `openbench_users`
   (bootstrap emails → `admin`, allowlist emails → `user`) and the
   `soft-grounded` persona, then serves the SSS SPA at the chat.serebrum.co.id origin.
3. Sign in as the bootstrap admin; verify the Pengguna page lists the seeded
   accounts and the Persona page shows `soft-grounded` (source `db`).
4. Remove `GENERAL_CHAT_ALLOWED_EMAILS` (and `GENERAL_CHAT_ALLOWED_DOMAINS`)
   from `.env.gcp`; `sudo docker-compose --env-file .env.gcp -f
   docker-compose.gce.yml up -d openbench-api` to restart. Seeding never runs
   again while the table is non-empty.
5. Retire the Firebase Hosting site — **done 2026-07-23** via
   `firebase hosting:disable` (see "Legacy Hosting URL" in the inventory).

## MCP DB server (db_server → Cloud SQL Postgres)

The `db_server` MCP is a vendored fork of
[souhardyak/mcp-db-server](https://github.com/Souhar-dya/mcp-db-server) at
[`examples/general-chat/mcp/db-server/`](../examples/general-chat/mcp/db-server/),
built to `mcp-db-server:1.3.1-ob1` in Artifact Registry. The API spawns it via the
mounted docker socket; it reaches Cloud SQL over the instance's **public IP**
(`MCP_DB_DATABASE_URL`) — the same path `GENERAL_CHAT_DATABASE_URL` already uses.

Data lives in the **`appdata`** database on the existing Cloud SQL instance
(separate from the `openbench` chat-memory DB):
- `public.*` — seeded business tables the agent reads.
- `mart.*` — tables the agent **materializes** (`materialize_query` → `CREATE TABLE
  mart.<name> AS SELECT …`) so Superset can chart computed datasets live.

The `mcp_app` role is scoped to `appdata` only (SELECT on `public`, full control of
`mart`). Writes are gated by `MCP_ALLOW_WRITES`; read queries are capped by
`MCP_MAX_ROWS`.

**Prerequisite:** the VM's public egress IP must be an **authorized network** on
the Cloud SQL instance (already true — chat memory uses the same public-IP path).

### First-time setup

```bash
bash deploy/deploy.sh mcp-image        # build + pull the forked image on the VM
# set MCP_DB_DATABASE_URL / APPDATA_ADMIN_URL / MCP_ALLOW_WRITES / MCP_MAX_ROWS
# in the VM .env.gcp (point at the Cloud SQL public IP; mcp_app password)
bash deploy/deploy.sh nginx            # push the updated compose (new API env)
bash deploy/deploy.sh backend          # rebuild API image + roll out
bash deploy/deploy.sh init-appdb       # create appdata + mart + mcp_app
bash deploy/deploy.sh seed-mcp-db deploy/appdb/init.sql
```

### Adding data (`.sql`)

```bash
# Edit deploy/appdb/seed.example.sql (or your own INSERTs), then:
bash deploy/deploy.sh seed-mcp-db deploy/appdb/seed.example.sql
```
`seed-mcp-db` scp's the file and applies it with a throwaway `postgres:16` psql
container using `APPDATA_ADMIN_URL` (Cloud SQL public IP) — re-runnable.

### Adding data (DBeaver, manual)

Connect DBeaver through a **local** cloud-sql-proxy (nothing is exposed publicly):

```bash
# on your laptop, authenticated with a GCP account that has roles/cloudsql.client
cloud-sql-proxy PROJECT:REGION:INSTANCE --port 5432
# DBeaver → new Postgres connection → host 127.0.0.1, port 5432, database appdata
```
Edits made in DBeaver are visible to the agent immediately (it queries live).

## Grafana (deploy-to-Grafana dashboards)

A self-hosted Grafana (`grafana/grafana:11.1.0`, bound to `127.0.0.1:3000`)
runs next to the API and is served by nginx at
**`https://chat.serebrum.co.id/grafana/`** (`GF_SERVER_ROOT_URL` +
`serve_from_sub_path`). Access model:

- **View** — anonymous access is enabled with the **Viewer** role: anyone with
  a dashboard link can view it, no login (same trust model as the `/d/{id}`
  public shares).
- **Edit** — requires the admin login (`admin` / `GRAFANA_ADMIN_PASSWORD` in
  the VM `.env.gcp`). Sign-up is disabled.

**Deploy flow:** the dashboard frame's **Deploy** button posts the ViewModel to
`POST /dashboard/deploy/grafana` (Firebase-auth). The API converts it with
`view_model_to_grafana(..., live=...)` and pushes it to Grafana over the compose
network (`http://grafana:3000`, `POST /api/dashboards/db`, `overwrite=true` with
a title-derived uid, so re-deploys update in place). Datasets backed by a real
`appdata` table (`public.*`/`mart.*` — discovered via `MCP_DB_DATABASE_URL`)
become **live Postgres panels** through the provisioned `appdata-postgres`
datasource (read-only `mcp_app` role); everything else is embedded as inline
CSV via the `testdata` datasource. The response `{url, live, inline}` reports
the split; the UI opens the URL in a new tab.

**Provisioning:** `deploy/grafana/datasources.yaml` (scp'd to the VM, mounted
read-only). The two datasource UIDs (`appdata-postgres`, `testdata`) are the
contract with `grafana_client.py` — don't rename one without the other.

### First-time setup

```bash
bash deploy/deploy.sh grafana   # env gen + provisioning + container + health
bash deploy/deploy.sh nginx     # publish the /grafana/ route
bash deploy/deploy.sh backend   # API with the deploy endpoint
bash deploy/deploy.sh frontend  # SPA with the Deploy button
bash deploy/deploy.sh verify    # includes /grafana/api/health + raw :3000 closed
```

Grafana state (dashboards, users) persists in `/app-data/grafana` (uid 472).

## Custom functions (user-defined Python the agent can run)

Users define Python functions in the app's **Functions** panel; the agent runs
them through the **`custom_function` MCP** (`mcp/custom-function-mcp/`,
image `custom-function-mcp:0.1.0` in Artifact Registry).

**Trust model:** definitions are auth-gated (Firebase + allowlist) and
validated (identifier name, syntax, exactly one top-level function, 64KB cap).
Execution is sandboxed — the MCP container is spawned per call with `--rm`,
`--network none`, `--memory 512m --cpus 1 --pids-limit 128`, a non-root user,
and the functions dir (`CUSTOM_FN_DATA_PATH=/app-data/custom-functions`)
mounted **read-only**; each run is a fresh subprocess with a hard timeout.
Fixed preinstalled libs (pandas, numpy, matplotlib, openpyxl, dateutil) — no
runtime pip, no network. The UI **Test run** goes through the same sandbox
(`POST /functions/{name}/run`).

### First-time setup

```bash
bash deploy/deploy.sh fn-image   # build + pull the sandbox image, create the dir
bash deploy/deploy.sh nginx      # push the updated compose (new API env + volume)
bash deploy/deploy.sh backend    # roll out the API (routes + bundled MCP config)
bash deploy/deploy.sh frontend   # SPA with the Functions panel
```

Smoke: Functions panel → save `add` (`def add(a, b): return a + b`) → Test run
with `{"a": 2, "b": 3}` → `5`; then in chat: "run the add function with a=2
b=3" → the agent calls `custom_function.run_function`.

## Verify

```bash
bash deploy/deploy.sh verify
```
Expected: `/health` 200 · `/persona` 401 (no token) · `/openapi.json` 404
(docs disabled) · raw `:8080` unreachable. Real end-to-end:
open `https://chat.serebrum.co.id`, sign in with an authorized Google account,
send a message.

## Backups & restore

```bash
bash deploy/deploy.sh backups    # enable + verify (idempotent)
```

Configures the shared Cloud SQL instance `openbench-postgres`: automated daily
backups at 18:00 UTC (01:00 WIB, off-hours), 14 backups retained, point-in-time
recovery with 7 days of transaction logs. Enabling PITR the first time turns on
WAL archiving and can briefly restart the instance — run off-hours.

> **History:** on 2026-08-04 backups were found **disabled** on the live
> instance (zero backups existed) even though this section claimed otherwise —
> the config does not survive instance recreation. `deploy.sh backups` was
> re-run and coverage verified. **Re-run it after any instance recreate/clone
> promotion**, and treat "backups enabled" as something to verify
> (`gcloud sql backups list`), not assume.

**Covered** (everything on the instance):

| Database | Contents |
|----------|----------|
| `openbench` | chat sessions, memory, sources, `openbench_users`, settings |
| `controlled_chat` | the controlled-source-chat Cloud Run deployment's state |
| `appdata` | `db_server` MCP mart data |

**NOT covered** — VM-disk state under `/app-data`: uploads, downloads,
Grafana SQLite, MCP registry files. Uploads are additionally copied to the
GCS forever-archive when `GENERAL_CHAT_ARCHIVE_BUCKET` is set; otherwise
they are single-copy on the VM disk.

**Restore — recommended path (clone, non-destructive):**

```bash
gcloud sql backups list --instance=openbench-postgres --project sss-poc1-corporate
# PITR clone to a new instance (UTC, RFC3339); or use --backup-id=BACKUP_ID
gcloud sql instances clone openbench-postgres openbench-postgres-restore \
  --project sss-poc1-corporate \
  --point-in-time "2026-07-20T02:00:00Z"
# Give the clone a public IP + the VM's egress IP as an authorized network,
# then on the VM edit .env.gcp (GENERAL_CHAT_DATABASE_URL, MCP_DB_DATABASE_URL,
# APPDATA_ADMIN_URL → clone IP), update the hardcoded Postgres IP in
# deploy/grafana/datasources.yaml (uid appdata-postgres) + rerun
# `deploy/deploy.sh grafana`, and recreate the containers:
sudo docker-compose --env-file .env.gcp -f docker-compose.gce.yml up -d --force-recreate
bash deploy/deploy.sh verify
```

Keep the clone (update this inventory) or `pg_dump`/restore back and delete it.

**Restore — in-place (destructive):**

```bash
gcloud sql backups restore BACKUP_ID --restore-instance=openbench-postgres \
  --project sss-poc1-corporate
```

> **Warning:** in-place restore overwrites **all three databases** on the shared
> instance, including `controlled_chat`, which belongs to the separate Cloud Run
> deployment. Prefer the clone path.

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

- **Frontend:** ships inside the API image — roll back the backend (below).
- **Backend:** images are tagged `:latest`; to roll back, on the VM
  `sudo docker pull <image>@<previous-sha256>` then `... up -d`, or rebuild from a
  prior git commit. Previous `.env.gcp` is backed up as `.env.gcp.bak-*` before edits.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `TypeError: NetworkError` in browser | SPA built with wrong `VITE_BACKEND_URL`. Rebuild + redeploy frontend so it targets `https://chat.serebrum.co.id`. |
| `auth/configuration-not-found` on sign-in | Google provider not enabled — see "Enable Google sign-in". |
| Signed-in user gets "Access not authorized" / 403 | Email not in `GENERAL_CHAT_ALLOWED_EMAILS` — run `add-user`. |
| 502 right after a deploy | API still booting (MCP seed ~60s). `deploy.sh backend` waits for `/health`; otherwise re-check shortly. |
| Chat doesn't stream | nginx `/awp` must have `proxy_buffering off` — run `deploy/deploy.sh nginx`. |
| `gcloud builds submit` exits 1 but build is fine | Log-streaming permission quirk. `deploy.sh` uses `--async` + polling to avoid it. |
| Windows git-bash `curl` errors `(43)` | Schannel-curl quirk (hit the old all-numeric sslip.io host). `deploy.sh verify` auto-falls back to PowerShell `Invoke-WebRequest`; from Linux/Cloud Shell curl works directly. |

## Out of scope

`examples/lci-mini` (a separate example using Cloud Run, project `openbench-lci`)
is unrelated and untouched by this runbook.

`examples/controlled-source-chat` deploys to **Cloud Run** in this same project
(service `controlled-source-chat`, its own `controlled_chat` database on the
shared `openbench-postgres` instance) with local username/password auth instead
of Firebase. Its runbook is
[`examples/controlled-source-chat/DEPLOY.md`](../examples/controlled-source-chat/DEPLOY.md);
nothing in this file applies to it except the shared Cloud SQL instance.
