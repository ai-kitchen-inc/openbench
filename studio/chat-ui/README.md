# Chat UI Excluded

The previous `@openbench/chat-ui` React SDK has been excluded from the active
OpenBench UI path. OpenBench now integrates with Open WebUI through the
OpenAI-compatible chat transport in `openbench.chat.transport`.

Use the replacement workspace in `studio/open-webui`:

```powershell
cd studio\open-webui
Copy-Item .env.example .env
docker compose --env-file .env up
```

Backends should mount:

```python
from openbench.chat import create_openai_compatible_router

app.include_router(
    create_openai_compatible_router(engine=engine, model_id="openbench-chat"),
    prefix="/v1",
)
```
