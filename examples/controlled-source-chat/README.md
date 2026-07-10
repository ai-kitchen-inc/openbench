# Controlled Source Chat

Admin-curated knowledge-base chat with strict source grounding, citations, and local two-account login.

A thin wrapper around the [general-chat](../general-chat) backend: an **admin** curates the sources (documents, pasted text, URLs, MCP servers) in a full-screen control panel and can test them in a chat drawer; **guests** get chat only. The agent answers **strictly from the curated sources** (plus admin-enabled MCP tools), refuses off-source questions, and cites every claim with the source name so users can fact-check via the read-only Sources drawer.

## Run

```bash
export GOOGLE_API_KEY=...        # PowerShell: $env:GOOGLE_API_KEY="..."
openbench demo run controlled-source-chat
```

Backend starts on `:8006`, the Vite frontend on `:5173`. Manual alternative:

```bash
# Backend (from this directory)
uvicorn server:app --port 8006 --reload --reload-dir src

# Frontend
cd frontend && pnpm install && pnpm dev
```

## Accounts (local auth — no cloud)

| Account | Password   | Sees |
|---------|------------|------|
| `admin` | `admin123` | Control panel: manage sources + MCP servers, test chat drawer |
| `guest` | `guest123` | Chat only: no source management, no attachments, read-only Sources drawer |

Auth is a local username/password pair exchanged for a stateless HMAC bearer
token (survives `--reload` restarts). No Firebase, no GCP.

## How it works

- `server.py` sets an env baseline and builds the app via
  `controlled_source_chat.app.build_app()`, which wraps general-chat's
  `create_app()` unmodified and adds `/auth/*`, `/controlled/sources`, and a
  role-guard middleware.
- Sources live on one fixed thread (`controlled-sources`, owner `admin`).
  `GENERAL_CHAT_SHARED_SOURCES_OWNER/THREAD` make **every** chat turn ground
  on that thread — guests and the admin test chat see identical behavior.
- Strict grounding comes from this example's `soul/` persona
  (`GENERAL_CHAT_SOUL_DIR`), a short per-turn goal
  (`GENERAL_CHAT_AGENT_GOAL`), and an authoritative source framing label
  (`GENERAL_CHAT_SOURCE_CONTEXT_LABEL`). Answers cite `[source name]` inline
  and end with a `**Sources:**` line.
- Guests are blocked server-side (403) from `/chat/upload*`, `/chat/sources*`,
  `/mcp/*`, `/toolhive/*`, `/functions*`, `/dashboard/*`, `/persona`,
  `/skills`; they read the curated list via `GET /controlled/sources`.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `GOOGLE_API_KEY` | — (required) | Gemini API key |
| `CONTROLLED_CHAT_ADMIN_PASSWORD` | `admin123` | Admin password override |
| `CONTROLLED_CHAT_GUEST_PASSWORD` | `guest123` | Guest password override |
| `CONTROLLED_CHAT_AUTH_SECRET` | generated | Token signing secret (else persisted under `.openbench/`) |
| `GENERAL_CHAT_MODEL` | `gemini-3-flash-preview` | Chat model |

All other `GENERAL_CHAT_*` variables keep working; `server.py` only
`setdefault`s them.

## Caveats

- All guest logins share the `guest` account, so they share chat history —
  this is a two-account demo, not a multi-tenant deployment.
- MCP tool calls made from a guest chat can surface in-chat permission cards;
  the guest can approve them. Grounded answers may cite `[tool: <name>]`.
- Strict grounding is prompt-enforced (persona + goal + source labels), not a
  hard output filter — verify with the admin test chat after curating sources.

## Tests

```bash
pytest tests/test_controlled_source_chat_auth.py \
       tests/test_controlled_source_chat_guard.py \
       tests/test_controlled_source_chat_shared_sources.py \
       tests/test_general_chat_env_overrides.py
```
