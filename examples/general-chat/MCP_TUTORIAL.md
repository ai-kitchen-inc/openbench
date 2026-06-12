# General Chat MCP Tutorial

This tutorial verifies MCP in three layers:

1. Raw OpenBench MCP tool discovery.
2. Direct MCP wrapper tests.
3. End-to-end use through the General Chat backend and UI.

General Chat keeps MCP disabled by default. Turn it on only when you want to
test MCP-backed tools.

## 1. Install MCP Extras

From the repository root:

```powershell
pip install -e ".[mcp]"
pip install -e examples/general-chat
```

The local General Chat tutorial uses an in-process MCP server first, so it does
not require Docker MCP Gateway or ToolHive.

## 2. Inspect OpenBench MCP Tools

From the repository root:

```powershell
openbench mcp list-tools --config examples/general-chat/mcp/openbench-mcp.yaml
```

You should see tools such as:

- `filter_records`
- `distinct_values`
- `group_and_aggregate`
- `top_n_records`
- `read_pdf`
- `export_to_excel`
- `web_search`

The General Chat agent only loads the approved query tools by default. The other
tools are visible at the MCP server layer so you can confirm the server exposes
the full SDK tool surface.

## 3. Run Focused MCP Tests

```powershell
python -m pytest tests/test_mcp_schema_policy.py tests/test_mcp_server_client.py -q
```

Expected result:

```text
15 passed
```

These tests validate schema conversion, policy checks, MCP server wrapping,
in-memory MCP transport, namespacing, and `ToolExecutor` compatibility.

## 4. Enable MCP In General Chat

Edit `examples/general-chat/.env` or set these in PowerShell:

```powershell
$env:GOOGLE_API_KEY="YOUR_KEY"
$env:GENERAL_CHAT_MCP_ENABLED="1"
$env:GENERAL_CHAT_MCP_MODE="local"
$env:GENERAL_CHAT_MCP_CONFIG="mcp/openbench-mcp.yaml"
$env:GENERAL_CHAT_MCP_APPROVED_TOOLS="openbench.filter_records,openbench.distinct_values,openbench.group_and_aggregate,openbench.top_n_records"
```

Then start the backend:

```powershell
cd examples/general-chat
uvicorn server:app --port 8005 --reload
```

Check health:

```powershell
Invoke-RestMethod http://localhost:8005/health
```

Check MCP tools:

```powershell
Invoke-RestMethod http://localhost:8005/mcp/tools
```

Expected fields:

- `enabled: true`
- `tool_count: 4`
- `namespaced_tool_names` includes `openbench.filter_records`
- `provider_tool_names` includes `openbench_filter_records`

## 5. Start The UI

In a second terminal:

```powershell
cd examples/general-chat/frontend
pnpm install
pnpm dev
```

Open `http://localhost:5173`.

## 6. Ask A Tool-Forcing Chat Prompt

Use a prompt that explicitly asks for MCP tools and provides structured records:

```text
Use the MCP tools to filter these records to region EU only, then tell me the count and rows:
[
  {"region": "EU", "revenue": 100},
  {"region": "US", "revenue": 200},
  {"region": "EU", "revenue": 150}
]
```

Expected behavior:

- The agent may call the MCP-backed `openbench_filter_records` tool.
- The final answer should say the count is `2`.
- The final answer should include the two EU rows.

Try another:

```text
Use the MCP tools to return distinct region values from:
[
  {"region": "EU"},
  {"region": "US"},
  {"region": "EU"}
]
```

Expected distinct values:

```text
EU, US
```

## 7. Policy Check

By default General Chat only loads query tools. If you ask for an export:

```text
Use MCP to export these records to Excel.
```

Expected behavior:

- The agent should not have an Excel export adapter loaded.
- It should explain that only the approved query tools are enabled for this
  local MCP test.

To test artifact tools later, add `openbench.export_to_excel` to
`GENERAL_CHAT_MCP_APPROVED_TOOLS`, restart the backend, and make sure you are
comfortable with file writes to the configured downloads directory.

## 8. Register Standard MCP JSON

Open the MCP Servers panel in the UI and paste standard MCP client JSON:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "mcp/playwright"
      ]
    }
  }
}
```

The app validates and saves the server config without starting the process.
Choose **Load tools** when you want General Chat to start the MCP server and
discover its tools. Discovered tools appear under the server with names,
descriptions, parameter summaries, and per-tool enable toggles.

You can also register from the API:

```powershell
$body = @{
  config = '{
    "mcpServers": {
      "playwright": {
        "command": "docker",
        "args": ["run", "-i", "--rm", "mcp/playwright"]
      }
    }
  }'
} | ConvertTo-Json
Invoke-RestMethod http://localhost:8005/mcp/catalogs/import -Method Post -ContentType "application/json" -Body $body
```

After loading tools, ask a prompt that explicitly uses the enabled server tools.
Disabled servers and disabled tools are not registered with the chat agent.

## 9. Run All Bundled MCP Integrations Together

Use the all-MCP launcher when you want one General Chat session that can use
SAM segmentation and ToolHive tools at the same time:

```powershell
openbench demo run general-chat --all-mcp
# or
openbench demo run general-chat-all --all-mcp
```

This path keeps General Chat in registry mode. It seeds the registry with:

- internal OpenBench tools
- filesystem MCP
- generic API MCP
- image-search MCP
- SAM 3 segmentation MCP
- Docker MCP Gateway
- currently running ToolHive workloads

It does not start ToolHive workloads automatically. Start ToolHive servers in
ToolHive UI or with `thv run ...` first, then launch General Chat with
`--all-mcp`.

All-MCP runs use a separate `.openbench/all-mcp` registry root. The regular
General Chat registry remains unchanged, and stale saved servers from normal
registry sessions are not loaded into `general-chat-all`.

Check the merged tool surface:

```powershell
Invoke-RestMethod http://localhost:8005/mcp/tools
```

Expected `namespaced_tool_names` include:

```text
openbench.filter_records
filesystem.read_file
generic_api.fetch_generic_api_data
image_search.list_index_stats
image_search.search_similar_images
sam_segmentation.count_objects_with_sam3
```

Docker MCP Gateway tools and ToolHive tools appear when those local services are
available and expose tools. Missing Docker, missing `npx`, missing SAM weights,
an unbuilt image-search index, or unavailable ToolHive are reported in startup
warnings and registry diagnostics instead of being silently skipped.
Optional MCP failures do not block other servers from loading; successful tools
remain available in the same session.

Prepare optional dependencies before a full local smoke test:

```powershell
hf auth login
docker compose -f mcp\generic-api-mcp\docker-compose.yml --profile cpu build
docker compose -f mcp\image-search-mcp\docker-compose.yml --profile cpu build
docker compose -f mcp\sam-segmentation-mcp\docker-compose.yml --profile cpu build
docker mcp profile create --name openbench
thv serve
thv run toolhive-doc-mcp
```

Use the focused launchers below when you want to debug only one MCP server.

## 10. ToolHive MCP Servers

General Chat can connect to MCP servers launched or proxied by ToolHive. The
recommended flow is to manage server install, configuration, secrets, and logs in
ToolHive UI, then import the running ToolHive proxy URL into OpenBench. This
does not use `thv client setup`; OpenBench is a custom MCP host and connects to
ToolHive-provided proxy URLs directly.

Install and verify ToolHive:

```powershell
winget install stacklok.thv
thv version
```

Start ToolHive's local API server for full General Chat controls:

```powershell
thv serve
```

You can also start servers in ToolHive UI. The desktop UI bundles `thv` at
`%LOCALAPPDATA%\ToolHive\bin\thv.exe` on Windows and `~/.toolhive/bin/thv` on
macOS/Linux. General Chat checks `thv` on `PATH` first, then those bundled CLI
paths. If it is not detected after install, open a new terminal and restart the
backend.

In another terminal, or from ToolHive UI, start the ToolHive docs MCP server:

```powershell
thv run toolhive-doc-mcp
thv list
thv list --format mcpservers
```

Open the **MCP Servers** panel. The **ToolHive MCP** section should show:

- ToolHive status and version.
- Running workloads from `thv list --format mcpservers`.
- An import button for each running server.
- A copied URL registration field for URLs copied from ToolHive UI.

Some registry servers take longer to start while ToolHive pulls the image or
prepares the runtime. General Chat waits up to 180 seconds by default. Increase
that before starting the backend if needed:

```powershell
$env:TOOLHIVE_START_TIMEOUT="300"
```

Choose **Import into OpenBench** on `toolhive-doc-mcp`, then **Load tools** for
the registered server if needed. Ask:

```text
Use the ToolHive MCP tools to answer: how do I run a remote MCP server with ToolHive?
```

Expected behavior:

- General Chat exposes enabled ToolHive MCP tools to the model.
- The model can call the ToolHive docs server through the local `/mcp` proxy.
- The final answer uses the tool result and mentions relevant ToolHive commands.

You can also:

- Search the ToolHive registry and start a server from the panel.
- Enter a remote MCP URL for ToolHive to proxy. Remote URLs require explicit
  approval in the UI.
- Register an already-running ToolHive URL such as
  `http://127.0.0.1:19767/mcp`.

The registry start, remote proxy, restart, stop, and delete actions are under
**Advanced local controls**. The default path is to manage the server lifecycle
in ToolHive UI and use OpenBench only to import and call tools.

Removing an OpenBench registered server only removes the OpenBench reference.
Use the ToolHive workload **Delete** action only when you want ToolHive to stop
and remove the workload itself.

If General Chat runs in Docker or another container, localhost in the container
may not reach ToolHive on the host. Set one of:

```powershell
$env:TOOLHIVE_HOST="host.docker.internal"       # Docker Desktop Windows/macOS
$env:TOOLHIVE_HOST="host.containers.internal"   # Podman Desktop
$env:TOOLHIVE_HOST="172.17.0.1"                 # common Docker Engine bridge
```

ToolHive's local API has no built-in auth. Keep `thv serve` bound to a trusted
local interface unless you add external authentication and authorization.

## 11. Image Search MCP Server

General Chat can also use the Dockerized DINOv3 CIFAR-10 image-search MCP
server from `mcp/image-search-mcp`.

From the repository root, build the image:

```powershell
docker compose -f mcp\image-search-mcp\docker-compose.yml --profile cpu build
```

Confirm the standalone MCP server works:

```powershell
python mcp\image-search-mcp\scripts\test_mcp_server.py --mode docker
```

If General Chat reports `Failed to discover MCP server 'image_search':
Connection closed`, the container exited before MCP handshake. First inspect the
image, then run the smoke command above to surface Docker-side stderr:

```powershell
docker image inspect openbench/image-search-mcp:cpu
python mcp\image-search-mcp\scripts\test_mcp_server.py --mode docker
```

Start General Chat with the image-search MCP config:

```powershell
cd examples/general-chat
.\scripts\run_with_image_search_mcp.ps1
```

Check discovery:

```powershell
Invoke-RestMethod http://localhost:8005/mcp/tools
```

Expected `namespaced_tool_names` includes:

```text
image_search.list_index_stats
image_search.search_similar_images
```

Use this prompt in the UI:

```text
Use image_search.list_index_stats to verify the CIFAR-10 index is healthy, then use image_search.search_similar_images for CIFAR-10 test image index 0 and return the top 3 results with image ids, labels, splits, dataset indexes, and similarity scores. If the index is partial, mention that coverage is partial.
```

To search from your own image, upload a `.png`, `.jpg`, `.jpeg`, or `.webp`
file in the Sources panel, then ask:

```text
Use the uploaded image source with image_search.search_similar_images. If the index is empty or uninitialized, tell me to build it outside chat; otherwise return the top 3 similar images with visible thumbnails, image ids, labels, splits, dataset indexes, and similarity scores. If the index is partial, mention that coverage is partial.
```

If `list_index_stats` reports `healthy=true`, search can run. A partial index
returns `complete=false` and `partial=true`; rebuild the full index outside chat
only when you want full CIFAR-10 coverage.

If the image-search model fails with a gated Hugging Face error, run
`hf auth login` on the host and make sure
`%USERPROFILE%\.cache\huggingface\token` exists. The launcher mounts that cache
read-only into the Docker container.

## 12. SAM 3 Concept Counting MCP Server

General Chat can also use the Dockerized Ultralytics SAM 3 concept counting MCP
server from `mcp/sam-segmentation-mcp`. It counts objects matching a text
concept such as `dog`, `person`, `red apple`, or `yellow school bus`.

Ultralytics does not auto-download `sam3.pt`, and the official weights are gated
on Hugging Face. After receiving access, either place `sam3.pt` at
`mcp/sam-segmentation-mcp/weights/sam3.pt` or set `HF_TOKEN` so Docker
Compose can download the weights during build. From the repository root, build
the image:

```powershell
$env:HF_TOKEN="hf_..."   # optional if weights/sam3.pt already exists
docker compose -f mcp\sam-segmentation-mcp\docker-compose.yml --profile cpu build
```

If you already ran `hf auth login`, you can use the helper script instead:

```powershell
mcp\sam-segmentation-mcp\scripts\build_with_sam3.ps1
```

The compose build defaults `SAM3_PREINSTALL=required`, so it fails early if the
weights cannot be copied or downloaded. General Chat uses the baked-in model at
`/models/sam3.pt`.

Confirm discovery:

```powershell
python mcp\sam-segmentation-mcp\scripts\test_mcp_server.py --mode docker --discovery-only
```

Start General Chat with the SAM 3 counting MCP config:

```powershell
cd examples/general-chat
.\scripts\run_with_sam_segmentation_mcp.ps1
```

Check discovery:

```powershell
Invoke-RestMethod http://localhost:8005/mcp/tools
```

Expected `namespaced_tool_names` includes:

```text
sam_segmentation.count_objects_with_sam3
```

Uploaded image paths under `/general-chat/uploads/...` are mounted into the
image MCP containers. Do not use filesystem MCP tools on those paths unless you
also mount uploads into the filesystem sandbox.

After a successful `sam_segmentation.count_objects_with_sam3` call, answer from
the returned `count`. `service_info` is a diagnostic tool for failures, not a
follow-up to a successful count.

Upload a `.png`, `.jpg`, `.jpeg`, or `.webp` image in the Sources panel, then
ask:

```text
How many dogs are in this image? Use the SAM 3 counting tool.
```

## Troubleshooting

- `/mcp/tools` says disabled: set `GENERAL_CHAT_MCP_ENABLED=1` and restart.
- For the all-MCP launcher, `/mcp/tools` should report registry mode; check
  `/mcp/catalogs` for per-server diagnostics when a Docker, filesystem,
  ToolHive, generic API, image-search, or SAM server is unavailable.
- `/mcp/tools` has zero tools: load tools in the MCP Servers panel and make
  sure the target server and tools are enabled.
- Dedicated Docker scripts fail while discovering stale ToolHive or manual MCP
  servers: set `GENERAL_CHAT_MCP_REGISTRY_ENABLED=0`, or use the provided
  scripts which set it for you.
- `openbench mcp list-tools` fails: install `openbench[mcp]` and run from the
  repository root.
- Chat does not call tools: make the prompt explicit: "Use the MCP tools..."
- Optional source context is handled by the chat flow. MCP tools are used only
  when they are enabled and the prompt or model behavior calls for them.
