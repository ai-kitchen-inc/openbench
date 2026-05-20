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

## 9. Image Search MCP Server

General Chat can also use the Dockerized DINOv3 CIFAR-10 image-search MCP
server from `examples/image-search-mcp`.

From the repository root, build the image:

```powershell
docker compose -f examples\image-search-mcp\docker-compose.yml --profile cpu build
```

Confirm the standalone MCP server works:

```powershell
python examples\image-search-mcp\scripts\test_mcp_server.py --mode docker
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
image_search.index_images
image_search.search_similar_images
image_search.rebuild_index
```

Use this prompt in the UI:

```text
Use the image_search MCP tools to index 16 CIFAR-10 training images with batch size 4, then search similar images for CIFAR-10 test image index 0 and return the top 3 results with image ids, labels, and similarity scores.
```

To search from your own image, upload a `.png`, `.jpg`, `.jpeg`, or `.webp`
file in the Sources panel, then ask:

```text
Use the uploaded image source with image_search.search_similar_images. Index 16 CIFAR-10 training images with batch size 4 if needed, then return the top 3 similar images with visible thumbnails, image ids, labels, and similarity scores.
```

If the image-search model fails with a gated Hugging Face error, run
`hf auth login` on the host and make sure
`%USERPROFILE%\.cache\huggingface\token` exists. The launcher mounts that cache
read-only into the Docker container.

## Troubleshooting

- `/mcp/tools` says disabled: set `GENERAL_CHAT_MCP_ENABLED=1` and restart.
- `/mcp/tools` has zero tools: load tools in the MCP Servers panel and make
  sure the target server and tools are enabled.
- `openbench mcp list-tools` fails: install `openbench[mcp]` and run from the
  repository root.
- Chat does not call tools: make the prompt explicit: "Use the MCP tools..."
- Document upload Q&A does not call tools: that is intentional. General Chat
  reads uploaded document text directly from the chat context.
