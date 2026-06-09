# ToolHive With OpenBench

OpenBench can run behind ToolHive as a container stdio server or as a remote
Streamable HTTP server.

Recommended production shape:

- package OpenBench as a container image
- run as a non-root user
- use ToolHive secrets for tokens
- expose only required outbound network hosts
- use policy in OpenBench and ToolHive for defense in depth

Remote OpenBench client config:

```yaml
mcp:
  servers:
    toolhive:
      transport: streamable-http
      url: "${OPENBENCH_TOOLHIVE_MCP_URL}"
      headers:
        Authorization: "Bearer ${OPENBENCH_TOOLHIVE_TOKEN}"
      namespace: toolhive
      allowed: true
```
