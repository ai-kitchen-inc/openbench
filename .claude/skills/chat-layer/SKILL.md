---
name: chat-layer
description: Working with OpenBench chat layer - ChatEngine, A2UI v0.10 builder, content renderers, SSE + REST transport, and ChatLayer L2 orchestrator. Use when building chat interfaces, streaming A2UI JSONL, rendering rich content (charts, forms, files), or composing chat workflows.
---

# Chat Layer

OpenBench chat layer provides a complete backend for interactive chat UIs powered by **A2UI v0.10** (Google's declarative JSON streaming UI protocol).

## A2UI v0.10 Protocol

Four message types, every message has `"version": "v0.10"`:

| Message | Purpose |
|---------|---------|
| `createSurface` | Initialize surface with `surfaceId` + `catalogId` |
| `updateComponents` | Add/replace components (flat adjacency list) |
| `updateDataModel` | Update data at JSON Pointer path |
| `deleteSurface` | Remove a surface |

Components are flat objects: `{"id": "root", "component": "Column", "children": ["t1", "c1"]}`
Root component must have `id: "root"`. Properties are NOT nested.

Standard catalog: 18 components. Custom (OpenBench): 4 extensions.

## Architecture

```
src/openbench/chat/
├── engine.py           # ChatEngine (Chainable) -- main orchestrator
├── session.py          # ChatSession, ChatMessage, Attachment
├── a2ui/
│   ├── builder.py      # A2UIMessageBuilder -- A2UI v0.10 JSONL generator
│   ├── catalog.py      # Custom catalog (ObChart, ObFileCard, ObCodeBlock, ObMarkdown)
│   └── schema.py       # A2UI v0.10 message types and validation
├── renderers/
│   ├── base.py         # ContentRenderer ABC + Registry
│   ├── text.py         # TextRenderer (markdown, code)
│   ├── chart.py        # ChartRenderer (bar, line, pie, scatter)
│   ├── form.py         # FormRenderer (dynamic forms)
│   └── file.py         # FileRenderer (file preview/download)
├── transport/
│   ├── agui.py         # AGUIHandler -- AG-UI SSE event streaming
│   └── agui_actions.py # AGUIActionHandler -- REST for A2UI actions
└── layer.py            # ChatLayer (L2) + ChatFactory
```

## ChatEngine

Main orchestrator. Chainable -- composable with all OpenBench layers.

```python
from openbench.chat import ChatEngine, ChatSession
from openbench.intelligence.base import BaseAgent

agent = BaseAgent(goal="Answer questions about Q4 sales")
engine = ChatEngine(agent=agent)

# Single turn
result = engine.invoke({"content": "Show Q4 sales by region"})
# result = {"messages": [...], "session": ChatSession, "metadata": {...}}

# Streaming (A2UI v0.10 JSONL)
for line in engine.stream({"content": "Show Q4 sales"}):
    print(line)  # Each line is a valid A2UI v0.10 JSON message
```

## Composition with Layers

```python
from openbench.core import DataLayer, OutputLayer
from openbench.chat import ChatLayer

# Chat with RAG pipeline
workflow = DataLayer(sources=[pdf_source]) | ChatLayer(agent=rag_agent)

# Chat with transcript output
workflow = ChatLayer(agent=agent) | OutputLayer(generators=[transcript_gen])

# Full E2E
workflow = DataLayer(sources=[pdf]) | ChatLayer(agent=agent) | OutputLayer(generators=[...])
```

## ChatSession

```python
from openbench.chat import ChatSession, ChatMessage

session = ChatSession()
session.add_user_message("Hello", attachments=[...])
session.add_assistant_message("Hi!", surfaces=[...])

# Serialize / deserialize
data = session.to_dict()
restored = ChatSession.from_dict(data)

# Context window for LLM
recent = session.get_context_window(max_messages=50)
```

## Content Renderers

Auto-detect and render agent output as A2UI components:

```python
from openbench.chat.renderers.text import TextRenderer
from openbench.chat.renderers.chart import ChartRenderer

# Renderers auto-detect content type
text_renderer = TextRenderer()
text_renderer.detect("Hello world")  # True
components = text_renderer.render("# Title\nBody text", surface_id="s1")
# Returns [A2UIComponent(id="...", component="Text", properties={"text": "...", "variant": "h2"})]

chart_renderer = ChartRenderer()
chart_renderer.detect({"type": "bar", "data": [...]})  # True
components = chart_renderer.render({"type": "bar", "data": [...]}, surface_id="s1")
# Returns [A2UIComponent(id="...", component="ObChart", properties={"chartType": "bar", ...})]
```

## A2UI Builder

Build A2UI v0.10 JSONL messages:

```python
from openbench.chat.a2ui import A2UIMessageBuilder

builder = A2UIMessageBuilder()

# Build complete surface (createSurface + updateComponents + updateDataModel)
messages = builder.build_surface(
    surface_id="s1",
    components=[...],  # A2UIComponent list (one must have id="root")
    data_model={"/chart/data": [...]}
)
# Returns:
# [
#   {"version":"v0.10","createSurface":{"surfaceId":"s1","catalogId":"..."}},
#   {"version":"v0.10","updateComponents":{"surfaceId":"s1","components":[...]}},
#   {"version":"v0.10","updateDataModel":{"surfaceId":"s1","path":"/chart/data","value":[...]}}
# ]

# Serialize to JSONL
jsonl = builder.to_jsonl(messages)
```

## AG-UI Transport (Primary)

```python
from fastapi import FastAPI, Request
from openbench.chat import ChatEngine
from openbench.chat.transport import AGUIHandler, AGUIActionHandler

app = FastAPI()
engine = ChatEngine(agent=my_agent)
agui_handler = AGUIHandler(engine=engine)
action_handler = AGUIActionHandler(engine=engine)

@app.post("/awp")
async def chat_stream(request: Request):
    return await agui_handler.handle(request)

@app.post("/chat/action")
async def chat_action(request: Request):
    return await action_handler.handle(request)
```

## AG-UI Protocol

```
Client                                Server
  |                                   |
  |-- POST /awp                    -->|  AG-UI RunAgentInput
  |    {threadId, runId,              |
  |     messages: [...],              |
  |     forwardedProps: {sessionId}}  |
  |                                   |
  |<-- data: {"type":"RUN_STARTED",   |  AG-UI: run begins
  |     "threadId":"...",             |
  |     "runId":"..."}                |
  |                                   |
  |<-- data: {"type":"STEP_STARTED",  |  AG-UI: processing input
  |     "stepName":"Processing input"}|
  |<-- data: {"type":"STEP_FINISHED"} |
  |                                   |
  |<-- data: {"type":"STEP_STARTED",  |  AG-UI: thinking (streaming)
  |     "stepName":"Thinking"}        |
  |                                   |
  |<-- data: {"type":"TEXT_MESSAGE_START",  |  Text streaming begins
  |     "messageId":"msg-xxx",        |
  |     "role":"assistant"}           |
  |                                   |
  |<-- data: {"type":"TEXT_MESSAGE_CONTENT",|  Token deltas (progressive)
  |     "messageId":"msg-xxx",        |
  |     "delta":"The revenue..."}     |
  |   ... (more deltas)               |
  |                                   |
  |<-- data: {"type":"TEXT_MESSAGE_END",    |  Text streaming complete
  |     "messageId":"msg-xxx"}        |
  |                                   |
  |<-- data: {"type":"STEP_FINISHED"} |
  |                                   |
  |<-- data: {"type":"STEP_STARTED",  |  (only if rich content)
  |     "stepName":"Rendering"}       |
  |<-- data: {"type":"CUSTOM",        |  AG-UI: A2UI messages
  |     "name":"a2ui",                |
  |     "value":{"version":"v0.10",   |
  |       "createSurface":{...}}}     |
  |<-- data: {"type":"STEP_FINISHED"} |
  |                                   |
  |<-- data: {"type":"RUN_FINISHED",  |  AG-UI: run complete
  |     "result":{...}}               |
  |                                   |
  |-- POST /chat/action            -->|  User action (A2UI event)
  |    {"name":"submit_form",         |
  |     "surfaceId":"s1",             |
  |     "sourceComponentId":"btn",    |
  |     "context":{...}}             |
  |<-- [response messages]         ---|  JSON array
```

## Progressive Token Streaming

AGUIHandler streams text token-by-token using an `asyncio.Queue` bridge pattern:

```
Sync Thread (BaseAgent)           Async Event Loop (AGUIHandler)
┌─────────────────────┐          ┌──────────────────────────┐
│ llm.generate_stream()│          │ _event_stream():         │
│   ├─ chunk "The"    │──queue──>│   ├─ TextMessageContent  │──SSE──> Browser
│   ├─ chunk " answer"│──queue──>│   ├─ TextMessageContent  │──SSE──> Browser
│   ├─ chunk " is..." │──queue──>│   ├─ TextMessageContent  │──SSE──> Browser
│   └─ DONE sentinel  │──queue──>│   └─ break loop          │
└─────────────────────┘          └──────────────────────────┘
```

- `ChatEngine._execute_agent(content, config, attachments, on_chunk)` accepts the callback
- Agent calls `on_chunk(delta)` for each token
- `on_chunk` puts deltas into `asyncio.Queue` via `loop.call_soon_threadsafe()`
- SSE generator reads from queue and emits `TextMessageContentEvent`
- Text-only responses: 2 steps (Processing input + Thinking)
- Rich content responses: 3 steps (+ Rendering response with A2UI surfaces)

## Custom A2UI Catalog

4 custom components beyond the 18 standard A2UI v0.10 components:

| Component | Properties |
|-----------|------------|
| `ObChart` | `chartType`, `data`, `options`, `width`, `height` |
| `ObFileCard` | `fileName`, `fileUrl`, `fileSize`, `mimeType`, `previewUrl` |
| `ObCodeBlock` | `code`, `language`, `showLineNumbers`, `maxHeight` |
| `ObMarkdown` | `content`, `allowHtml` |

Note: `AudioPlayer` and `Video` are standard A2UI components -- no custom wrappers needed.

## Anti-Patterns

**DO NOT:**
- Import `fastapi` at module level -- use lazy imports (it's an optional dep)
- Create ChatEngine without an agent -- it requires `Agent | FrameworkAdapter`
- Skip `detect()` before `render()` on ContentRenderers -- always check first
- Send raw strings over SSE -- always use A2UI v0.10 JSONL format
- Use `surfaceUpdate` or `beginRendering` -- those are NOT real A2UI message types
- Use `"type"` on components -- the correct field is `"component"`
- Nest properties inside a `"properties"` dict -- A2UI properties are flat on the component object
- Forget `"version": "v0.10"` on every A2UI message
- Forget `catalogId` on `createSurface` messages
- Forget to include a component with `id: "root"` in every surface

## Cross-References

- **Intelligence Layer**: Agents used in ChatEngine -> see `intelligence-layer` skill
- **Data Layer**: RAG sources used with ChatLayer -> see `data-layer` skill
- **Output Layer**: Transcript generators used after ChatLayer -> see `output-layer` skill
- **Composing Workflows**: ChatLayer L2 composition -> see `composing-workflows` skill
- **Chat UI**: @openbench/chat-ui React SDK -> see `chat-ui` skill
- **Adapters**: External framework agents in ChatEngine -> see `adapters` skill
- **Testing**: Mock agent and renderer tests -> see `testing-openbench` skill

## Best Practices

1. Use renderers to auto-detect content -- don't hardcode A2UI components
2. Always stream for real-time UIs -- `engine.stream()` over `engine.invoke()`
3. Keep sessions serializable -- use `to_dict()` / `from_dict()` for persistence
4. Register custom renderers via `ContentRendererRegistry` for extensibility
5. Use `ChatLayer` for L2 composition, `ChatEngine` for direct usage
6. Validate JSONL output against A2UI v0.10 JSON schemas

For architecture details, see `docs/CHAT_UI_ARCHITECTURE.md`
