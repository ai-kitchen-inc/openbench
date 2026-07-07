# custom-function-mcp

Runs **user-defined Python functions** as agent-callable MCP tools for
general-chat. Users author functions in the app's Functions panel; the
general-chat API validates and persists them; this server lists and executes
them.

## Trust model

The code is untrusted — the **container is the sandbox**:

- spawned per call: `docker run --rm -i --network none --memory 512m --cpus 1
  --pids-limit 128` (see `examples/general-chat/mcp/custom-function-docker.yaml`)
- non-root user, functions dir mounted **read-only** at `/data/functions`
- each run is a fresh subprocess with a hard wall-clock timeout
  (`CUSTOM_FN_TIMEOUT_SECONDS`, default 20s)
- **definition** is auth-gated by the API (Firebase + allowlist); this server
  never writes functions
- fixed preinstalled libraries (pandas, numpy, matplotlib, openpyxl,
  python-dateutil) — no runtime pip, no network

## Tools

| Tool | Risk | Description |
|------|------|-------------|
| `list_functions` | read | metadata of stored functions |
| `describe_function(name)` | read | source + metadata |
| `run_function(name, kwargs_json)` | execute | run in a fresh subprocess, JSON result |

## Storage contract

`/data/functions/<name>.py` (exactly one top-level `def <name>(...)`) +
`<name>.json` (`{"name", "description", "created_at"}`). Names match
`^[a-z_][a-z0-9_]{0,63}$`.

## Local dev

```bash
pip install -r requirements.txt
CUSTOM_FN_DIR=./functions python -m app.runner add '{"a":2,"b":3}'
CUSTOM_FN_DIR=./functions python -m app.mcp_server --transport stdio
```

Build: `docker build -t openbench/custom-function-mcp:cpu .` (or Cloud Build →
Artifact Registry via `cloudbuild.custom-function-mcp.yaml`).
