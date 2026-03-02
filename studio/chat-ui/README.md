# @openbench/chat-ui

Standalone React component library for building chat interfaces powered by OpenBench. Renders rich, interactive content via the A2UI v0.10 declarative JSON streaming protocol, transported over AG-UI (SSE + REST).

## Features

### Core (headless, no React dependency)

- **AGUITransport** -- SSE client for AG-UI event streaming + REST for user actions
- **ChatStore** -- Zustand vanilla store for sessions, messages, and streaming state
- **MessageProcessor** -- A2UI v0.10 JSONL parser that builds surfaces incrementally
- **StreamManager** -- Coordinates text deltas and A2UI surface events

### A2UI Rendering

- **SurfaceRenderer** -- Converts A2UI adjacency list to React component tree
- **24 components** -- 18 standard A2UI (Text, Image, Button, TextField, Tabs, Modal, ...) + 6 custom OpenBench (ObChart, ObFileCard, ObCodeBlock, ObMarkdown, ObTable, ObCallout)
- **Data binding** -- JSON Pointer resolution, DynamicString/Number/Boolean, 14 standard functions
- **Extensible catalog** -- Register custom components via `registerCustomComponent()`

### Hooks

- **useChat** -- Full chat lifecycle: send messages, receive streaming text + rich content, manage sessions
- **useA2UIProcessor** -- Process raw A2UI JSONL into renderable surfaces

### Components

- **ChatProvider** -- Context provider wrapping store + transport configuration
- **ChatPanel** -- Complete chat interface (messages + input + header)
- **MessageList** -- Scrollable message list with auto-scroll and streaming indicators
- **ChatInput** -- Message input with file attachments
- **SessionSidebar** -- Session history with create/switch/delete
- **MessageBubble**, **TypingIndicator**, **StreamingIndicator**, **WelcomeScreen**

## How It Works

The frontend SDK communicates with the Python A2UI backend via two channels:

```
Browser                          Python Server
  |                                   |
  |-- POST /awp (message) ----------->|  AGUIHandler receives message
  |                                   |  ChatEngine -> Agent -> Renderers
  |<--- SSE stream -------------------|  AG-UI events:
  |   TEXT_MESSAGE_START              |    - Text deltas (token-by-token)
  |   TEXT_MESSAGE_CONTENT (deltas)   |    - A2UI surfaces (charts, forms, files)
  |   CUSTOM(name="a2ui", value=msg)  |    - Step progress indicators
  |   TEXT_MESSAGE_END                |
  |   RUN_FINISHED                    |
  |                                   |
  |-- POST /chat/action ------------->|  AGUIActionHandler processes user action
  |<-- JSON response -----------------|  (button clicks, form submits, etc.)
```

**A2UI messages** are wrapped inside AG-UI `CustomEvent(name="a2ui")` payloads. A2UI handles the rendering protocol (what to show), AG-UI handles the transport protocol (how to deliver).

**Python side pipeline:**

1. `AGUIHandler` receives the user message
2. `ChatEngine` routes to the configured `Agent`
3. Agent generates response (text + structured content)
4. `ContentRenderers` convert structured content to A2UI components
5. `A2UIMessageBuilder` produces A2UI v0.10 JSONL
6. `AGUIHandler` wraps A2UI messages in AG-UI events and streams via SSE

## Quick Start

### Install and build

```bash
cd studio/chat-ui
pnpm install
pnpm build
```

### Use in a React app

```tsx
import { ChatProvider, ChatPanel } from '@openbench/chat-ui';
import '@openbench/chat-ui/styles/chat-ui.css';

function App() {
  return (
    <ChatProvider config={{ streamUrl: '/awp' }}>
      <ChatPanel className="h-screen" />
    </ChatProvider>
  );
}
```

### Use hooks for custom UI

```tsx
import { useChat } from '@openbench/chat-ui';

function MyChat() {
  const { messages, sendMessage, isStreaming } = useChat({
    streamUrl: '/awp',
  });

  return (
    <div>
      {messages.map(m => <div key={m.id}>{m.content}</div>)}
      <button onClick={() => sendMessage('Hello!')}>Send</button>
    </div>
  );
}
```

## Development

```bash
pnpm dev              # Vite dev server
pnpm build            # Build library (ESM + .d.ts via Vite)
pnpm tsc --noEmit     # Type check
pnpm vitest           # Run tests (watch mode)
pnpm vitest run       # Run tests (single run)
npx @biomejs/biome check src/      # Lint
npx @biomejs/biome check --write src/  # Lint + auto-fix
```

## Design System

Notion-inspired. Monochrome. Icon-driven.

- **Colors**: Carbon gray scale (#1a1a1a on #ffffff), blue accent for links only
- **Icons**: Lucide React (16px inline, 18px buttons, 1.5px stroke)
- **Typography**: System font stack, 14px base
- **Borders**: 1px solid rgba(0,0,0,0.08)
- **Spacing**: 4px base unit
- **CSS**: Custom properties with `--ob-` prefix, dark mode via `[data-theme="dark"]`

See [docs/DESIGN_SYSTEM.md](../../docs/DESIGN_SYSTEM.md) for full design tokens.

## Architecture

For the complete system architecture covering both the Python backend (ChatEngine, A2UI builder, content renderers, AG-UI transport) and the TypeScript frontend, see [docs/CHAT_UI_ARCHITECTURE.md](../../docs/CHAT_UI_ARCHITECTURE.md).
