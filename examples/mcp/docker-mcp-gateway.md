# Docker MCP Gateway With OpenBench

OpenBench connects to Docker MCP Gateway through standard MCP transports.

```bash
docker mcp profile create --name openbench
docker mcp profile server add openbench --server catalog://mcp/docker-mcp-catalog/github-official
docker mcp gateway run --profile openbench
```

OpenBench client config:

```yaml
mcp:
  servers:
    docker:
      transport: stdio
      command: docker
      args: ["mcp", "gateway", "run", "--profile", "${OPENBENCH_MCP_DOCKER_PROFILE:-openbench}"]
      namespace: docker
      allowed: true
```

OpenBench does not mutate Docker profiles or secrets automatically.
