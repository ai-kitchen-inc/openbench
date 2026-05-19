# OpenBench + Open WebUI

OpenBench now exposes chat engines through an OpenAI-compatible `/v1` API, so
Open WebUI can be used as the default chat interface without the old
`@openbench/chat-ui` React SDK. 

## Backend Contract

Any FastAPI backend can mount the OpenBench router:

```python
from fastapi import FastAPI
from openbench.chat import ChatEngine, create_openai_compatible_router
from openbench.intelligence.base import BaseAgent

app = FastAPI()
engine = ChatEngine(agent=BaseAgent(goal="Help the user", model="gemini-2.5-flash"))

app.include_router(
    create_openai_compatible_router(engine=engine, model_id="openbench-chat"),
    prefix="/v1",
)
```

Open WebUI connects to:

```text
http://host.docker.internal:8005/v1
```

## Run Open WebUI

Start your OpenBench backend first, for example:

```powershell
uvicorn server:app --port 8005 --reload
```

Then run the UI:

```powershell
cd studio\open-webui
Copy-Item .env.example .env
docker compose --env-file .env up
```

Open [http://localhost:3000](http://localhost:3000).

## Open WebUI Settings

If the provider is not picked up automatically, add it manually:

| Setting | Value |
| --- | --- |
| Connection type | OpenAI-compatible / Standard |
| URL | `http://host.docker.internal:8005/v1` |
| API key | `not-needed` |
| Model ID | `openbench-chat` |

## Notes

- Open WebUI sends chat history through Chat Completions; OpenBench rebuilds the
  request-scoped agent memory for each turn.
- `ChatEngine`, tools, personas, attachments, render queues, and framework
  adapters remain on the OpenBench side.
- AG-UI/A2UI backend modules remain available for compatibility, but the
  bundled React SDK is no longer the default UI path.
