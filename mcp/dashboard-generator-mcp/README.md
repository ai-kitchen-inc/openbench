# Dashboard Generator MCP

Standalone FastMCP server for the OpenBench dashboard-generator workflow. It
exposes the same three tools as the SDK skill:

- `extract_metadata`: inspect CSV/XLSX columns, types, samples, and SQL hints
- `aggregate_data`: run read-only SQLite `SELECT`/`WITH` queries over the file
- `generate_dashboard`: render a declarative dashboard ViewModel as an A2UI
  dashboard artifact with an HTML export

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `OPENBENCH_EXPORT_DIR` | `outputs/` | Directory for generated dashboard HTML files |
| `OPENBENCH_EXPORT_URL_BASE` | file path | URL prefix returned as `dashboardUrl` |
| `DASHBOARD_RENDER_ADAPTER` | `auto` | `default`, `stitch`, or `auto` |
| `STITCH_API_KEY` | unset | Optional Stitch credential |
| `STITCH_API_URL` | unset | Optional Stitch endpoint; `/mcp` URLs use MCP mode |

## Run Locally

From the repo root:

```bash
pip install -e ".[all]"
cd mcp/dashboard-generator-mcp
python -m app.mcp_server --transport stdio
```

For HTTP testing:

```bash
python -m app.mcp_server --transport streamable-http --host 127.0.0.1 --port 8003
```

Smoke-test discovery:

```bash
python mcp/dashboard-generator-mcp/scripts/test_mcp_server.py --mode local
```

## Docker

```bash
docker compose -f mcp/dashboard-generator-mcp/docker-compose.yml --profile cpu build
docker compose -f mcp/dashboard-generator-mcp/docker-compose.yml --profile cpu run --rm dashboard-generator-mcp-cpu
```

## OpenBench

Expose the bundled OpenBench skill wrapper through the OpenBench MCP server:

```bash
openbench mcp list-tools --config mcp/dashboard-generator-mcp/openbench-mcp.yaml
openbench mcp serve --config mcp/dashboard-generator-mcp/openbench-mcp.yaml --transport stdio
```

## General Chat

Dedicated MCP-only dashboard run:

```powershell
cd examples\general-chat
.\scripts\run_with_dashboard_generator_mcp.ps1
```

Or use the built-in demo launcher:

```bash
openbench demo run general-chat-dashboard-generator
```

The dedicated runner disables the legacy SDK dashboard skill for that session
with `GENERAL_CHAT_DASHBOARD_SKILL_ENABLED=0`, then loads the MCP tools as:

- `dashboard_generator.extract_metadata`
- `dashboard_generator.aggregate_data`
- `dashboard_generator.generate_dashboard`

Generated dashboard exports are written to `examples/general-chat/downloads/`
and served from `/downloads/...`.

When using the dedicated launcher, General Chat keeps the dashboard stdio MCP
process open across the metadata, aggregation, and render calls. This avoids
Windows stdio cleanup delays from being reported as dashboard tool timeouts.
