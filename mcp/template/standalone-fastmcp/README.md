# Standalone FastMCP Template

Copy this directory to `mcp/<your-name>-mcp` and replace `example_mcp`,
`example_echo`, and the environment variable names with your server-specific
names.

## Run Locally

```bash
pip install -r requirements.txt
python -m app.mcp_server --transport stdio
```

For local HTTP testing:

```bash
python -m app.mcp_server --transport streamable-http --host 127.0.0.1 --port 8000
```

## Docker

```bash
docker compose --profile cpu build
docker compose --profile cpu run --rm example-mcp-cpu
```

## OpenBench

```bash
openbench mcp list-tools --config mcp/template/standalone-fastmcp/openbench-mcp.yaml
openbench mcp serve --config mcp/template/standalone-fastmcp/openbench-mcp.yaml --transport stdio
```
