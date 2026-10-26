# Generic API MCP

Generic authenticated API access through a standalone FastMCP server. The
server exposes `fetch_generic_api_data`, which sends a GET request to an
endpoint URL supplied by the chat/tool call. Optional Basic Auth defaults can be
provided through environment variables.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `GENERIC_API_USERNAME` | none | Optional Basic Auth username |
| `GENERIC_API_PASSWORD` | none | Optional Basic Auth password |
| `GENERIC_API_TIMEOUT_SECONDS` | `30` | Request timeout in seconds |

## Run Locally

```bash
python -m app.mcp_server --transport stdio
```

## Docker

```bash
docker compose --profile cpu build
docker compose --profile cpu run --rm generic-api-mcp-cpu
```

## General Chat

`openbench demo run general-chat-all --all-mcp` seeds this server through
`examples/general-chat/mcp/generic-api-docker.yaml`.
