# OpenBench MCP

OpenBench can expose existing function tools as MCP tools and consume MCP
servers as agent tools.

## Install

```bash
pip install -e ".[mcp]"
```

MCP remains optional. Core OpenBench imports do not require the MCP SDK.

## Serve OpenBench Tools

Create a config:

```yaml
mcp:
  server:
    name: openbench
    include_sdk_tools: true
    transport: stdio
    policy:
      allowed_servers: ["openbench"]
      require_approval_for_risks: ["write", "artifact_write", "external_network", "destructive"]
```

List tools:

```bash
openbench mcp list-tools --config openbench.yaml
```

Run locally over stdio:

```bash
openbench mcp serve --config openbench.yaml --transport stdio
```

Run over Streamable HTTP:

```bash
openbench mcp serve --config openbench.yaml --transport streamable-http --host 127.0.0.1 --port 8000
```

Use `0.0.0.0` only behind an authenticated gateway or trusted internal network.

## Consume MCP Servers

OpenBench accepts the common MCP client JSON shape for user-provided servers:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp/playwright"],
      "env": {},
      "cwd": "examples/general-chat"
    }
  }
}
```

Validation checks JSON shape, command/transport fields, string arrays for
`args`, string maps for `env` and `headers`, and duplicate normalized server
names. Validation does not start command-based servers.

OpenBench YAML config remains available for SDK and CLI use:

```yaml
mcp:
  servers:
    openbench:
      transport: stdio
      command: openbench
      args: ["mcp", "serve", "--config", "openbench.yaml"]
      namespace: openbench
      allowed: true
    docker:
      transport: stdio
      command: docker
      args: ["mcp", "gateway", "run", "--profile", "${OPENBENCH_MCP_DOCKER_PROFILE:-openbench}"]
      namespace: docker
      allowed: true
    toolhive:
      transport: streamable-http
      url: "${OPENBENCH_TOOLHIVE_MCP_URL}"
      headers:
        Authorization: "Bearer ${OPENBENCH_TOOLHIVE_TOKEN}"
      namespace: toolhive
      allowed: true
```

Tools discovered from multiple servers are namespaced as `{server}.{tool}` to
prevent collisions.

## Docker MCP Gateway

Create a Docker MCP profile, add servers to it, then configure OpenBench to use
the gateway as an MCP server:

```bash
docker mcp profile create --name openbench
docker mcp profile server add openbench --server catalog://mcp/docker-mcp-catalog/github-official
docker mcp gateway run --profile openbench
```

Use Docker's secret management for credentials. OpenBench does not edit Docker
profiles automatically.

## ToolHive

OpenBench can also consume MCP servers managed by
[ToolHive](https://docs.stacklok.com/toolhive/). The recommended desktop flow is
to manage server install, configuration, secrets, and logs in
[ToolHive UI](https://docs.stacklok.com/toolhive/guides-ui/), then import the
running MCP proxy URL into OpenBench. OpenBench stays the MCP host/client: it
discovers tools from the ToolHive proxy URL, namespaces them, and routes chat
tool calls back through ToolHive.

Install and verify ToolHive:

```powershell
winget install stacklok.thv
thv version
```

Start the local ToolHive API for UI management:

```powershell
thv serve
```

Or use ToolHive UI to start a server from the registry. The ToolHive UI bundles
the `thv` CLI in `%LOCALAPPDATA%\ToolHive\bin\thv.exe` on Windows and
`~/.toolhive/bin/thv` on macOS/Linux. OpenBench checks `thv` on `PATH` first,
then those bundled CLI paths. If a newly installed `thv` is not detected, open a
new terminal and restart the General Chat backend.

Start a docs MCP server and inspect the proxy URL from CLI:

```powershell
thv run toolhive-doc-mcp
thv list
thv list --format mcpservers
```

`thv list --format mcpservers` returns standard MCP client JSON:

```json
{
  "mcpServers": {
    "toolhive-doc-mcp": {
      "url": "http://127.0.0.1:19767/mcp"
    }
  }
}
```

OpenBench prefers the ToolHive API server at `TOOLHIVE_BASE_URL`, defaulting to
`http://127.0.0.1:8080`, and falls back to the `thv` CLI for discovering
running UI-managed servers when the API is unavailable. ToolHive API controls
are intended for local automation/UI use and should not be exposed remotely
without authentication and authorization.

Starting a registry server can take longer than status/list calls because
ToolHive may need to pull an image or prepare the runtime. OpenBench uses
`TOOLHIVE_START_TIMEOUT`, defaulting to 180 seconds, for start operations:

```bash
TOOLHIVE_START_TIMEOUT=300
```

If OpenBench runs in a container, set `TOOLHIVE_HOST` so localhost proxy URLs
are rewritten explicitly:

```bash
TOOLHIVE_HOST=host.docker.internal        # Docker Desktop macOS/Windows
TOOLHIVE_HOST=host.containers.internal    # Podman Desktop
TOOLHIVE_HOST=172.17.0.1                  # common Docker Engine bridge gateway
```

Keep credentials in ToolHive secrets. OpenBench stores only server names,
ToolHive workload names, local proxy URLs, enabled flags, selected tools, and
timestamps; it redacts likely secrets from displayed config.

## Adding A New MCP Tool

Prefer the existing OpenBench skill convention:

1. Add a skill directory with `SKILL.md`.
2. Add `tools.py` with a callable and matching `FOO_SCHEMA`.
3. Load that skill in `mcp.server.skills` or rely on `include_sdk_tools`.
4. Add a policy classification if the tool is write-capable, networked, or
   destructive.
5. Add unit tests for the callable and schema conversion.

## Troubleshooting

- Discovery fails: check transport, command, URL, headers, and whether the
  server completed MCP initialization.
- Tool denied: inspect policy allowlists, risk class, and approval settings.
- Auth fails: verify the header value is populated from the environment and not
  committed directly.
- Docker Gateway issues: confirm the selected profile contains enabled servers
  and that Docker MCP Toolkit is installed.
- ToolHive issues: confirm `thv version`, `thv serve`, `thv list --format
  mcpservers`, and that the endpoint uses a Streamable HTTP URL ending in
  `/mcp`. SSE URLs currently report a clear unsupported-transport message.
