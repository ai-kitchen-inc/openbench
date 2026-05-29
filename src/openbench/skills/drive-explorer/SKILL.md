# drive-explorer

Search, read, and inspect files in the user's Google Drive via an MCP
server. Use this skill when the user wants the agent to find a
specific document, fetch its contents to summarize or reason over, or
list recently modified files for context.

This skill is **MCP-backed**: the actual Drive operations run inside
an MCP server process (Anthropic's `@modelcontextprotocol/server-gdrive`
or any compatible implementation). The skill itself is a thin wrapper
that exposes the MCP tools to the agent's reasoning loop and provides
the *playbook* for when to use them.

This is distinct from the storage-layer Drive integration
(`GoogleDriveStorageBackend`) — that backend persists OpenBench session
state to Drive without the agent thinking about it. This skill is for
the agent to *actively reason about* the user's Drive when they ask
for it.

## Triggers

- User asks "find …", "search my Drive for …", "look for the doc about …"
- User asks "what was in the Q1 report?", "summarize my latest
  proposal", "show me the spec for X"
- User references a document they own without giving a path
- Agent needs external context the user has stored in Drive (LCA
  workbooks, regulation PDFs, prior reports) and the request implies
  the user expects the agent to find it

## When NOT to use

- The user uploaded a file in the current turn — use the file directly
  via the standard upload path, not Drive search.
- The user attached a file via the storage layer's persistent
  `FileStore` — that file is already available via its attachment path.
- The agent needs to persist its own state — that is the storage
  layer's job, not this skill's.

## Workflow

1. Start broad: `drive_search` with a short keyword query (1-3 words).
   Return ≤10 results.
2. Inspect candidates: read `name`, `mimeType`, `modifiedTime` from
   the search results. Pick the one that best matches user intent.
3. Fetch content: `drive_read_file(file_id)` to get the file body.
   Large files may be truncated server-side — the result includes a
   `truncated` flag if so.
4. For "what changed recently?" questions, prefer
   `drive_list_recent` over a search.
5. For metadata-only questions (when was X modified, who owns Y),
   prefer `drive_get_metadata` to avoid downloading content.

## Failure modes the agent should narrate

- **Not connected**: the MCP client is not bound. The user needs to
  connect their Drive (UI flow) — say so and stop.
- **No matches**: the search returned zero results. Either the file
  doesn't exist, the keyword was too specific, or it's in a different
  workspace. Suggest a broader query or ask the user for a hint.
- **Permission denied**: the file exists but the user's OAuth scope
  does not grant access. Say so; do not retry.
- **Server error**: the MCP server returned an error. Surface a brief
  apology and the error message; do not silently retry more than once.

## Tools

- drive_search: find files by keyword
- drive_read_file: fetch a file's content by id
- drive_list_recent: list recently modified files
- drive_get_metadata: read a file's metadata without downloading it

## References

- mcp-server-setup.md: how the MCPClient is bound (server choice,
  auth, transport)

## Version

0.1.0

## Dependencies

- An :class:`openbench.integrations.mcp.MCPClient` bound at agent
  construction (typically wrapping `@modelcontextprotocol/server-gdrive`
  or a compatible server). The skill itself imports no Drive SDK and
  no MCP transport library.
