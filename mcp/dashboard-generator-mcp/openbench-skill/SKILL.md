# dashboard-generator

Generate data dashboards from uploaded CSV/XLSX files using a strict,
metadata-first workflow. This skill keeps large tabular data out of the LLM
context: inspect metadata first, use the separate Aggregate Data MCP for
read-only SQL aggregation, then create a declarative dashboard ViewModel that
A2UI renders as native dashboard components.

## Triggers

- User uploads a `.csv` or `.xlsx` file and asks for a dashboard
- User says "buatkan dashboard", "create a dashboard", "show KPI/charts", or similar
- Agent needs a multi-panel artifact from tabular data
- Agent has or can obtain aggregated datasets for charts without reading the whole file into context

## Tools

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
2. Call `aggregate_data.extract_metadata(path=...)` first. If the workbook has multiple sheets,
   choose the most relevant sheet from metadata or ask the user when the choice
   is ambiguous.
3. Use the metadata response to infer column roles:
   - date/time columns for trends
   - categorical columns for group-by dimensions
   - numeric columns for metrics and KPIs
   - identifier columns only for counts/top-N when appropriate
4. Write one or more read-only SQLite SQL queries from the metadata. The source
   file is loaded as table `data`; use only `SELECT` or `WITH`, quote column
   names with double quotes when needed, and add `LIMIT` for large chart/table
   outputs.
5. Call the separate Aggregate Data MCP tool
   `aggregate_data.aggregate_data(path=..., query=[...])`. Use the returned
   datasets as the only source for dashboard panels unless a small table
   preview is needed. For multiple dashboard datasets, pass a list of query
   objects in one call.
6. Build a dashboard ViewModel as declarative JSON. Treat this step as A2UI-style
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
7. If the user uploaded a dashboard template, locate its attachment/source path
   from `Dashboard template path:` and pass it as
   `generate_dashboard(view_model=..., template_path=...)`. Templates are
   optional; when absent, omit all template fields so the system uses the
   configured default/Stitch adapter.
8. Call `generate_dashboard(view_model=...)`. The tool publishes the ViewModel
   as a dashboard artifact. In General Chat, A2UI renders it side-by-side; any
   returned HTML link is only a fallback/export.
9. In the final answer, mention the dashboard is ready and refer to the returned
   link. Do not dump the full ViewModel unless the user asks for implementation
   details.

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
