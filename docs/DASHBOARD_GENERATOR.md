# Dashboard Generator

OpenBench dashboard generation is a metadata-first workflow for CSV/XLSX data.
Agents inspect file metadata, aggregate data with read-only SQL, then send a
declarative dashboard ViewModel to the Dashboard Generator MCP.

## Components

- Aggregate Data MCP
  - `aggregate_data.extract_metadata`
  - `aggregate_data.aggregate_data`
- Dashboard Generator MCP
  - `dashboard_generator.generate_dashboard`
  - `dashboard_generator.search_dashboards`
  - `dashboard_generator.load_dashboard`
- Rendering adapters
  - default local HTML/A2UI export
  - optional Stitch adapter

The dashboard generator focuses on rendering and persistence memory. Metadata
extraction and SQL aggregation are intentionally handled by Aggregate Data MCP.

## Environment

| Variable | Purpose |
| --- | --- |
| `OPENBENCH_EXPORT_DIR` | Directory for generated dashboard HTML |
| `OPENBENCH_EXPORT_URL_BASE` | Public URL prefix returned in dashboard artifacts |
| `OPENBENCH_DASHBOARD_STATE_PATH` | Shared state/memory JSON file |
| `DASHBOARD_RENDER_ADAPTER` | `default`, `stitch`, or `auto` |
| `STITCH_API_KEY` | Optional Stitch credential |
| `STITCH_API_URL` | Optional Stitch endpoint; `/mcp` URLs use JSON-RPC MCP mode |

## Agent SOP

When the user asks to load a previous dashboard:

1. Use `dashboard_generator.load_dashboard(latest=true)` for "last/latest/terakhir".
2. Use `dashboard_generator.search_dashboards(query=...)` when the user names a
   dashboard, source file, template, or older data set.
3. Call `dashboard_generator.load_dashboard(dashboard_id=...)` with the selected id.
4. Do not regenerate unless no memory match exists or the user explicitly asks
   for a new dashboard.

When the user asks for a new dashboard from CSV/XLSX data:

1. Locate the uploaded spreadsheet path from source metadata.
2. Call `aggregate_data.extract_metadata(path=...)`.
3. Write read-only SQLite `SELECT` or `WITH` queries against table `data`.
4. Call `aggregate_data.aggregate_data(path=..., query=[...])` once with all
   datasets needed for KPIs/charts/tables.
5. Build a canonical declarative ViewModel.
6. Pass an uploaded template via `template_path` only when requested.
7. Call `dashboard_generator.generate_dashboard(view_model=...)`.

`generate_dashboard` automatically stores successful artifacts in dashboard
memory and returns a saved artifact instead of rendering a different dashboard
when the source-data fingerprint and template fingerprint exactly match a prior
dashboard.

## ViewModel Shape

Prefer this canonical shape:

```json
{
  "title": "Sales Dashboard",
  "description": "Overview of uploaded sales data.",
  "kpis": [
    {"label": "Total Revenue", "value": 1200, "value_format": "$0,0.00"}
  ],
  "sections": [
    {
      "title": "Performance",
      "items": [
        {
          "type": "chart",
          "chart_type": "bar",
          "title": "Revenue by Region",
          "data": [{"region": "EU", "revenue": 1200}],
          "x_field": "region",
          "y_field": "revenue"
        },
        {
          "type": "table",
          "title": "Top Regions",
          "data": [{"region": "EU", "revenue": 1200}],
          "columns": ["region", "revenue"]
        }
      ]
    }
  ]
}
```

Agents should not include raw HTML, CSS, JavaScript, Chart.js config, or nested
component dialects. The backend has a normalizer fallback, but deterministic
generation depends on the canonical ViewModel.

## Uploaded Templates

Dashboard templates are optional. General Chat exposes uploaded templates as
`Dashboard template path:` in source context. Supported files:

- `.html` / `.htm`
- markdown design briefs such as `design.md` or `dashboard-template.md`

Pass the template path to:

```text
dashboard_generator.generate_dashboard(..., template_path="<path>")
```

Templates affect the HTML export/fallback and optional Stitch guidance. The
interactive chat artifact remains the canonical A2UI ViewModel.

## Persistence Memory

Dashboard memory lives in the shared state JSON file configured by
`OPENBENCH_DASHBOARD_STATE_PATH`. It stores the exact artifact plus source and
template fingerprints. See
[`DASHBOARD_PERSISTENCE_MEMORY.md`](DASHBOARD_PERSISTENCE_MEMORY.md).

## General Chat

The `examples/general-chat` app uses the standalone MCP path for dashboard
requests. Spreadsheet uploads are stored as sources with local paths. Generated
dashboard artifacts appear as assistant links and in the side-by-side dashboard
artifact panel.
