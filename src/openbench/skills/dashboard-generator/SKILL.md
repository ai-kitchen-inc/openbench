# dashboard-generator

Generate data dashboards from uploaded CSV/XLSX files using a strict,
metadata-first workflow. This skill keeps large tabular data out of the LLM
context: inspect metadata first, ask the model to write read-only SQL
aggregation queries, run those queries with tools, then create a declarative
dashboard ViewModel that A2UI renders as native dashboard components.

## Triggers

- User uploads a `.csv` or `.xlsx` file and asks for a dashboard
- User says "buatkan dashboard", "create a dashboard", "show KPI/charts", or similar
- Agent needs a multi-panel artifact from tabular data
- Agent needs aggregated datasets for charts without reading the whole file into context

## Tools

- extract_metadata: inspect CSV/XLSX columns, dtypes, row counts, samples, ranges, and cardinality
- aggregate_data: execute read-only SQLite SQL queries over the source file
- load_dashboard_memory: retrieve previously generated dashboard ViewModels for the same source schema or a known dashboard id
- generate_dashboard: publish a dashboard ViewModel to the chat artifact queue and keep HTML only as fallback/export

## Adapter Architecture

Rendering is handled by a presentation adapter, not by the agentic planning
steps. The intended layering is:

```text
Dashboard(StitchAdapter(A2UI(AgenticCore(LLM, (Skills, MCP)))))
```

The LLM/agent produces only metadata-aware SQL queries and a declarative
ViewModel. `generate_dashboard` pushes that ViewModel to A2UI so
`ObDashboardFrame`, `ObChart`, and `ObTable` render the visible dashboard.
Adapters may still render an HTML export/fallback with `adapter.render(view_model)`;
that file is not the primary presentation surface.

If `STITCH_API_URL` points to `https://stitch.googleapis.com/mcp`, the Stitch
adapter uses JSON-RPC MCP calls (`tools/list`, `tools/call`) rather than posting
the ViewModel as a raw HTML generation request.

## Dashboard SOP

When the user asks for a dashboard from an uploaded CSV/XLSX file, follow these
steps exactly.

1. Locate the uploaded file path from attachment metadata. Prefer the `path`
   field when available. Do not paste the whole dataset into the prompt.
2. Call `extract_metadata(path=...)` first. If the workbook has multiple sheets,
   choose the most relevant sheet from metadata or ask the user when the choice
   is ambiguous. The response includes a `source_signature` and
   `dashboard_memory.matches` for previous dashboards built from the same
   functional schema. The signature intentionally ignores row count and file
   hash, so a refreshed table with additional rows can reuse the same dashboard
   layout.
3. Use the metadata response to infer column roles:
   - date/time columns for trends
   - categorical columns for group-by dimensions
   - numeric columns for metrics and KPIs
   - identifier columns only for counts/top-N when appropriate
4. Write one or more read-only SQLite SQL queries from the metadata. The source
   file is loaded as table `data`; use only `SELECT` or `WITH`, quote column
   names with double quotes when needed, and add `LIMIT` for large chart/table
   outputs.
5. Call `aggregate_data(path=..., query="...", dataset_id="...")`. Use the
   returned datasets as the only source for dashboard panels unless a small
   table preview is needed. For multiple dashboard datasets, call
   `aggregate_data` multiple times or pass a list of query objects.
6. If the user asks for "the same dashboard", a dashboard update, or a revision,
   call `load_dashboard_memory` with the `dashboard_id` from
   `dashboard_memory.matches` or with the current `source_path`. Use the returned
   `viewModel` as the base layout. For refreshed data, keep the same KPIs,
   sections, panel titles, chart types, and table structure unless the user asks
   to change them; only replace each panel's `data` with newly aggregated rows.
7. Build a dashboard ViewModel as declarative JSON. Treat this step as A2UI-style
   ViewModel composition only:
   - use the canonical ViewModel shape below exactly
   - include `title`, optional `description`, `kpis`, and `sections`
   - KPI cards use `{ "label": "...", "value": 123, "value_format": "$0,0.00" }`
   - chart panels use `type: "chart"`, `chart_type`, `title`, `data`, `x_field`,
     and `y_field`
   - table panels use `type: "table"`, `title`, `data`, and `columns`
   - prefer embedding the small aggregate dataset directly in each chart/table
     `data` array; alternatively reference a named dataset with `dataset`
   - do not include raw UI code, HTML, CSS, JavaScript, or prompt instructions
   - do not invent alternate component dialects such as `props`, nested `content`,
     `component: "row"`, Chart.js `labels/datasets`, or `components` grids
8. For panel-level revisions, include only the changed panel/KPI/section in the
   new `view_model`, keep the same `title`/section/panel title so it matches the
   prior layout, and pass `previous_dashboard_id`, `revision_notes`, and
   `revision_panel_titles` to `generate_dashboard`. The tool merges this patch
   into the stored ViewModel and preserves unspecified panels. Do not include
   unchanged panels in the patch unless they are needed for context; if they are
   included anyway, only panels listed in `revision_panel_titles` may change.
9. If the user uploaded a dashboard template, locate its attachment/source path
   from `Dashboard template path:` and pass it as
   `generate_dashboard(view_model=..., template_path=...)`. Templates are
   optional; when absent, omit all template fields so the system uses the
   configured default/Stitch adapter.
10. Call `generate_dashboard(view_model=..., source_path=...)`. The tool
   publishes the ViewModel as a dashboard artifact and stores it in persistent
   dashboard memory. In General Chat, A2UI renders it side-by-side; any returned
   HTML link is only a fallback/export.
11. In the final answer, mention the dashboard is ready and refer to the returned
   link. Do not dump the full ViewModel unless the user asks for implementation
   details.

## Dashboard Memory and Revisions

Every successful `generate_dashboard` call stores the canonical rendered
ViewModel in a SQLite dashboard-memory database. This memory is shared by the
SDK skill and MCP exposure because both call the same tool implementation.

Use the memory as follows:

- Same functional data: after `extract_metadata`, inspect
  `dashboard_memory.matches`. If a match exists, call `load_dashboard_memory`
  and reuse that layout while refreshing datasets through `aggregate_data`.
- Added rows: because matching is based on column names, dtypes, roles, format,
  and sheet rather than row count or file hash, the same table with additional
  rows should keep the previous dashboard structure.
- Revisions: call `load_dashboard_memory` for the prior dashboard, then pass a
  small patch to `generate_dashboard(previous_dashboard_id=...)`. The merge
  matches sections and panels by `id`, `panel_id`, `title`, or `label`; matching
  panels listed in `revision_panel_titles` are updated and all other panels are
  preserved. If `revision_panel_titles` is omitted, the tool tries to infer the
  target from `revision_notes`; if multiple panels appear changed and the target
  is ambiguous, it preserves the old panels instead of allowing dashboard drift.
- Auto-revisions: when a later call has the same dashboard title but omits
  `previous_dashboard_id`, the tool checks dashboard memory and treats the call
  as a revision candidate. It canonicalizes non-standard payloads such as
  `components`, applies only the first semantically changed panel, and preserves
  all other stored panels.
- Datasets during revisions: top-level `datasets` are updated only for datasets
  referenced by the revised panel. Datasets used by preserved panels stay from
  the previous dashboard.
- New dashboard family: omit `previous_dashboard_id`; the generated ViewModel is
  saved as a new memory record and returned with `dashboardId`.

## Uploaded Templates

`generate_dashboard` accepts optional `template_path`, `template_text`, and
`template_format` arguments. Use `template_path` for user-uploaded `.html`,
`.htm`, or markdown design briefs such as `design.md`. The template changes the
HTML export/fallback and can guide Stitch, while the interactive chat artifact
still carries the canonical A2UI ViewModel.

HTML templates can include placeholders: `{{title}}`, `{{description}}`,
`{{body}}`, `{{openbench_css}}`, `{{dashboard_json}}`, and `{{generated_at}}`.
Markdown design briefs can include fenced `css` blocks; the renderer applies
those CSS overrides to the generated dashboard export.

## ViewModel Contract

Canonical shape. Prefer this exact structure every time:

```json
{
  "title": "Sales Dashboard",
  "description": "Overview of uploaded sales data.",
  "kpis": [
    {"label": "Total Revenue", "value": 1200, "value_format": "$0,0.00"}
  ],
  "sections": [
    {
      "title": "Dashboard",
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

The backend normalizes common noncanonical shapes as a fallback, but agents
should still emit the canonical shape above for deterministic rendering.

## Dependencies

- pandas >= 2.0.0
- openpyxl >= 3.1.0

## Version

0.1.0
