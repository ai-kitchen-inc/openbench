# Open WebUI Integration

OpenBench integrates with Open WebUI through the OpenAI-compatible chat
transport in `openbench.chat.transport`.

## FastAPI Backend

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

This exposes:

- `GET /v1/models`
- `POST /v1/chat/completions`

## Open WebUI

Use the Compose workspace in `studio/open-webui`:

```powershell
cd studio\open-webui
Copy-Item .env.example .env
docker compose --env-file .env up
```

Open WebUI should point to `http://host.docker.internal:8005/v1` when the
OpenBench backend is running on the host at port `8005`.
