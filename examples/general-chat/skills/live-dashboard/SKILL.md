# live-dashboard

Create dashboards that stay bound to a database instead of a one-off
snapshot. Each panel is backed by a SQL query run through the `db_server`
MCP; the server re-runs the queries on a schedule, detects changes and
pushes the refreshed dashboard to every viewer (chat side panel and the
public `/d/{id}` page) over server-sent events.

Use this when the user wants a dashboard *from a database* (as opposed to
an uploaded CSV/XLSX, which the dashboard_generator MCP handles) or asks
for a dashboard that updates by itself.

## Triggers

- "buatkan dashboard dari database ...", "dashboard live", "dashboard
  realtime", "dashboard yang update otomatis"
- User asks for a dashboard over tables reachable with `db_server`
- User wants an existing live dashboard changed, refreshed, published,
  paused, or its refresh interval altered
- User asks which live dashboards exist

## Tools

- create_live_dashboard: save queries + a ViewModel template, run once,
  render in the side panel, start the schedule
- update_live_dashboard: change queries / panels / title / interval /
  public / enabled on an existing dashboard (prefer this over recreating)
- list_live_dashboards: the caller's live dashboards with status
- refresh_live_dashboard: re-run the queries now and push the result

## Protocol

1. **Explore the schema first.** Call `db_server.list_tables`, then
   `db_server.describe_table` for every table you intend to use. Never
   guess column names.
2. **One aggregate SELECT per panel.** Write small `GROUP BY` /
   `SUM` / `COUNT` queries that return exactly the rows a chart needs
   (<= a few hundred rows). A KPI query returns ONE row with ONE named
   column. Put aggregates in the outer query: the server rewrites any
   `LIMIT n` in the statement text, including sub-queries.
3. **Read-only, single statement.** Only `SELECT` / `WITH ... SELECT`.
   No `;`, no INSERT/UPDATE/DELETE/DDL. Use the database's own dialect
   (SQLite vs PostgreSQL date functions differ).
4. **Optionally smoke-test** a tricky query with `db_server.execute_sql`
   plus `LIMIT 5` before saving it.
5. **Call `create_live_dashboard` once** with:
   - `queries`: `{ "dataset_key": "SELECT ..." }` -- keys are lowercase
     snake_case and become the dataset names.
   - `view_model`: a template whose panels REFERENCE datasets, never
     inline rows:
     `{"kpis": [{"label": "Total Pendapatan", "dataset": "total",
     "value_column": "total", "format": "currency"}],
     "sections": [{"title": "Wilayah", "items": [{"type": "chart",
     "chart_type": "bar", "title": "Pendapatan per wilayah",
     "dataset": "by_region", "x_field": "region", "y_field": "revenue"}]}]}`
     Tables: `{"type": "table", "title": "...", "dataset": "...",
     "columns": [...]}`.
   - `refresh_interval_seconds`: default 60; minimum 15; `0` = manual
     only. Honor the user's wording ("setiap 5 menit" -> 300).
   - `public`: only when the user asks for a shareable link.
6. **Fix and retry within the turn.** The tool runs every query once and
   returns `errors` per dataset plus `rowCounts`. If a query failed, fix
   the SQL and call `update_live_dashboard` with the corrected `queries`
   (do not create a second dashboard).
7. **Never paste the ViewModel back.** The dashboard is already rendered
   in the side panel. Summarize in the user's language: what it shows,
   the refresh interval, and the public link when `publicUrl` is present.
8. **Revisions** go through `update_live_dashboard` using the `id`
   returned at creation (or found via `list_live_dashboards`).

## Version

0.1.0
