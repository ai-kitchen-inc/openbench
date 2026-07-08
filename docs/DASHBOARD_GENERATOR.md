# Dashboard Generator

OpenBench includes a dashboard-generator SDK skill for metadata-first dashboard
creation from CSV/XLSX files. The feature is designed for chat agents and MCP
servers that need to inspect uploaded tabular data, aggregate it safely, then
return a rendered dashboard artifact without putting a full dataset into the LLM
context.

## What Changed

Added to the framework:

- `src/openbench/skills/dashboard-generator/`
  - `extract_metadata(path, sheet=None, sample_rows=5)`
  - `aggregate_data(path, query, sheet=None, dataset_id=None)`
  - `load_dashboard_memory(dashboard_id=None, source_path=None, source_signature=None, ...)`
  - `generate_dashboard(view_model, filename=None, output_dir=None, template_path=None, template_text=None, template_format=None, source_path=None, previous_dashboard_id=None, revision_notes=None)`
  - `adapters.py` registry plus separate adapter modules:
    `adapter_base.py`, `default_adapter.py`, and `stitch_adapter.py`
- `DashboardGenerator` in `src/openbench/output/generators.py`
- `DashboardRenderer` in `src/openbench/chat/renderers/dashboard.py`
- `ObDashboardFrame` in `studio/chat-ui/src/a2ui/custom/`
- MCP risk policy entries for dashboard read and artifact tools

No previous dashboard framework code was removed. The old
`DashboardGenerator` placeholder now renders local HTML dashboards from a
declarative ViewModel.

## Adapter Architecture

Dashboard generation is split into an agentic core and a presentation layer:

```text
Dashboard(StitchAdapter(A2UI(AgenticCore(LLM, (Skills, MCP)))))
```

The agentic core is responsible for understanding the uploaded file, writing
metadata-aware SQL aggregation queries, and producing a declarative ViewModel.
It does not generate HTML or vendor-specific instructions. Presentation
adapters are responsible for turning that ViewModel into an artifact.

The adapter contract lives in
`src/openbench/skills/dashboard-generator/`:

- `adapter_base.py`: `BaseAdapter` and `DashboardRenderResult`
- `default_adapter.py`: wraps OpenBench's built-in `DashboardGenerator`
- `stitch_adapter.py`: handles Stitch-specific HTTP/MCP calls
- `adapters.py`: small registry that selects the active adapter

`tools.py` no longer branches on vendor logic inside `_write_dashboard_html`.
It resolves an adapter and calls:

```python
adapter.render(view_model)
```

This keeps Skills/MCP/LLM orchestration independent from the presentation
technology.

## Dependency Injection

Applications can choose the presentation adapter in two ways.

Environment selection:

| Variable | Values | Purpose |
|----------|--------|---------|
| `DASHBOARD_RENDER_ADAPTER` | `auto`, `default`, `stitch` | Select dashboard presentation adapter |
| `OPENBENCH_DASHBOARD_RENDER_ADAPTER` | `auto`, `default`, `stitch` | Alternate namespaced selector |
| `STITCH_API_MODE` | `mcp`, `direct` | Optional override; `/mcp` URLs are detected automatically |

Runtime injection:

```python
skill.bind(dashboard_adapter="stitch")

skill.bind(
    dashboard_adapter_factory=lambda output_path, public_url: MyAdapter(
        output_path=output_path,
        public_url=public_url,
    )
)
```

Use `dashboard_adapter_factory` when the adapter needs per-render state such as
the target output path.

## Agent SOP

When the user asks for a dashboard from CSV/XLSX data, the agent should follow
this order:

1. Locate the uploaded file path from attachments or source metadata.
2. Call `extract_metadata(path=...)` and inspect `dashboard_memory.matches`.
3. Use only the metadata response to understand columns, roles, and SQL hints.
4. Write read-only SQLite `SELECT` or `WITH` queries against table `data`.
   Quote column names with double quotes when they contain spaces or
   punctuation, alias output columns clearly, and add `LIMIT` for large chart
   or table datasets.
5. Call `aggregate_data(path=..., query="...", dataset_id="...")`.
6. When regenerating the same dashboard or applying a revision, call
   `load_dashboard_memory` and use the stored `viewModel` as the layout base.
7. Build a declarative ViewModel. Treat this as A2UI-style data, not UI code.
   For revisions, send only the changed panel and pass `previous_dashboard_id`
   plus `revision_panel_titles` to `generate_dashboard`; unspecified panels and
   their top-level datasets are preserved.
8. Optionally pass a user-uploaded template with
   `generate_dashboard(view_model=..., template_path="...")`.
9. Call `generate_dashboard(view_model=..., source_path=...)`.
10. Return the generated link and a short explanation.

Step 6 must not include raw HTML, CSS, JavaScript, or renderer instructions.
The `generate_dashboard` tool owns the visual stitching.

For details on cross-session layout reuse and panel-level revision merging, see
[`DASHBOARD_PERSISTENCE_MEMORY.md`](DASHBOARD_PERSISTENCE_MEMORY.md).

## User-Uploaded Templates

Dashboard templates are optional. If no template is supplied, OpenBench keeps
the existing adapter selection: `default`, `stitch`, or `auto`.

When a user uploads a template in General Chat, the source context exposes a
`Dashboard template path:` line. Agents should pass that value to
`generate_dashboard(template_path=...)`. Supported uploaded template files are:

- `.html` / `.htm`: may include `{{title}}`, `{{description}}`, `{{body}}`,
  `{{openbench_css}}`, `{{dashboard_json}}`, and `{{generated_at}}`
  placeholders.
- `design.md` or markdown files with `design`/`template` in the name: treated
  as design briefs. Fenced `css` blocks are applied to the HTML export.

The visible chat artifact remains A2UI-first: `generate_dashboard` returns the
canonical `viewModel`, `datasets`, `kpis`, and `sections` for
`ObDashboardFrame`. The custom template affects the HTML export/fallback and
provides Stitch visual guidance.

## ViewModel Shape

```json
{
  "title": "Sales Dashboard",
  "description": "Overview of uploaded sales data.",
  "datasets": {
    "sales_by_region": [
      {"region": "EU", "revenue": 1200}
    ]
  },
  "kpis": [
    {"label": "Total Revenue", "value": 1200, "unit": "USD"}
  ],
  "sections": [
    {
      "title": "Performance",
      "items": [
        {
          "type": "chart",
          "chart_type": "bar",
          "title": "Revenue by Region",
          "dataset": "sales_by_region",
          "x": "region",
          "y": "revenue"
        }
      ]
    }
  ]
}
```

Supported panel types are `chart`, `table`, `text`, and `kpi`. Supported chart
types are `bar`, `line`, `area`, `pie`, and `scatter`.

## Stitch Integration

`StitchAdapter` checks these environment variables:

| Variable | Purpose |
|----------|---------|
| `STITCH_API_KEY` | Enables Stitch credentials |
| `STITCH_API_URL` | Stitch endpoint; `https://stitch.googleapis.com/mcp` is JSON-RPC MCP |
| `STITCH_API_MODE` | Optional `mcp` or `direct`; auto-detected from `/mcp` URLs |
| `STITCH_PROJECT_ID` | Optional existing Stitch project id; otherwise the adapter calls `create_project` |
| `STITCH_PROJECT_TITLE` | Optional title when creating a Stitch project |
| `STITCH_MCP_GENERATE_TOOL` | Optional MCP generate tool name, default `generate_screen_from_text` |
| `STITCH_DEVICE_TYPE` | Optional Stitch device type, default `DESKTOP` |
| `STITCH_MODEL_ID` | Optional Stitch model id, default `GEMINI_3_FLASH` |
| `STITCH_DESIGN_SYSTEM` | Optional Stitch design system asset id |
| `STITCH_TIMEOUT_SECONDS` | Optional request timeout, default `180` |
| `OPENBENCH_EXPORT_DIR` | Directory for generated HTML |
| `OPENBENCH_EXPORT_URL_BASE` | Public URL prefix for generated files |

If `STITCH_API_KEY` is present but `STITCH_API_URL` is not set, OpenBench falls
back through `DefaultGeneratorAdapter`. This avoids guessing a network endpoint
while still keeping the key ready for environments that provide one.

For MCP mode, the adapter does not post the ViewModel directly as HTML input.
It calls `tools/list`, then `tools/call` for `create_project` and
`generate_screen_from_text` (plus `get_screen` when available). If Stitch
returns embeddable HTML, OpenBench writes that HTML. If Stitch returns only
project/screen metadata, OpenBench writes a small HTML artifact containing the
Stitch reference instead of treating the successful MCP response as a failure.

## MCP Exposure

`OpenBenchMCPServer` auto-discovers SDK skill tools, so the dashboard
tools become MCP-callable through the normal OpenBench MCP tool registry.
Policy classification:

- `extract_metadata`: read
- `aggregate_data`: read
- `load_dashboard_memory`: read
- `generate_dashboard`: artifact write

## SQL Aggregation Contract

`extract_metadata` returns a `sql` block with the SQLite dialect, source table
name, identifier quote character, and available column names. `aggregate_data`
then loads the CSV/XLSX into an in-memory SQLite table, defaulting to `data`,
and executes the query.

Allowed query forms:

```sql
SELECT region, SUM(revenue) AS revenue
FROM data
GROUP BY region
ORDER BY revenue DESC
LIMIT 10
```

Only read-only `SELECT` or `WITH` statements are allowed. Multi-statement SQL
and destructive keywords such as `DROP`, `INSERT`, `UPDATE`, `DELETE`,
`CREATE`, `ALTER`, `ATTACH`, and `PRAGMA` are rejected before execution.

## General Chat Integration

The `examples/general-chat` app loads only the `dashboard-generator` SDK skill
by default. CSV/XLSX source uploads are stored as `kind="spreadsheet"` with a
`localFilePath` metadata entry. The chat handler passes that path to the agent,
and generated dashboard artifacts render as both an assistant link and a
side-by-side artifact window.
