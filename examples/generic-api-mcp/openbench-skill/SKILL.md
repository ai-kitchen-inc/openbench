# generic-api-mcp

Generic API fetch tools backed by a user-provided endpoint URL and optional
Basic Auth defaults.

## Triggers

- The user wants to fetch data from an API endpoint URL.
- The user wants Basic Auth API access through OpenBench.
- The user wants MCP-compatible generic API retrieval.

## Tools

- `fetch_generic_api_data` - fetch data from the provided endpoint URL using
  a required endpoint URL, optional query parameters, and optional Basic Auth
  credentials from environment variables.

## Dependencies

- mcp[cli]
- requests

## Version

0.1.0
