# Aggregate Data MCP

Standalone FastMCP server for general-purpose CSV/XLSX metadata inspection and
read-only aggregation. Use it when a user asks for grouped metrics, averages,
counts, top-N tables, or other tabular summaries without necessarily creating a
dashboard.

Tools:

- `extract_metadata`: inspect columns, types, samples, and SQLite hints
- `aggregate_data`: run read-only SQLite `SELECT`/`WITH` queries over the file

`aggregate_data` persists named datasets to the same dashboard state file used by
the dashboard-generator MCP. That lets dashboard workflows call this server for
aggregation, then call `dashboard_generator.generate_dashboard` to render.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `OPENBENCH_DASHBOARD_STATE_PATH` | `.openbench/dashboard_generator_state.json` | Shared state file for aggregate datasets |
| `GENERAL_CHAT_DASHBOARD_STATE_PATH` | unset | Alternate shared state path used by General Chat |

## Run Locally

From the repo root:

```bash
pip install -e ".[all]"
cd mcp/aggregate-data-mcp
python -m app.mcp_server --transport stdio
```

Smoke-test discovery:

```bash
python mcp/aggregate-data-mcp/scripts/test_mcp_server.py --mode local
```
