# OpenBench Standalone MCP Servers

This directory contains standalone Model Context Protocol (MCP) servers that can
be run next to OpenBench and connected through the OpenBench MCP client layer.

The Python SDK package remains at `src/openbench/mcp`. Keep importing OpenBench
MCP helpers with `openbench.mcp`. This directory is for standalone server
projects, templates, and Docker profiles.

## Directory Layout

Use this layout for a new standalone MCP server:

```text
mcp/<server-name>-mcp/
├── app/
│   ├── __init__.py
│   ├── mcp_server.py
│   ├── service.py
│   └── tool_schemas.py          # Optional OpenBench/OpenAI-style schemas
├── openbench-skill/             # Optional OpenBench skill wrapper
│   ├── SKILL.md
│   └── tools.py
├── tests/
├── scripts/
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── docker-mcp-server.example.json
├── mcp-client.example.json
├── openbench-mcp.yaml
└── README.md
```

Start from `mcp/template/standalone-fastmcp` for the smallest working example.

## Tool Contract

- Use stable, descriptive tool names such as `search_similar_images`.
- Keep tool arguments typed and JSON-serializable.
- Put business logic in `app/service.py`; keep `app/mcp_server.py` focused on
  MCP registration, transport flags, and error shaping.
- Add useful MCP annotations: `readOnlyHint`, `destructiveHint`,
  `idempotentHint`, and `openWorldHint`.
- Return compact dictionaries with high-signal fields. Avoid raw dumps when a
  summary is enough.
- For stdio servers, never write logs or third-party output to stdout. Redirect
  tool execution stdout to stderr when needed.
- Do not commit secrets. Read credentials from environment variables or a
  runtime secret manager.

## Runtime Contract

- Support `stdio` by default.
- Support `streamable-http` when useful, bound to `127.0.0.1` by default and
  served at `/mcp`.
- Keep `sse` optional for legacy clients only.
- Use environment variables for paths, credentials, timeouts, and model/cache
  locations.
- Use Docker image names like `openbench/<server-name>-mcp:<profile>`, for
  example `openbench/image-search-mcp:cpu`.
- Keep Docker volumes explicit and scoped to the server's data, model, upload,
  or cache directories.

## OpenBench Integration

Expose an OpenBench skill through the built-in MCP server:

```bash
openbench mcp list-tools --config mcp/<server-name>-mcp/openbench-mcp.yaml
openbench mcp serve --config mcp/<server-name>-mcp/openbench-mcp.yaml --transport stdio
```

Register a standalone server with standard MCP client JSON:

```json
{
  "mcpServers": {
    "example": {
      "command": "python",
      "args": ["-m", "app.mcp_server", "--transport", "stdio"],
      "cwd": "mcp/example-mcp",
      "env": {}
    }
  }
}
```

General Chat keeps its runtime MCP config files in `examples/general-chat/mcp/`.
Those configs can point to Docker images or standalone servers in this
directory.

## Testing Contract

- Unit-test service logic without starting an MCP process.
- Test schema/tool registration and JSON-serializable tool outputs.
- Add a stdio discovery smoke test when the server is lightweight.
- Add Docker smoke tests for containerized servers, but skip cleanly when Docker
  or heavy model assets are unavailable.
- Keep external API calls mocked in unit tests.

## Included Servers

- `aggregate-data-mcp`: general CSV/XLSX metadata inspection and read-only SQLite aggregation.
- `dashboard-generator-mcp`: metadata-first CSV/XLSX dashboard planning and rendering.
- `generic-api-mcp`: authenticated GET access to user-provided API endpoints.
- `image-search-mcp`: local image similarity search with DINOv3/CIFAR assets.
- `sam-segmentation-mcp`: SAM 3 concept counting and segmentation helper.
