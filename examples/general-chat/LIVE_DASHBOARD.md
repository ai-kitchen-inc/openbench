# Live (database-bound) dashboards

A live dashboard is a dashboard whose panels are backed by SQL instead of a
frozen snapshot. The server re-runs the SQL through the `db_server` MCP on a
per-dashboard interval, detects changes and pushes the refreshed ViewModel to
every viewer over server-sent events (SSE). Both the chat side panel and the
public `/d/{id}` page stay current without re-generating anything.

This complements the upload-based
[dashboard generator](DASHBOARD_GENERATOR.md): that one renders a snapshot of
a CSV/XLSX, this one binds to a database.

## Concept

```
chat: "buatkan dashboard live dari database penjualan, refresh 30 detik"
  │
  ▼  agent explores schema (db_server.list_tables / describe_table), writes SQL
create_live_dashboard(queries, view_model template)      ← skills/live-dashboard
  │  runs the queries once, saves the record, renders in the side panel
  ▼
LiveDashboardScheduler (API process, tick every 5 s)
  │  due dashboard → LiveQueryRunner → db_server.execute_sql_json (one MCP
  │  client per cycle) → hash datasets → changed? hydrate ViewModel, version+1
  ▼
LiveDashboardHub → SSE subscribers
  ├─ chat frame      GET /dashboard/live/{id}/events   (bearer header, fetch-based SSE)
  └─ public page     GET /d/{id}/events                (EventSource, only when public)
```

Code: `src/general_chat/live_dashboard/` (models, store, runner, hub,
scheduler, sqlguard), routes in `server/app.py` ("Live dashboards" block), the
chat tools in `skills/live-dashboard/`, the SDK frame changes in
`studio/chat-ui/src/a2ui/custom/use-live-dashboard.ts`, and the frontend
transport in `frontend/src/chat/liveDashboard.ts` + `frontend/src/dashboard/`.

## Record shape

Stored per dashboard (`openbench_live_dashboards` in Postgres, or
`<storage>/live_dashboards/<id>.json` locally):

```json
{
  "id": "a1b2c3d4e5f6",
  "owner": "user@example.com",
  "title": "Penjualan",
  "serverId": "server-…",            "namespace": "db_server",
  "queries": {
    "by_region": {"sql": "SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY region", "maxRows": 500},
    "total":     {"sql": "SELECT SUM(revenue) AS total FROM sales", "maxRows": 500}
  },
  "template": {
    "kpis": [{"label": "Total", "dataset": "total", "value_column": "total"}],
    "sections": [{"title": "Wilayah", "items": [
      {"type": "chart", "chart_type": "bar", "title": "Per wilayah",
       "dataset": "by_region", "x_field": "region", "y_field": "revenue"}]}]
  },
  "refreshIntervalSeconds": 60,   "enabled": true,   "public": false,
  "version": 3,  "dataHash": "sha256:…",
  "snapshot": {"datasets": {…}, "viewModel": {…canonical, rows inlined…}, "errors": {}, "refreshedAt": "…"},
  "lastRefreshAt": "…", "lastError": null, "nextRunAt": "…"
}
```

- The **template** is stored un-normalized (panels reference `dataset` keys).
  Each refresh runs `normalize_dashboard_view_model(template + datasets)`,
  which inlines the rows — the same normalizer every dashboard uses.
- `queries` must be single read-only `SELECT`/`WITH … SELECT` statements
  (no `;`, no DML/DDL); keys are `^[a-z][a-z0-9_]{0,63}$`; at most 20.
- `refreshIntervalSeconds`: `0` = manual only, otherwise clamped to 15…86400.

## REST + SSE contract

Authenticated (`/dashboard` prefix: bearer token, capability `dashboards`,
owner-scoped; admins may read every record):

| Method | Path | Notes |
|---|---|---|
| `GET` | `/dashboard/live` | caller's dashboards (no snapshot, with `rowCounts`) |
| `POST` | `/dashboard/live` | body `{title, queries, viewModel, refreshIntervalSeconds?, description?, public?, serverId?}` → 201 record (queries run once) |
| `GET` | `/dashboard/live/{id}` | full record incl. queries + snapshot |
| `PATCH` | `/dashboard/live/{id}` | any subset of the create body plus `enabled`; changed queries/template re-run immediately |
| `POST` | `/dashboard/live/{id}/refresh` | run now, push to viewers, returns the public payload |
| `DELETE` | `/dashboard/live/{id}` | delete + `closed{reason:"deleted"}` to viewers |
| `GET` | `/dashboard/live/{id}/events` | SSE |

Public (no auth, **404 unless `public: true`**, never includes queries/owner/serverId):

| Method | Path | Notes |
|---|---|---|
| `GET` | `/d/{id}` | the SPA (public page) when the live record is public; otherwise the legacy static HTML from `/dashboard/publish` |
| `GET` | `/d/{id}/data` | current public payload (JSON) |
| `GET` | `/d/{id}/events` | SSE |

SSE events (`event:` name, `data:` one-line JSON):

| Event | Payload | When |
|---|---|---|
| `snapshot` | `{id, title, description, viewModel, version, refreshedAt, refreshIntervalSeconds, errors, lastError, enabled, public}` | immediately on connect |
| `update` | same shape | data hash changed, definition changed, or manual refresh |
| `error` | `{id, version, error, errors, refreshedAt}` | every query failed (previous snapshot stays) |
| `closed` | `{id, reason: "deleted" \| "unpublished"}` | stream ends; clients must not reconnect |
| `ping` | `{}` | heartbeat every 15 s (keeps nginx `proxy_read_timeout` happy; clients reconnect after 45 s of silence) |

Partial failures keep the previous rows of the failing dataset and report the
message under `errors[datasetKey]`; the frame shows it as the badge tooltip.

## Chat tools (`skills/live-dashboard`)

`create_live_dashboard`, `update_live_dashboard`, `list_live_dashboards`,
`refresh_live_dashboard`. The skill's `SKILL.md` carries the protocol the
model follows (schema first, one aggregate SELECT per panel, template
references datasets, fix SQL via `update_live_dashboard`, never paste the
ViewModel back). The tools are bound to the server's store/runner/hub at
agent build (`create_agent(live_dashboard_bindings=…)`); the owner comes from
the per-turn ContextVar set by the chat handler.

## Environment

| Var | Default | Meaning |
|---|---|---|
| `GENERAL_CHAT_LIVE_DASHBOARD_ENABLED` | `1` | load the skill + start the scheduler |
| `GENERAL_CHAT_LIVE_DASHBOARD_TICK_SECONDS` | `5` | scheduler poll interval for due dashboards |
| `GENERAL_CHAT_LIVE_DASHBOARD_MAX_CONCURRENT_REFRESH` | `2` | parallel refresh cycles (each spawns one `db_server` container) |
| `GENERAL_CHAT_LIVE_DASHBOARD_QUERY_TIMEOUT_S` | `60` | per-query MCP call timeout |
| `GENERAL_CHAT_PUBLIC_BASE_URL` | `` | prefix for `publicUrl` returned to the agent (e.g. `https://chat.serebrum.co.id`) |
| `GENERAL_CHAT_MCP_DB_SERVER_CONFIG` | `db-server-docker.yaml` | which bundled db_server config `GENERAL_CHAT_SEED_ALL_MCP` seeds (`db-server-local.yaml` for the python/sqlite twin) |

The scheduler runs only in the API process (it needs the docker socket the
stdio `db_server` is spawned with); the GCS worker is untouched.

## Local recipe (sqlite, no docker)

```bash
python -m venv .venv-dbserver
.venv-dbserver/Scripts/pip install -r examples/general-chat/mcp/db-server/requirements.txt
python examples/general-chat/scripts/seed_live_demo_db.py      # prints MCP_DB_DATABASE_URL
```

Add to `examples/general-chat/.env` (local only):

```
DB_SERVER_MCP_PYTHON=<abs path>/.venv-dbserver/Scripts/python.exe
MCP_DB_DATABASE_URL=sqlite+aiosqlite:///<abs path>/examples/general-chat/.openbench/live-demo.db
GENERAL_CHAT_SEED_ALL_MCP=1
GENERAL_CHAT_MCP_DB_SERVER_CONFIG=db-server-local.yaml
# only when the API process cwd is not examples/general-chat (e.g. uvicorn from the repo root):
DB_SERVER_MCP_CWD=<abs path>/examples/general-chat/mcp/db-server
```

Then `openbench demo run general-chat`, check the MCP panel shows `db_server`
with `execute_sql_json`, and ask: *"buatkan dashboard live dari database
penjualan per wilayah, refresh 30 detik"*. Re-run the seed script to insert a
row; the panel updates within one interval. `curl -N -H "Authorization:
Bearer …" http://localhost:8005/dashboard/live/<id>/events` shows the raw
stream.

## Limits and caveats

- **One `docker run` per refresh cycle** (prod): all of a dashboard's queries
  share one MCP client, but every cycle pays the container cold start.
  Hence the 15 s floor and `MAX_CONCURRENT_REFRESH=2`.
- The fork's `execute_safe_query` rewrites every `LIMIT n` in the statement
  text, including sub-queries; put aggregates in the outer query.
- `execute_sql_json` ships in image `1.3.1-ob3`. Older images only expose
  `execute_sql`; its text table is parsed as a fallback, which cannot split
  cells that contain `" | "` — rebuild the image (`deploy.sh mcp-image`).
- Browser `EventSource` cannot send headers, so the authenticated stream is
  fetch-based; tokens are never placed in URLs. The public page uses native
  `EventSource`.
- Starlette's TestClient buffers streaming bodies, so SSE tests end the
  stream with a `closed` event (see `tests/test_general_chat_live_dashboard_routes.py`).
