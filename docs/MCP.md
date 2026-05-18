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

Example client config:

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

For ToolHive, publish OpenBench either as a container-based stdio server or a
remote Streamable HTTP endpoint. Keep credentials in ToolHive secrets and keep
filesystem permissions out of registry metadata.

The example `examples/mcp/toolhive-server.json` shows both package and remote
metadata shapes.

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
- ToolHive issues: confirm the endpoint uses Streamable HTTP, the auth token is
  present, and ToolHive proxy logs show the request.
