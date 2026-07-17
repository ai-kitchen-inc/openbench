# Dashboard Persistence Memory

Dashboard Generator MCP persists every successful dashboard into the shared
dashboard state JSON file so later chat sessions can reopen or consistently
reuse the same artifact.

## Storage

The state file path is resolved from:

1. `OPENBENCH_DASHBOARD_STATE_PATH`
2. `GENERAL_CHAT_DASHBOARD_STATE_PATH`
3. `.openbench/dashboard_generator_state.json`

The same file is shared with Aggregate Data MCP. Aggregate Data MCP stores the
latest `source_context` and named `aggregate_datasets`; Dashboard Generator MCP
stores dashboard memory under `dashboards`.

When `dashboards` is empty or incomplete, `search_dashboards` and
`load_dashboard` also scan `OPENBENCH_EXPORT_DIR` for existing dashboard HTML
exports that contain `openbench-dashboard-view-model`. Those exports are
backfilled into memory so dashboards created before the memory feature can still
be found by title/query and loaded again.

Each dashboard memory record contains:

- `id`: stable dashboard id, returned as `memory.dashboard_id`
- `match_key`: fingerprint key used for exact reuse
- `source`: source path, file name, file hash, sheet, row count, and column dtype signature
- `template`: template path/hash, inline template hash, or default template signature
- `artifact`: the exact saved dashboard artifact, including `viewModel`, datasets, URL, and path
- `created_at` / `updated_at`

## Matching Rules

For CSV/XLSX dashboards, `generate_dashboard` computes a source fingerprint from
the current shared `source_context`:

- file hash
- sheet
- row count
- column names and dtypes

It also computes a template fingerprint from `template_path`, `template_text`,
and `template_format`. If a saved dashboard has the same source fingerprint and
template fingerprint, `generate_dashboard` returns the saved artifact instead of
rendering a different dashboard. This preserves consistency when the same data
and template are used in a different chat session.

Dashboards without a source fingerprint are still saved, but their fallback key
includes the rendered ViewModel so unrelated source-less dashboards do not
overwrite each other.

## Tools

Dashboard Generator MCP exposes:

- `generate_dashboard`: render a new dashboard or reuse a saved exact
  source/template match; saves every successful artifact
- `search_dashboards`: search saved dashboards by title, source file/path,
  template file/path, source hash, or query text
- `load_dashboard`: publish a saved artifact back to chat by `dashboard_id`,
  `query`, or `latest=true`

## Agent Flow

For "load dashboard terakhir", call:

```text
dashboard_generator.load_dashboard(latest=true)
```

For "load dashboard yang kemarin pakai data A", call:

```text
dashboard_generator.search_dashboards(query="data A")
dashboard_generator.load_dashboard(dashboard_id="<matched id>")
```

For a dashboard request with an uploaded CSV/XLSX, keep the metadata-first flow
but search memory before aggregating:

```text
aggregate_data.extract_metadata
dashboard_generator.search_dashboards(source_path="...", template_path="...")
```

If the search result has `reusable_match=true`, or `exact_source_match=true`
with no conflicting template and the user did not request changes, load the
saved dashboard:

```text
dashboard_generator.load_dashboard(dashboard_id="<matched id>")
```

Only aggregate and generate when no reusable dashboard exists, or when the user
explicitly asks for a revision, chart/template/layout change, or another custom
change:

```text
aggregate_data.aggregate_data
dashboard_generator.generate_dashboard
```

`generate_dashboard` handles exact source/template reuse automatically.
