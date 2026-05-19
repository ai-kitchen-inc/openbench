# General Chat OpenUI

Document-aware OpenBench chat backend wired to the
[Open WebUI](https://github.com/open-webui/open-webui) interface.

This folder is a migrated copy of `examples/general-chat`. The original demo is
unchanged. The copied React `frontend/` has been removed, and the backend now
mounts OpenBench's framework-level OpenAI-compatible `/v1` API for Open WebUI.

## What Changed

| Area | Before | Now |
| --- | --- | --- |
| UI | Vite + `@openbench/chat-ui` | Open WebUI Docker app |
| Chat transport | AG-UI `/awp` | OpenAI-compatible `/v1/chat/completions` |
| Model discovery | Not needed by old UI | `/v1/models` exposes `general-chat` |
| Backend | OpenBench + Gemini agent | Same backend, same persona, same source APIs |

The original AG-UI and source endpoints remain available for compatibility:
`/awp`, `/chat/upload`, `/chat/sources/*`, `/sessions`, `/persona`, and `/skills`.
The OpenAI-compatible adapter now lives in `openbench.chat.transport`, so this
example is no longer carrying its own copy of that bridge.

## Prerequisites

| Tool | Purpose |
| --- | --- |
| Python 3.10+ | Run the OpenBench backend |
| Docker Desktop or Docker Engine | Run Open WebUI |
| Google API key | Gemini model used by the agent |
| Tavily API key | Optional web source discovery |

## Configure Backend

From the repo root:

```powershell
cd examples\general-chat-OpenUI
Copy-Item .env.example .env
```

Edit `.env` and set at minimum:

```dotenv
GOOGLE_API_KEY=YOUR_KEY_HERE
TAVILY_API_KEY=YOUR_TAVILY_KEY_HERE
GENERAL_CHAT_OPENAI_MODEL_ID=general-chat
```

Install and start the backend:

```powershell
pip install -e .
uvicorn server:app --port 8005 --reload
```

Verify:

```powershell
Invoke-RestMethod http://localhost:8005/health
Invoke-RestMethod http://localhost:8005/v1/models
```

## Start Open WebUI

In a second terminal:

```powershell
cd examples\general-chat-OpenUI\open-webui
Copy-Item .env.example .env
docker compose --env-file .env up
```

Open [http://localhost:3000](http://localhost:3000).

The Compose file points Open WebUI to:

```text
http://host.docker.internal:8005/v1
```

That is the Docker Desktop hostname for a backend running on your host machine.
If your backend runs somewhere else, edit `GENERAL_CHAT_OPENAI_BASE_URL` in
`open-webui/.env`.

## Manual Open WebUI Connection

If the model does not appear automatically, configure it in Open WebUI:

| Setting | Value |
| --- | --- |
| Connection type | OpenAI-compatible / Standard |
| URL | `http://host.docker.internal:8005/v1` |
| API key | `not-needed` |
| Model ID | `general-chat` |

Open WebUI verifies providers through `/models`, then sends chat requests to
`/chat/completions` under the configured `/v1` base URL.

## Notes

- Open WebUI sends chat history in the OpenAI Chat Completions request. The
  adapter seeds the OpenBench agent memory from that request for each turn.
- Open WebUI file upload and RAG features are managed by Open WebUI itself.
  The copied backend still keeps the original OpenBench upload/source APIs for
  programmatic use.
- `WEBUI_AUTH=false` is intended for local development. Turn authentication on
  before exposing Open WebUI beyond your machine.
