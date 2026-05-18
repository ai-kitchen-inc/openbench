# OpenBench MCP Architecture

OpenBench treats tools as in-process Python callables today. Skills are loaded
from `SKILL.md`, optional `references/*.md`, and optional `tools.py` modules;
`SkillRegistry.collect_tools()` returns `(name, callable, schema)` tuples that
`ToolExecutor` registers for agents. The MCP migration keeps that path intact
and adds a protocol layer around the same functions.

## Current Architecture

- `Skill.from_dir()` imports `tools.py` and discovers `FOO_SCHEMA` plus `foo()`
  pairs.
- `SkillRegistry` merges SDK, user, and project skills, then raises on tool name
  collisions.
- `ToolExecutor` stores callables or `Tool` objects, exposes OpenAI-style
  function schemas, runs calls with timeouts, and can execute independent calls
  concurrently.
- `BaseAgent` registers explicit tools, skill tools, and the optional
  `retrieve_knowledge` RAG tool. Existing LLM providers convert these schemas to
  provider-specific declarations.
- SDK tools include file readers, record operations, visualization render items,
  Excel/PDF artifact generation, web search, and scratchpad memory.

The main gaps are that tools cannot be discovered or called through MCP,
schemas are not normalized across MCP/OpenAI/Gemini, remote tools have no common
client, and dangerous tools do not have a reusable policy/audit layer.

## Target Architecture

The MCP layer lives in `openbench.mcp` and is additive:

- `OpenBenchMCPServer` wraps existing skill tools as MCP tools and can expose
  skill files as resources plus reusable workflow prompts.
- `MCPClient` connects to one or more MCP servers, discovers tools/resources/
  prompts, and calls tools by namespaced names such as `openbench.read_pdf`.
- `MCPToolAdapter` implements the existing `Tool` abstraction so remote MCP
  tools can be passed to `BaseAgent` without changing the reasoning loop.
- `MCPPolicyEngine` enforces allowlists, denylists, risk classes, approval
  requirements, timeouts, and response limits.
- Schema adapters translate between OpenBench/OpenAI-style function schemas and
  MCP `inputSchema` tool definitions.

Transport support is explicit:

- `stdio` is the default for local development and hermetic tests.
- `streamable-http` is the production default for remote servers, Docker MCP
  Gateway, and ToolHive.
- `sse` is legacy compatibility and remains opt-in.

## Security Model

Remote servers are denied by default unless policy explicitly allows them.
Policy decisions are based on server, tool, risk level, timeout, and approval
state. Built-in risk classes are `read`, `write`, `artifact_write`,
`external_network`, and `destructive`.

Default SDK classifications:

- Read: file metadata/read tools, PDF read/table tools, query-explorer tools,
  `read_memory`, and `list_memory_keys`.
- Write/artifact: profile writes, Excel/PDF export or mutation, `write_memory`,
  and `append_memory`.
- External network: web search tools.

Production HTTP deployments should bind locally unless explicitly configured,
validate origin headers, require auth for non-local endpoints, redact secrets in
logs, and confine writes to configured export/profile directories. Docker MCP
Gateway and ToolHive deployments should use their respective secret stores
instead of embedding credentials in config files.

## Observability

Every discovery and tool call should have a correlation ID. The MCP layer logs
structured fields for server, tool, transport, duration, retry count, policy
decision, and status. A lightweight metrics recorder tracks request volume,
latency, retry counts, failures, policy denials, and active sessions. Optional
OpenTelemetry spans wrap discovery, policy checks, transport requests, and tool
execution when `opentelemetry-api` is installed.

## Docker MCP Gateway

OpenBench treats Docker MCP Gateway as a normal MCP endpoint. A local profile can
be configured through Docker's `docker mcp gateway run --profile <profile>`
command over stdio, or through a Streamable HTTP URL when deployed that way.
OpenBench does not mutate Docker profiles automatically; docs and examples show
how to create/import profiles, add servers, use secrets, and connect the
OpenBench client.

## ToolHive Compatibility

OpenBench can be published to ToolHive as either:

- a container server using stdio transport, or
- a remote Streamable HTTP server.

ToolHive metadata should list tools when known, mark secrets as secret, include
network permissions only when required, and avoid host volume mounts in registry
entries. The OpenBench client supports ToolHive endpoints with Streamable HTTP,
auth headers, and policy checks before outbound calls.

## Migration Phases

1. Add architecture/user docs and examples.
2. Add schema, config, policy, error, and observability foundations.
3. Add OpenBench MCP server wrapping existing skill tools.
4. Add MCP client, transports, discovery, and `Tool` adapter.
5. Add CLI commands and optional dependency metadata.
6. Add tests for schema, policy, server wrapping, client behavior, and examples.
7. Expand live Docker/ToolHive validation outside the default unit suite.

## Rollback

The migration is optional and additive. Existing skills, `ToolExecutor`, agents,
chat, and examples continue to work without MCP installed. If MCP behavior needs
to be disabled, remove `openbench[mcp]` from the environment or avoid MCP config.
No existing agent path depends on MCP unless explicitly configured.

## Validation

Run:

```bash
python -m unittest discover tests -v
pytest tests/ --cov=openbench
ruff check src/ tests/
mypy src/openbench/
```

MCP-specific tests that need the optional SDK should skip cleanly unless
`openbench[mcp]` is installed.
