# Chat UI SDK Architecture

## Overview

The Chat UI system spans two packages:

1. **Python Backend** (`src/openbench/chat/`) -- ChatEngine, A2UI builder, content renderers, AG-UI transport
2. **TypeScript Frontend** (`studio/chat-ui/`) -- `@openbench/chat-ui` React component library

Both communicate via **AG-UI protocol** (SSE event streaming) and REST (actions). A2UI v0.10 messages are wrapped inside AG-UI `CustomEvent(name="a2ui")` payloads.

**A2UI Spec Reference**: [github.com/google/A2UI](https://github.com/google/A2UI) -- specification/v0_10/

---

## A2UI v0.10 Protocol Summary

A2UI (Agent to UI) is a declarative JSON-based streaming UI protocol by Google. The server streams JSON objects; the client parses each as a distinct message and incrementally builds or updates the UI.

### Four Message Types

Every message is a JSON object with `"version": "v0.10"` and exactly one of:

| Message | Purpose |
|---------|---------|
| `createSurface` | Initialize a new surface with `surfaceId` + `catalogId` |
| `updateComponents` | Add/replace components in a surface (flat adjacency list) |
| `updateDataModel` | Update data at a JSON Pointer path within a surface |
| `deleteSurface` | Remove a surface and all its components/data |

### Component Model

Components are **flat objects** in an adjacency list. Properties are directly on the object (not nested):

```json
{
  "id": "greeting",
  "component": "Text",
  "text": "Hello, world!",
  "variant": "h2"
}
```

Key rules:
- `id` (string, required) -- unique within the surface
- `component` (string, required) -- type name from the catalog
- One component **must** have `id: "root"` to serve as the tree root
- Container components reference children by ID via `children` (array or template)

### Data Binding

Properties can be literal values or bound to the data model via JSON Pointer (RFC 6901):

```json
{"text": "Hello"}                          // Literal
{"text": {"path": "/user/name"}}           // Data binding (absolute)
{"text": {"path": "name"}}                 // Data binding (relative, in template scope)
{"text": {"call": "formatString", "args": {"value": "Hi, ${/user/name}!"}}}  // Function call
```

Types: `DynamicString`, `DynamicNumber`, `DynamicBoolean`, `DynamicStringList`

### Actions

Interactive components use `action` with either server events or local function calls:

```json
{"action": {"event": {"name": "submit_form", "context": {"email": {"path": "/form/email"}}}}}
{"action": {"functionCall": {"call": "openUrl", "args": {"url": "https://example.com"}}}}
```

### Functions (14 in standard catalog)

Validation: `required`, `regex`, `length`, `numeric`, `email`
Formatting: `formatString`, `formatNumber`, `formatCurrency`, `formatDate`, `pluralize`
Navigation: `openUrl`
Logic: `and`, `or`, `not`

### Checks (Validation)

Input components can define validation rules:

```json
{
  "component": "TextField",
  "label": "Email",
  "value": {"path": "/form/email"},
  "checks": [
    {"condition": {"call": "required", "args": {"value": {"path": "/form/email"}}}, "message": "Required"},
    {"condition": {"call": "email", "args": {"value": {"path": "/form/email"}}}, "message": "Invalid email"}
  ]
}
```

### Theme

Set in `createSurface`: `primaryColor` (hex), `iconUrl` (URI), `agentDisplayName` (string).

### Transport

A2UI is transport-agnostic. Supports: A2A, AG-UI, WebSocket, SSE, REST, MCP.

---

## System Diagram

```
+---------------------------------------------------------------------+
|                     @openbench/chat-ui (SDK)                         |
|                                                                      |
|  +-------------------------------------------------------------+    |
|  |                    Components Layer                           |    |
|  |  ChatProvider -> SessionSidebar + ChatPanel                   |    |
|  |  ChatPanel -> MessageList + ChatInput                         |    |
|  |  MessageBubble -> text content + SurfaceRenderer              |    |
|  +---------------------------+-----------------------------------+    |
|                               |                                       |
|  +---------------------------v-----------------------------------+    |
|  |                    A2UI Layer                                  |    |
|  |  SurfaceRenderer: adjacency list -> React component tree      |    |
|  |  +---------------------------+------------------------------+  |    |
|  |  | Standard Catalog (18)     | Custom Catalog (OpenBench 6) |  |    |
|  |  | Text, Image, Icon, Video, | ObChart (Recharts)           |  |    |
|  |  | AudioPlayer, Row, Column, | ObFileCard                   |  |    |
|  |  | List, Card, Tabs, Modal,  | ObCodeBlock (Shiki)          |  |    |
|  |  | Divider, Button, TextField| ObMarkdown (react-markdown)  |  |    |
|  |  | CheckBox, ChoicePicker,   | ObTable                      |  |    |
|  |  | Slider, DateTimeInput     | ObCallout                    |  |    |
|  |  +---------------------------+------------------------------+  |    |
|  +---------------------------+-----------------------------------+    |
|                               |                                       |
|  +---------------------------v-----------------------------------+    |
|  |                    Core Layer                                  |    |
|  |  AGUITransport (AG-UI SSE + REST) <-> Any backend              |    |
|  |  A2UIMessageProcessor (JSONL parser + surface state)          |    |
|  |  ChatStore (Zustand -- sessions, messages, streaming)         |    |
|  +---------------------------------------------------------------+    |
|                                                                      |
|  Public API: Components + Hooks + Core + Types                       |
+---------------------------------------------------------------------+
         |                              ^
         | action (JSON)                | A2UI JSONL (stream)
         v                              |
+---------------------------------------------------------------------+
|                  Python Backend (src/openbench/chat/)                 |
|                                                                      |
|  +---------------------------------------------------------------+  |
|  |  ChatEngine (Chainable)                                        |  |
|  |  input -> agent.execute() -> ContentRenderer -> A2UIBuilder    |  |
|  |                                                                |  |
|  |  Composable:                                                   |  |
|  |    DataLayer | ChatEngine(agent=my_agent)                      |  |
|  |    ChatEngine(...) | OutputLayer(generators=[transcript])      |  |
|  +----------------------------+----------------------------------+  |
|                                |                                      |
|  +----------------------------v----------------------------------+  |
|  |  Content Renderers (11) -> A2UI Builder -> JSONL               |  |
|  |  Text, Chart, Code, Form, File, Media, List, Tabs,           |  |
|  |  Modal, Table, Callout                                        |  |
|  +----------------------------+----------------------------------+  |
|                                |                                      |
|  +----------------------------v----------------------------------+  |
|  |  AG-UI Transport (FastAPI)                                     |  |
|  |  Streams AG-UI events via SSE (A2UI in CustomEvent)             |  |
|  +---------------------------------------------------------------+  |
+---------------------------------------------------------------------+
```

---

## Part 1: Python Backend

### Module Structure

```
src/openbench/chat/
├── __init__.py                 # Public API exports
├── engine.py                   # ChatEngine (Chainable) -- main orchestrator
├── session.py                  # ChatSession, ChatMessage, Attachment
├── a2ui/
│   ├── __init__.py             # A2UI builder exports
│   ├── builder.py              # A2UIMessageBuilder -- generates A2UI v0.10 JSONL
│   ├── catalog.py              # Custom catalog definition (ObChart, ObFileCard, etc.)
│   └── schema.py               # A2UI message types and validation
├── renderers/
│   ├── __init__.py             # ContentRendererRegistry + exports
│   ├── base.py                 # ContentRenderer abstract base
│   ├── text.py                 # TextRenderer (markdown, code, rich text)
│   ├── chart.py                # ChartRenderer (bar, line, pie, scatter)
│   ├── code.py                 # CodeRenderer (syntax-highlighted code)
│   ├── form.py                 # FormRenderer (dynamic form generation)
│   ├── file.py                 # FileRenderer (file preview/download)
│   ├── media.py                # MediaRenderer (images, video, audio)
│   ├── list.py                 # ListRenderer (ordered/unordered lists)
│   ├── tabs.py                 # TabsRenderer (tabbed content)
│   ├── modal.py                # ModalRenderer (modal overlays)
│   ├── table.py                # TableRenderer (structured tables)
│   └── callout.py              # CalloutRenderer (styled callout boxes)
├── transport/                    # AG-UI protocol transport
│   ├── __init__.py
│   ├── agui.py                 # AGUIHandler -- AG-UI SSE event streaming
│   └── agui_actions.py         # AGUIActionHandler -- REST for A2UI actions
└── layer.py                    # ChatLayer (L2 orchestrator) + ChatFactory
```

### How It Fits Into OpenBench

ChatEngine and ChatLayer follow the same patterns as existing L1/L2 components:

```
Chainable[Input, Output]          <- Base class (core/chainable.py)
├── DataLayer                      <- Existing L2
├── IntelligenceLayer              <- Existing L2
├── OutputLayer                    <- Existing L2
└── ChatLayer (NEW)                <- New L2 (composable with all above)
     └── ChatEngine (NEW)          <- New L1 (Chainable)
```

Composition examples:
```python
# Chat with RAG pipeline
workflow = DataLayer(sources=[pdf]) | ChatLayer(agent=rag_agent)

# Chat with transcript output
workflow = ChatLayer(agent=agent) | OutputLayer(generators=[transcript_gen])

# Full E2E
workflow = DataLayer(...) | ChatLayer(...) | OutputLayer(...)
```

### Core Classes

#### ChatSession (session.py)

Manages conversation history. Integrates with existing `AgentMemory` from `intelligence/base.py`.

```python
@dataclass
class Attachment:
    id: str
    type: str          # "file", "audio", "video", "image"
    name: str
    url: str
    mime_type: str
    size_bytes: int | None = None

class MessageRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"

@dataclass
class ChatMessage:
    id: str
    role: MessageRole
    content: str
    surfaces: list[dict] | None = None        # A2UI surface data
    attachments: list[Attachment] | None = None
    timestamp: datetime
    metadata: dict[str, Any]

class ChatSession:
    session_id: str
    messages: list[ChatMessage]
    created_at: datetime
    updated_at: datetime

    def add_user_message(content, attachments=None) -> ChatMessage
    def add_assistant_message(content, surfaces=None) -> ChatMessage
    def get_context_window(max_messages=50) -> list[ChatMessage]
    def to_dict() -> dict
    @classmethod from_dict(data) -> ChatSession
```

#### A2UI Schema (a2ui/schema.py)

Defines the A2UI v0.10 message types matching the real protocol:

```python
@dataclass
class A2UIComponent:
    """A component in the adjacency list (flat object, not nested properties)."""
    id: str
    component: str                             # "Text", "Column", "ObChart", etc.
    properties: dict[str, Any]                 # Flat properties (text, children, variant, etc.)

    def to_dict(self) -> dict:
        """Serialize to A2UI format: {id, component, ...properties}"""
        result = {"id": self.id, "component": self.component}
        result.update(self.properties)
        return result

@dataclass
class CreateSurfaceMessage:
    """createSurface -- initialize a new surface."""
    surface_id: str
    catalog_id: str
    theme: dict[str, Any] | None = None
    send_data_model: bool = False

    def to_dict(self) -> dict:
        msg = {
            "version": "v0.10",
            "createSurface": {
                "surfaceId": self.surface_id,
                "catalogId": self.catalog_id,
            }
        }
        if self.theme:
            msg["createSurface"]["theme"] = self.theme
        if self.send_data_model:
            msg["createSurface"]["sendDataModel"] = True
        return msg

@dataclass
class UpdateComponentsMessage:
    """updateComponents -- add/replace components in a surface."""
    surface_id: str
    components: list[A2UIComponent]

    def to_dict(self) -> dict:
        return {
            "version": "v0.10",
            "updateComponents": {
                "surfaceId": self.surface_id,
                "components": [c.to_dict() for c in self.components],
            }
        }

@dataclass
class UpdateDataModelMessage:
    """updateDataModel -- update data at a JSON Pointer path."""
    surface_id: str
    path: str | None = None                    # RFC 6901 JSON Pointer, None = "/"
    value: Any = None                          # None = remove key at path

    def to_dict(self) -> dict:
        msg = {
            "version": "v0.10",
            "updateDataModel": {"surfaceId": self.surface_id}
        }
        if self.path:
            msg["updateDataModel"]["path"] = self.path
        if self.value is not None:
            msg["updateDataModel"]["value"] = self.value
        return msg

@dataclass
class DeleteSurfaceMessage:
    """deleteSurface -- remove a surface."""
    surface_id: str

    def to_dict(self) -> dict:
        return {
            "version": "v0.10",
            "deleteSurface": {"surfaceId": self.surface_id}
        }

# Wire format types for streaming envelope
class StreamMessageType(Enum):
    STREAM_START = "stream_start"
    STREAM_END = "stream_end"
    ERROR = "error"

@dataclass
class StreamMessage:
    type: StreamMessageType
    message_id: str
    metadata: dict[str, Any] | None = None
```

#### A2UI Catalog (a2ui/catalog.py)

Custom catalog extending the 18 standard A2UI components with OpenBench-specific types:

```python
# Standard A2UI v0.10 catalog (18 components):
# Text, Image, Icon, Video, AudioPlayer, Row, Column, List,
# Card, Tabs, Modal, Divider, Button, TextField, CheckBox,
# ChoicePicker, Slider, DateTimeInput

# OpenBench custom catalog (6 additional components):
OPENBENCH_CATALOG_ID = "https://openbench.dev/catalog/v1"

OPENBENCH_CATALOG = {
    "catalogId": OPENBENCH_CATALOG_ID,
    "components": {
        "ObChart": {
            "properties": {
                "chartType": "string",    # bar, line, pie, scatter, area
                "data": "object",         # Recharts-compatible data
                "options": "object",
                "width": "string",
                "height": "string",
            }
        },
        "ObFileCard": {
            "properties": {
                "fileName": "string",
                "fileUrl": "string",
                "fileSize": "number",
                "mimeType": "string",
                "previewUrl": "string",
            }
        },
        "ObCodeBlock": {
            "properties": {
                "code": "string",
                "language": "string",
                "showLineNumbers": "boolean",
                "maxHeight": "string",
            }
        },
        "ObMarkdown": {
            "properties": {
                "content": "string",
                "allowHtml": "boolean",
            }
        },
        "ObTable": {
            "properties": {
                "headers": "array",
                "rows": "array",
                "striped": "boolean",
                "compact": "boolean",
            }
        },
        "ObCallout": {
            "properties": {
                "content": "string",
                "variant": "string",      # default, info, success, warning
                "title": "string",
            }
        },
    },
    # Includes all 14 standard functions
    "functions": "inherit_from_standard",
}
```

Note: `AudioPlayer` and `Video` are **standard A2UI components** -- no custom wrappers needed.

#### ContentRenderer (renderers/base.py)

Abstract base for converting agent output to A2UI components. Uses the same `PluginRegistry` pattern as the rest of OpenBench:

```python
class ContentRenderer(ABC):
    @property
    @abstractmethod
    def content_type(self) -> str:
        """'text', 'chart', 'code', 'form', 'file', 'media', 'list', 'tabs', 'modal', 'table', 'callout'"""

    @abstractmethod
    def detect(self, content: Any) -> bool:
        """Can this renderer handle the given content?"""

    @abstractmethod
    def render(self, content: Any, surface_id: str) -> list[A2UIComponent]:
        """Convert content to A2UI component definitions."""

# Registry (same pattern as DataSourceRegistry, AgentRegistry, etc.)
ContentRendererRegistry = PluginRegistry[ContentRenderer]("content_renderer")
```

11 implementations:

| Renderer | Input | A2UI Output |
|----------|-------|-------------|
| `TextRenderer` | str / markdown | `Text` components with variant hints |
| `ChartRenderer` | `{"type":"bar","data":{...}}` | `ObChart` custom component |
| `CodeRenderer` | `{"code":"...","language":"..."}` | `ObCodeBlock` custom component |
| `FormRenderer` | `{"fields":[...]}` | `TextField + CheckBox + ChoicePicker + Button` with data binding |
| `FileRenderer` | `{"name":"...","url":"..."}` | `ObFileCard` custom component |
| `MediaRenderer` | `{"src":"...","mediaType":"image"}` | `Image`, `Video`, or `AudioPlayer` standard components |
| `ListRenderer` | `{"items":[...],"listType":"ordered"}` | `List + Text` components |
| `TabsRenderer` | `{"tabs":[...]}` | `Tabs + ObMarkdown` components |
| `ModalRenderer` | `{"modalContent":"..."}` | `Modal + ObMarkdown` components |
| `TableRenderer` | `{"headers":[...],"rows":[...]}` | `ObTable` custom component |
| `CalloutRenderer` | `{"calloutContent":"..."}` | `ObCallout` custom component |

#### A2UIMessageBuilder (a2ui/builder.py)

Takes component definitions from renderers and builds A2UI v0.10 JSONL:

```python
class A2UIMessageBuilder:
    def __init__(self, catalog_id: str = OPENBENCH_CATALOG_ID):
        self.catalog_id = catalog_id

    def build_surface(self, surface_id: str, components: list[A2UIComponent],
                      data_model: dict | None = None,
                      theme: dict | None = None,
                      send_data_model: bool = False) -> list[dict]:
        """Build complete surface: createSurface + updateComponents + optional updateDataModel.

        One component MUST have id="root" to serve as the tree root.
        """

    def build_create_surface(self, surface_id: str,
                              theme: dict | None = None,
                              send_data_model: bool = False) -> dict:
        """Build a createSurface message."""

    def build_update_components(self, surface_id: str,
                                 components: list[A2UIComponent]) -> dict:
        """Build an updateComponents message."""

    def build_update_data_model(self, surface_id: str,
                                 path: str | None = None,
                                 value: Any = None) -> dict:
        """Build an updateDataModel message."""

    def build_delete_surface(self, surface_id: str) -> dict:
        """Build a deleteSurface message."""

    def to_jsonl(self, messages: list[dict]) -> str:
        """Serialize messages to JSONL string (one JSON per line)."""
```

#### ChatEngine (engine.py)

The main orchestrator. Inherits from `Chainable[Any, dict[str, Any]]` following the same pattern as `DataLayer`, `IntelligenceLayer`, etc.

```python
class ChatEngine(Chainable[Any, dict[str, Any]]):
    """Orchestrates: user input -> agent -> content renderers -> A2UI v0.10 JSONL.

    Composable with existing L1/L2 components:
        DataLayer(sources) | ChatEngine(agent=my_agent)
        ChatEngine(agent) | OutputLayer(generators=[transcript])
    """

    def __init__(
        self,
        agent: Agent | FrameworkAdapter,
        renderers: list[ContentRenderer] | None = None,   # auto-detect if None
        session: ChatSession | None = None,               # create new if None
        catalog_id: str | None = None,                    # default: OPENBENCH_CATALOG_ID
    ): ...

    def invoke(self, input: dict, config: RunnableConfig | None = None) -> dict:
        """Process a single message turn.

        Input: {"content": "...", "attachments": [...], "session_id": "..."}
        Output: {
            "messages": [A2UI v0.10 JSONL lines],
            "session": ChatSession,
            "metadata": {"model": "...", "tokens": ..., ...}
        }
        """

    async def ainvoke(self, input: dict, config: RunnableConfig | None = None) -> dict:
        """Async message processing."""

    def stream(self, input: dict, config: RunnableConfig | None = None) -> Iterator[str]:
        """Stream A2UI v0.10 JSONL lines as they're generated."""
```

Processing flow inside `invoke()`:
```
1. Parse input (content, attachments, session_id)
2. Get or create ChatSession
3. Add user message to session
4. Execute agent (agent.invoke() or agent.execute())
5. Auto-detect content types in agent output
6. Run matching ContentRenderers -> A2UIComponent list
7. Ensure one component has id="root"
8. Build JSONL via A2UIMessageBuilder:
   a. createSurface (with catalogId)
   b. updateComponents (flat adjacency list)
   c. updateDataModel (if data bindings present)
9. Add assistant message (with surfaces) to session
10. Return {messages, session, metadata}
```

**Streaming flow** (via AGUIHandler):
```
1. Parse input, add user message to session
2. Step "Processing input"
3. Step "Thinking":
   a. agent.execute(context, on_chunk=callback) in thread pool
   b. on_chunk puts deltas into asyncio.Queue (thread-safe bridge)
   c. TEXT_MESSAGE_START -> TEXT_MESSAGE_CONTENT (deltas) -> TEXT_MESSAGE_END
4. Step "Rendering response" (only if rich content like charts/files):
   a. ContentRenderers produce A2UI components (text skipped, already streamed)
   b. CUSTOM(a2ui, createSurface) -> CUSTOM(a2ui, updateComponents)
5. RUN_FINISHED with complete text + metadata
```

Text-only responses have 2 steps (Processing + Thinking). Rich content responses have 3 steps (+ Rendering).

#### ChatLayer (layer.py)

L2 orchestrator -- composable with DataLayer, IntelligenceLayer, OutputLayer:

```python
class ChatLayer(Chainable[Any, dict[str, Any]]):
    """L2 chat orchestrator.

    Usage:
        # Standalone
        chat = ChatLayer(agent=my_agent)
        result = chat.invoke({"content": "Hello"})

        # With data pipeline
        workflow = DataLayer(sources=[pdf]) | ChatLayer(agent=rag_agent)

        # With output
        workflow = ChatLayer(agent=agent) | OutputLayer(generators=[transcript])
    """

    def __init__(
        self,
        agent: Agent | FrameworkAdapter,
        renderers: list[ContentRenderer] | None = None,
    ): ...

    def invoke(self, input: Any, config: RunnableConfig | None = None) -> dict[str, Any]:
        """Execute chat layer.

        Returns:
            {
                "chat_output": dict,          # ChatEngine result
                "metadata": {"layer": "chat", ...},
                # preserved keys: goal, output_path, title, author, template
            }
        """
```

#### AG-UI Transport (transport/agui.py)

AG-UI protocol handler that streams standardized events via SSE. A2UI v0.10 messages
are wrapped inside `CustomEvent(name="a2ui")` payloads:

```python
class AGUIHandler:
    """AG-UI protocol handler for chat.

    Usage with FastAPI:
        app = FastAPI()
        handler = AGUIHandler(engine=ChatEngine(agent=my_agent))

        @app.post("/awp")
        async def agent_endpoint(request: Request):
            return await handler.handle(request)
    """

    def __init__(self, engine: ChatEngine): ...
    async def handle(self, request: Request) -> StreamingResponse: ...
```

The `AGUIActionHandler` (transport/agui_actions.py) handles REST actions (button clicks, form submits).

### AG-UI + REST Protocol

```
Client (@openbench/chat-ui)              Server (Python)
  |                                          |
  |-- POST /awp --------------------------->|  User sends message
  |   { "threadId": "...",                  |  (AG-UI RunAgentInput format)
  |     "messages": [{ "role": "user",      |
  |       "content": "Show Q4 sales" }],    |
  |     "forwardedProps": { ... } }         |
  |                                          |
  |<-- data: {"type":"RUN_STARTED",         |  AG-UI: run started
  |     "threadId":"t1","runId":"r1"}       |
  |                                          |
  |<-- data: {"type":"STEP_STARTED",        |  AG-UI: step progress
  |     "stepName":"Processing input"}      |
  |<-- data: {"type":"STEP_FINISHED",       |
  |     "stepName":"Processing input"}      |
  |                                          |
  |<-- data: {"type":"STEP_STARTED",        |  AG-UI: thinking step
  |     "stepName":"Thinking"}              |
  |                                          |
  |<-- data: {"type":"TEXT_MESSAGE_START",  |  AG-UI: text streaming begins
  |     "messageId":"msg-abc123",           |
  |     "role":"assistant"}                 |
  |                                          |
  |<-- data: {"type":"TEXT_MESSAGE_CONTENT",|  AG-UI: progressive text deltas
  |     "messageId":"msg-abc123",           |  (token-by-token streaming)
  |     "delta":"The quarterly"}            |
  |<-- data: {"type":"TEXT_MESSAGE_CONTENT",|
  |     "messageId":"msg-abc123",           |
  |     "delta":" revenue shows..."}        |
  |   ... (more deltas)                     |
  |                                          |
  |<-- data: {"type":"TEXT_MESSAGE_END",    |  AG-UI: text streaming complete
  |     "messageId":"msg-abc123"}           |
  |                                          |
  |<-- data: {"type":"STEP_FINISHED",       |
  |     "stepName":"Thinking"}              |
  |                                          |
  |<-- data: {"type":"STEP_STARTED",        |  AG-UI: rendering (only if rich content)
  |     "stepName":"Rendering response"}    |
  |                                          |
  |<-- data: {"type":"CUSTOM",              |  AG-UI: A2UI create surface
  |     "name":"a2ui","value":{             |
  |       "version":"v0.10",                |
  |       "createSurface":{...}}}           |
  |                                          |
  |<-- data: {"type":"CUSTOM",              |  AG-UI: A2UI components
  |     "name":"a2ui","value":{             |
  |       "version":"v0.10",                |
  |       "updateComponents":{...}}}        |
  |                                          |
  |<-- data: {"type":"STEP_FINISHED",       |
  |     "stepName":"Rendering response"}    |
  |                                          |
  |<-- data: {"type":"RUN_FINISHED",        |  AG-UI: run complete
  |     "threadId":"t1","runId":"r1",       |
  |     "result":{"content":"...","metadata":{...}}}  |
  |                                          |
  |-- POST /chat/action ------------------>|  User action (A2UI event)
  |   { "name": "submit_form",             |
  |     "surfaceId": "s1",                  |
  |     "sourceComponentId": "submit-btn",  |
  |     "context": { "email": "a@b.com" }} |
  |<-- [response messages] (JSON array)     |
```

### Modified Existing Files

| File | Change |
|------|--------|
| `src/openbench/__init__.py` | Add `ChatLayer` export |
| `src/openbench/core/__init__.py` | Add `ChatLayer` to exports |
| `src/openbench/core/layers.py` | Import and re-export `ChatLayer` |
| `pyproject.toml` | Add `chat` optional dependency group |

### Python Test Files

| File | Coverage |
|------|----------|
| `tests/test_chat_session.py` | ChatMessage, Attachment, ChatSession CRUD, serialization |
| `tests/test_a2ui_builder.py` | A2UI v0.10 JSONL generation, all 4 message types, validation |
| `tests/test_content_renderers.py` | All 11 renderers: detect + render |
| `tests/test_chat_engine.py` | ChatEngine invoke, stream, compose with layers |
| `tests/test_chat_layer.py` | ChatLayer L2 composition: DataLayer \| ChatLayer \| OutputLayer |

---

## Part 2: TypeScript Frontend SDK

### Package Structure

```
studio/chat-ui/
├── package.json                    # @openbench/chat-ui
├── tsconfig.json
├── vite.config.ts                  # Library mode (ESM + .d.ts)
├── src/
│   ├── index.ts                    # Public API exports
│   ├── types.ts                    # All TypeScript interfaces
│   │
│   ├── core/                       # No React dependency
│   │   ├── transport.ts            # AG-UI transport (HttpAgent, sendAction)
│   │   ├── message-processor.ts    # A2UI v0.10 JSONL parser + surface state
│   │   ├── chat-store.ts           # Zustand store (sessions, messages, streaming)
│   │   └── utils.ts                # Helpers (formatTime, formatFileSize, generateId)
│   │
│   ├── a2ui/                       # A2UI rendering layer
│   │   ├── surface-renderer.tsx    # Adjacency list -> React tree
│   │   ├── catalog.ts              # Component registry + registerCustomComponent()
│   │   ├── data-binding.ts         # JSON Pointer (RFC 6901) resolver
│   │   ├── functions.ts            # A2UI function evaluator (14 standard functions)
│   │   ├── checks.ts               # Validation check runner
│   │   ├── standard/               # 18 standard A2UI components
│   │   │   ├── index.ts
│   │   │   ├── a2ui-text.tsx
│   │   │   ├── a2ui-image.tsx
│   │   │   ├── a2ui-icon.tsx
│   │   │   ├── a2ui-video.tsx
│   │   │   ├── a2ui-audio-player.tsx
│   │   │   ├── a2ui-row.tsx
│   │   │   ├── a2ui-column.tsx
│   │   │   ├── a2ui-list.tsx
│   │   │   ├── a2ui-card.tsx
│   │   │   ├── a2ui-tabs.tsx
│   │   │   ├── a2ui-modal.tsx
│   │   │   ├── a2ui-divider.tsx
│   │   │   ├── a2ui-button.tsx
│   │   │   ├── a2ui-textfield.tsx
│   │   │   ├── a2ui-checkbox.tsx
│   │   │   ├── a2ui-choice-picker.tsx
│   │   │   ├── a2ui-slider.tsx
│   │   │   └── a2ui-datetime-input.tsx
│   │   └── custom/                 # 7 OpenBench extended components
│   │       ├── index.ts
│   │       ├── ob-chart.tsx        # Recharts wrapper
│   │       ├── ob-file-card.tsx
│   │       ├── ob-code-block.tsx   # Shiki syntax highlighting
│   │       ├── ob-markdown.tsx     # react-markdown
│   │       ├── ob-table.tsx        # Structured tables
│   │       └── ob-callout.tsx      # Styled callout boxes
│   │
│   ├── components/                 # Pre-built chat UI
│   │   ├── ChatProvider.tsx        # React context (config, transport, store)
│   │   ├── ChatPanel.tsx           # Main chat area (MessageList + ChatInput)
│   │   ├── MessageList.tsx         # Scrollable message history
│   │   ├── MessageBubble.tsx       # Single message (text + A2UI surfaces)
│   │   ├── ChatInput.tsx           # Text input + file upload + send
│   │   ├── StreamingIndicator.tsx  # Typing dots animation
│   │   ├── AttachmentPreview.tsx   # File/media preview before sending
│   │   ├── SessionSidebar.tsx      # Session list (create, switch, delete)
│   │   └── WelcomeScreen.tsx       # Empty state with suggestions
│   │
│   └── hooks/                      # React hooks for custom UIs
│       ├── use-chat.ts             # Main: sendMessage, messages, isStreaming
│       └── use-a2ui-processor.ts   # Process A2UI JSONL -> surfaces
│
├── styles/
│   └── chat-ui.css                 # Default styles (plain CSS)
│
└── tests/
    ├── message-processor.test.ts
    ├── surface-renderer.test.tsx
    ├── data-binding.test.ts
    ├── functions.test.ts
    ├── chat-store.test.ts
    └── transport.test.ts
```

### Layer Architecture

```
+---------------------------------------------+
|            Components Layer                  |  React components
|  ChatProvider, ChatPanel, MessageBubble ...  |  (drop-in ready)
+---------------------------------------------+
|              Hooks Layer                     |  React hooks
|  useChat, useA2UIProcessor                   |  (for custom UIs)
+---------------------------------------------+
|              A2UI Layer                      |  Rendering engine
|  SurfaceRenderer, Catalog, DataBinding,     |  (framework for A2UI v0.10)
|  Functions, Checks                          |
+---------------------------------------------+
|              Core Layer                      |  No React dependency
|  AGUITransport, MessageProcessor, ChatStore |  (headless usage)
+---------------------------------------------+
```

Each layer can be used independently. A developer building a fully custom UI only needs Core + Hooks. Someone extending the component set uses A2UI + Catalog. Drop-in users import Components directly.

### Core Types (types.ts)

```typescript
// -- Chat Messages --
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  surfaces?: A2UISurface[];
  attachments?: Attachment[];
  timestamp: string;                  // ISO 8601
  status: 'sending' | 'streaming' | 'complete' | 'error';
  metadata?: MessageMetadata;
}

interface MessageMetadata {
  model?: string;
  tokensUsed?: number;
  cost?: number;
  latencyMs?: number;
  toolCalls?: ToolCallInfo[];
}

interface ToolCallInfo {
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
  status: 'pending' | 'running' | 'completed' | 'error';
}

// -- Attachments --
interface Attachment {
  id: string;
  type: 'file' | 'audio' | 'video' | 'image';
  name: string;
  url: string;
  mimeType: string;
  sizeBytes?: number;
}

// -- Sessions --
interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: string;
  updatedAt: string;
}

// -- A2UI v0.10 Types --
interface A2UISurface {
  surfaceId: string;
  catalogId: string;
  components: Map<string, A2UIComponent>;  // indexed by component ID
  dataModel: Record<string, unknown>;
  theme?: A2UITheme;
  sendDataModel?: boolean;
}

interface A2UIComponent {
  id: string;
  component: string;                 // "Text", "Column", "ObChart", etc.
  [key: string]: unknown;            // Flat properties (text, children, variant, etc.)
}

interface A2UITheme {
  primaryColor?: string;             // Hex color, e.g. "#00BFFF"
  iconUrl?: string;                  // Agent icon URL
  agentDisplayName?: string;         // Agent display name
}

// -- A2UI Actions (sent back to server) --
interface A2UIAction {
  name: string;                      // Event name from action.event.name
  surfaceId: string;
  sourceComponentId: string;
  timestamp: string;                 // ISO 8601
  context: Record<string, unknown>;  // Resolved from action.event.context
}

// -- Data Binding --
type DynamicString = string | DataBinding | FunctionCall;
type DynamicNumber = number | DataBinding | FunctionCall;
type DynamicBoolean = boolean | DataBinding | FunctionCall;

interface DataBinding {
  path: string;                      // JSON Pointer (RFC 6901)
}

interface FunctionCall {
  call: string;                      // Function name (e.g. "formatString")
  args?: Record<string, unknown>;
  returnType?: string;
}

// -- Configuration --
interface ChatConfig {
  streamUrl: string;                   // POST → SSE AG-UI endpoint (e.g., "/awp")
  actionUrl?: string;                  // POST → JSON (defaults to "/chat/action")
  theme?: 'light' | 'dark' | 'auto';
}

type TransportStatus = 'connected' | 'disconnected' | 'error';
```

### Key Component Designs

#### SurfaceRenderer -- A2UI adjacency list -> React tree

```
Input: A2UISurface received from createSurface + updateComponents + updateDataModel

Processing:
  1. Store components in Map<string, A2UIComponent>
  2. Find component with id="root"
  3. Look up component type in catalog: "Column" -> A2UIColumn React component
  4. Resolve Dynamic* properties:
     - Literal value -> use directly
     - DataBinding {path: "/..."} -> resolve via JSON Pointer against dataModel
     - FunctionCall {call: "formatString", ...} -> evaluate via functions engine
  5. Resolve children:
     - ChildList as array -> map IDs to components
     - ChildList as template -> iterate data array, instantiate template per item
  6. Recursively render child components
  7. Wire action handlers (Button clicks -> resolve context -> dispatch A2UIAction)
  8. Handle two-way binding for input components (TextField, CheckBox, etc.)

Output: React tree
  <A2UIColumn>
    <A2UIText text="Q4 sales:" variant="h2" />
    <ObChart component="ObChart" chartType="bar" data={resolvedData} />
  </A2UIColumn>
```

#### A2UIMessageProcessor -- Stateful JSONL parser

```
Maintains per-surface state:
  surfaces: Map<surfaceId, A2UISurface>

processMessage(jsonLine):
  parse JSON, check "version" === "v0.10"

  if createSurface    -> create new surface entry {surfaceId, catalogId, theme, components: {}, dataModel: {}}
  if updateComponents -> merge components into surface.components (add/replace by id)
                         if any component has id="root", surface is renderable
  if updateDataModel  -> update data at JSON Pointer path in surface.dataModel
                         if path omitted or "/", replace entire dataModel
                         if value omitted, remove key at path
  if deleteSurface    -> remove surface from map

getSurface(surfaceId) -> A2UISurface | null
getRenderableSurfaces() -> surfaces where a component with id="root" exists
```

#### Zustand ChatStore

```
State:
  sessions: ChatSession[]
  activeSessionId: string | null
  messages: ChatMessage[]           # for active session
  isStreaming: boolean
  connectionStatus: TransportStatus
  sidebarOpen: boolean

Actions:
  sendMessage(content, attachments?)
  addMessage(message)
  updateMessage(id, patch)
  appendSurface(messageId, surface)
  createSession() -> sessionId
  switchSession(id)
  deleteSession(id)
  setStreaming(bool)
  setConnectionStatus(status)
```

### Public API (index.ts)

```typescript
// Components (drop-in)
export { ChatProvider, ChatPanel, MessageList, MessageBubble,
         ChatInput, SessionSidebar, WelcomeScreen };

// Hooks (custom UI)
export { useChat, useA2UIProcessor };

// A2UI (extend)
export { SurfaceRenderer, registerCustomComponent, getComponentCatalog };

// Core (headless)
export { AGUITransport, A2UIMessageProcessor, useChatStore };

// Types
export type { ChatMessage, ChatSession, Attachment, A2UISurface,
              A2UIComponent, A2UIAction, ChatConfig, TransportStatus,
              DynamicString, DynamicNumber, DynamicBoolean, DataBinding };
```

### Usage Patterns

```tsx
// 1. Drop-in (full chat page)
import { ChatProvider, ChatPanel, SessionSidebar } from '@openbench/chat-ui';
import '@openbench/chat-ui/styles/chat-ui.css';

function ChatPage() {
  return (
    <ChatProvider config={{ streamUrl: '/awp' }}>
      <div className="flex h-screen">
        <SessionSidebar />
        <ChatPanel className="flex-1" />
      </div>
    </ChatProvider>
  );
}

// 2. Custom UI with hooks
import { useChat } from '@openbench/chat-ui';

function MyChat() {
  const { messages, sendMessage, isStreaming } = useChat({
    streamUrl: '/awp',
  });
  // ... render custom UI
}

// 3. Extend A2UI catalog
import { registerCustomComponent } from '@openbench/chat-ui';
registerCustomComponent('MyWidget', MyWidgetComponent);
```

---

## Data Flow -- Full Message Lifecycle

```
User types "Show Q4 sales by region" -> clicks Send
  |
  v
ChatInput.onSend()
  |-- chatStore.addMessage({ role: "user", content: "...", status: "complete" })
  |-- chatStore.addMessage({ role: "assistant", content: "", status: "streaming" })
  +-- transport.run(content, sessionId, attachments)
        |
        v
POST /awp -> Python AGUIHandler._event_stream()
  |-- session.add_user_message(content)
  |-- agent.execute(context, on_chunk=callback)  -> progressive streaming
  |     |-- on_chunk("The ")     -> queue -> TEXT_MESSAGE_CONTENT(delta="The ")
  |     |-- on_chunk("revenue ") -> queue -> TEXT_MESSAGE_CONTENT(delta="revenue ")
  |     |-- ... (tokens stream progressively via asyncio.Queue bridge)
  |     +-- returns ExecutionResult with complete text + structured data
  |-- ContentRenderers detect and render (rich content only, text already streamed):
  |     ChartRenderer  -> ObChart component (with id, component, chartType, data)
  |     FileRenderer   -> ObFileCard component (with id, component, fileName, fileUrl)
  |-- A2UIMessageBuilder builds A2UI v0.10 JSONL (only if rich content exists):
  |     1. {"version":"v0.10","createSurface":{"surfaceId":"s1","catalogId":"..."}}
  |     2. {"version":"v0.10","updateComponents":{"surfaceId":"s1","components":[...]}}
  +-- Stream AG-UI events via SSE
        |
        v
transport.onEvent() -> for each AG-UI event:
  |-- { type: "RUN_STARTED" }              -> chatStore.setStreaming(true), create msg
  |-- { type: "STEP_STARTED" }             -> addStep(msgId, stepName)
  |-- { type: "TEXT_MESSAGE_START" }       -> begin text accumulation
  |-- { type: "TEXT_MESSAGE_CONTENT" }     -> append delta to message.content
  |     (multiple deltas arrive progressively, text appears token-by-token)
  |-- { type: "TEXT_MESSAGE_END" }         -> text streaming complete
  |-- { type: "CUSTOM", name: "a2ui" }    -> A2UI message processing (rich content):
  |     |-- { createSurface: {...} }    -> messageProcessor: create surface entry
  |     |-- { updateComponents: {...} } -> messageProcessor: merge components
  |     |                                  if root exists -> surface renderable
  |     |                                  -> chatStore.appendSurface(msgId, surface)
  |     |                                  -> SurfaceRenderer builds React tree:
  |     |                                     Text -> <A2UIText text="..." variant="h2" />
  |     |                                     ObChart -> <ObChart chartType="bar" data={...} />
  |     |                                     ObFileCard -> <ObFileCard fileName="Q4-Report.pdf" />
  |     +-- { updateDataModel: {...} }  -> messageProcessor: update data at path
  |                                        -> re-render components bound to updated data
  |-- { type: "STEP_FINISHED" }         -> completeStep(msgId, stepName)
  +-- { type: "RUN_FINISHED" }          -> chatStore.setStreaming(false)
                                           -> updateMessage(msgId, { status: "complete" })
```

---

## Chat Page Layout

```
+------------------------------------------------------------------+
| ChatProvider                                                      |
| +----------+-----------------------------------------------------+
| | Session  |              ChatPanel                               |
| | Sidebar  |  +-----------------------------------------------+  |
| | (240px)  |  |  MessageList (auto-scroll)                    |  |
| |          |  |                                                |  |
| | [+ New]  |  |  User: "Show Q4 sales by region"              |  |
| |          |  |                                                |  |
| | Today    |  |  Assistant:                                    |  |
| |  Chat 1  |  |   "Here's the Q4 breakdown:"                  |  |
| |  Chat 2  |  |   +----------------------------+               |  |
| |          |  |   | ObChart (Recharts BarChart) |               |  |
| | Yesterday|  |   |  NA   EU  APAC  LATAM      |               |  |
| |  Chat 3  |  |   +----------------------------+               |  |
| |          |  |   +----------------------------+               |  |
| |          |  |   | ObFileCard                  |               |  |
| |          |  |   | Q4-Report.pdf  2.1MB  [DL]  |               |  |
| |          |  |   +----------------------------+               |  |
| |          |  |                                                |  |
| |          |  |  +------------------------------------------+  |  |
| |          |  |  | ChatInput                                |  |  |
| |          |  |  | [clip] [Type a message...           ] [>]|  |  |
| |          |  |  +------------------------------------------+  |  |
| |          |  +-----------------------------------------------+  |
| +----------+-----------------------------------------------------+
+------------------------------------------------------------------+
```

---

## A2UI Component Catalog

### Standard (18 from A2UI v0.10 spec)

| Component | Purpose | Key Properties |
|-----------|---------|----------------|
| `Text` | Text display (simple Markdown) | `text` (DynamicString), `variant` (h1-h5, caption, body) |
| `Image` | Image from URL | `url` (DynamicString), `fit`, `variant` |
| `Icon` | System icon | `name` (enum of 50+ icons or DynamicString) |
| `Video` | Video from URL | `url` (DynamicString) |
| `AudioPlayer` | Audio playback | `url` (DynamicString), `description` |
| `Row` | Horizontal layout | `children` (ChildList), `justify`, `align` |
| `Column` | Vertical layout | `children` (ChildList), `justify`, `align` |
| `List` | Scrollable list | `children` (ChildList), `direction`, `align` |
| `Card` | Container | `child` (ComponentId) |
| `Tabs` | Tab interface | `tabs` (array of {title, child}) |
| `Modal` | Dialog overlay | `trigger` (ComponentId), `content` (ComponentId) |
| `Divider` | Visual separator | `axis` (horizontal/vertical) |
| `Button` | Clickable action | `child` (ComponentId), `variant`, `action`, `checks` |
| `TextField` | Text input | `label`, `value` (DynamicString), `variant`, `checks` |
| `CheckBox` | Boolean toggle | `label`, `value` (DynamicBoolean), `checks` |
| `ChoicePicker` | Option selection | `options`, `value` (DynamicStringList), `variant`, `checks` |
| `Slider` | Numeric range | `label`, `value` (DynamicNumber), `min`, `max`, `checks` |
| `DateTimeInput` | Date/time input | `value` (DynamicString), `enableDate`, `enableTime`, `min`, `max` |

### Custom (7 OpenBench extensions)

| Component | Library | Purpose |
|-----------|---------|---------|
| `ObChart` | Recharts | Bar, line, pie, scatter, area charts |
| `ObFileCard` | Custom | File preview card with download |
| `ObCodeBlock` | Shiki | Syntax-highlighted code blocks |
| `ObMarkdown` | react-markdown | Rich markdown rendering |
| `ObTable` | Custom | Structured tabular data display |
| `ObCallout` | Custom + react-markdown | Styled callout boxes (info, success, warning) |

### Standard Functions (14)

| Function | Type | Purpose |
|----------|------|---------|
| `required` | boolean | Value is not null/undefined/empty |
| `regex` | boolean | Value matches regex pattern |
| `length` | boolean | String length within min/max bounds |
| `numeric` | boolean | Number within min/max bounds |
| `email` | boolean | Valid email address |
| `formatString` | string | String interpolation with `${path}` and `${fn()}` syntax |
| `formatNumber` | string | Number formatting (decimals, grouping) |
| `formatCurrency` | string | Currency formatting (ISO 4217 code) |
| `formatDate` | string | Date formatting (Unicode TR35 patterns) |
| `pluralize` | string | Plural-aware string selection (CLDR categories) |
| `openUrl` | void | Open URL in browser |
| `and` | boolean | Logical AND on boolean list |
| `or` | boolean | Logical OR on boolean list |
| `not` | boolean | Logical NOT on boolean value |

---

## Dependencies

### Python (pyproject.toml addition)

```toml
chat = [
    "fastapi>=0.100.0",
    "uvicorn>=0.25.0",
]
```

### TypeScript (package.json)

```json
{
  "peerDependencies": {
    "react": "^18.0.0 || ^19.0.0",
    "react-dom": "^18.0.0 || ^19.0.0"
  },
  "dependencies": {
    "zustand": "^5.0.0",
    "recharts": "^2.15.0",
    "react-markdown": "^9.0.0",
    "shiki": "^1.0.0"
  }
}
```

---

## Implementation Order

| Phase | Scope | Output |
|-------|-------|--------|
| **1** | Core Python SDK | session.py, a2ui/schema.py, a2ui/catalog.py, renderers/base.py, renderers/text.py, a2ui/builder.py + tests |
| **2** | Rich renderers | chart.py, form.py, file.py + tests |
| **3** | Engine + transport + layer | engine.py, layer.py, transport/, exports, pyproject.toml + tests |
| **4** | TS scaffolding + core | package.json, tsconfig, vite, types.ts, core/ modules + tests |
| **5** | A2UI components | catalog.ts, data-binding.ts, functions.ts, surface-renderer.tsx, 18 standard + 4 custom + tests |
| **6** | Chat UI components | hooks, components, index.ts, CSS, build |

---

## Verification

### Python
- `pytest tests/test_chat_*.py -v` -- all renderers, builder, session, engine
- `ChatEngine` composed with `DataLayer` + agent pipeline
- JSONL output validated against A2UI v0.10 spec (server_to_client.json schema)
- `DataLayer | ChatLayer | OutputLayer` pipeline

### TypeScript
- `pnpm build` -> `dist/` with ESM + `.d.ts`
- `pnpm tsc --noEmit` -- type check
- `pnpm vitest` -- message processor, data binding, functions, store, transport
- E2E: Python AG-UI server + React app consuming `@openbench/chat-ui`
