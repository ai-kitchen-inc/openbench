# Dashboard Generator MCP

Standalone FastMCP server for the OpenBench dashboard-generator workflow.
Metadata extraction and aggregation are provided by the separate Aggregate Data
MCP, so this server focuses on dashboard rendering:

- `generate_dashboard`: render a declarative dashboard ViewModel as an A2UI
  dashboard artifact with an HTML export, optionally using a user-uploaded
  `.html` template or `design.md` design brief
- `search_dashboards`: search persisted dashboard memory across chat sessions
  by title, source file, template, or query text
- `load_dashboard`: publish the exact saved dashboard artifact back to chat

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `OPENBENCH_EXPORT_DIR` | `outputs/` | Directory for generated dashboard HTML files |
| `OPENBENCH_EXPORT_URL_BASE` | file path | URL prefix returned as `dashboardUrl` |
| `DASHBOARD_RENDER_ADAPTER` | `auto` | `default`, `stitch`, or `auto` |
| `STITCH_API_KEY` | unset | Optional Stitch credential |
| `STITCH_API_URL` | unset | Optional Stitch endpoint; `/mcp` URLs use MCP mode |
| `OPENBENCH_DASHBOARD_STATE_PATH` | `.openbench/dashboard_generator_state.json` | Shared dashboard memory/state file |

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
with `GENERAL_CHAT_DASHBOARD_SKILL_ENABLED=0`, then loads dashboard rendering
tools plus the separate Aggregate Data MCP:

- `aggregate_data.extract_metadata`
- `aggregate_data.aggregate_data`
- `dashboard_generator.generate_dashboard`
- `dashboard_generator.search_dashboards`
- `dashboard_generator.load_dashboard`

Generated dashboard exports are written to `examples/general-chat/downloads/`
and served from `/downloads/...`.

Uploaded templates are optional. In General Chat, upload a spreadsheet plus
`template.html` or `design.md`; the chat source context will expose
`Dashboard template path:`. Pass that path to
`dashboard_generator.generate_dashboard(template_path=...)`. Without it, the
server uses the configured `default`/`stitch`/`auto` adapter as before.

For dashboard requests, call `aggregate_data.extract_metadata`, then call
`aggregate_data.aggregate_data` once with all SQL queries needed for datasets,
then call `dashboard_generator.generate_dashboard`. The aggregate MCP writes
datasets into the shared dashboard state file so `generate_dashboard` can
hydrate referenced datasets even though metadata/aggregation and rendering live
in separate MCP servers. `generate_dashboard` also saves every rendered
dashboard into that state file and reuses a saved artifact when the current
source-data fingerprint and template fingerprint match. For requests like
"load dashboard terakhir" or "load dashboard yang kemarin dibuat pakai data A",
call `dashboard_generator.search_dashboards` as needed and then
`dashboard_generator.load_dashboard` instead of rebuilding.
