---
name: chat-ui
description: Building and extending the @openbench/chat-ui TypeScript/React SDK. Use when creating chat components, A2UI v0.10 renderers, custom components, hooks, SSE + REST transport, or styling the chat interface.
---

# Chat UI SDK

`@openbench/chat-ui` is a standalone React component library for rendering interactive chat interfaces powered by **A2UI v0.10 JSONL** (Google's declarative JSON streaming UI protocol).

## A2UI v0.10 Key Points

- 4 message types: `createSurface`, `updateComponents`, `updateDataModel`, `deleteSurface`
- Every message has `"version": "v0.10"`
- Components are flat objects: `{id, component, ...properties}` (NOT nested)
- Root component must have `id: "root"`
- Data binding via JSON Pointer (RFC 6901): `{"path": "/user/name"}`
- Actions: `{event: {name, context}}` or `{functionCall: {call, args}}`
- 14 standard functions for validation and formatting
- `checks` system for input validation

## AG-UI Streaming Events

The frontend receives AG-UI events via SSE, including progressive text streaming:

| Event | Purpose |
|-------|---------|
| `TEXT_MESSAGE_START` | Begin accumulating message content |
| `TEXT_MESSAGE_CONTENT` | Append text delta to message buffer (token-by-token) |
| `TEXT_MESSAGE_END` | Finalize text message |
| `STEP_STARTED` / `STEP_FINISHED` | Track processing steps |
| `CUSTOM(name="a2ui")` | A2UI rendering messages (surfaces, components) |
| `RUN_STARTED` / `RUN_FINISHED` | Run lifecycle |

The `useChat` hook handles all events automatically. Text appears progressively via `TEXT_MESSAGE_CONTENT` deltas, then rich content (charts, files) renders via A2UI `CUSTOM` events.

## Package Location

```
packages/chat-ui/
├── src/
│   ├── index.ts              # Public API exports
│   ├── types.ts              # All TypeScript interfaces
│   ├── core/                 # No React dependency
│   │   ├── transport.ts      # SSE + REST client
│   │   ├── message-processor.ts  # A2UI v0.10 JSONL parser
│   │   ├── chat-store.ts     # Zustand store
│   │   └── utils.ts          # Helpers
│   ├── a2ui/                 # A2UI rendering
│   │   ├── surface-renderer.tsx
│   │   ├── catalog.ts        # Component registry
│   │   ├── data-binding.ts   # JSON Pointer resolver + function evaluator
│   │   ├── standard/         # 18 standard A2UI components
│   │   └── custom/           # 6 OpenBench extensions
│   ├── components/           # Pre-built chat UI
│   └── hooks/                # React hooks
├── styles/
│   └── chat-ui.css           # Default styles
└── tests/
```

## Usage Patterns

### Drop-in (full chat page)

```tsx
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
```

### Custom UI with hooks

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

### Extend A2UI catalog

```tsx
import { registerCustomComponent } from '@openbench/chat-ui';
registerCustomComponent('MyWidget', MyWidgetComponent);
```

## A2UI Component Catalog

### Standard (18 from A2UI v0.10)

Text, Image, Icon, Video, AudioPlayer, Row, Column, List, Card, Tabs, Modal, Divider, Button, TextField, CheckBox, ChoicePicker, Slider, DateTimeInput

### Custom (6 OpenBench extensions)

| Component | Library | Purpose |
|-----------|---------|---------|
| `ObChart` | Recharts | Bar, line, pie, scatter, area charts |
| `ObFileCard` | Custom | File preview card with download |
| `ObCodeBlock` | Shiki | Syntax-highlighted code blocks |
| `ObMarkdown` | react-markdown | Rich markdown rendering |
| `ObTable` | Custom | Structured tabular data display |
| `ObCallout` | Custom + react-markdown | Styled callout boxes (info, success, warning) |

Note: `AudioPlayer` and `Video` are standard A2UI components -- no custom wrappers needed.

### Standard Functions (14)

Validation: `required`, `regex`, `length`, `numeric`, `email`
Formatting: `formatString`, `formatNumber`, `formatCurrency`, `formatDate`, `pluralize`
Navigation: `openUrl`
Logic: `and`, `or`, `not`

## SurfaceRenderer

Converts A2UI v0.10 adjacency list to React component tree:

```tsx
import { SurfaceRenderer } from '@openbench/chat-ui';

<SurfaceRenderer
  surface={a2uiSurface}
  onAction={(action) => transport.send(action)}
/>
```

Processing:
1. Index components by ID in Map
2. Find component with `id: "root"`
3. Look up `component` type in catalog -> React component
4. Resolve Dynamic* properties (literal | DataBinding | FunctionCall)
5. Resolve ChildList (array of IDs or template with data path)
6. Recursively render children
7. Wire action handlers (resolve context, dispatch A2UIAction)
8. Handle two-way binding for input components

## Design System

**Notion-inspired, monochrome, icon-driven. No emojis.**

- **Colors**: Carbon (#1a1a1a) on White (#ffffff), Gray scale for hierarchy
- **Icons**: Lucide React (clean, consistent, 1px stroke)
- **Typography**: System font stack (Inter where available)
- **Borders**: 1px solid rgba(0,0,0,0.08) -- subtle, not heavy shadows
- **Spacing**: 4px base unit, consistent padding/margin multiples

See `docs/DESIGN_SYSTEM.md` for full design tokens.

## Build Commands

```bash
cd packages/chat-ui
pnpm install          # Install dependencies
pnpm dev              # Dev server
pnpm build            # Build library (ESM + .d.ts)
pnpm tsc --noEmit     # Type check
pnpm vitest           # Run tests
```

## Anti-Patterns

**DO NOT:**
- Import from internal paths -- use public API from `@openbench/chat-ui`
- Use emojis in the UI -- use Lucide icons exclusively
- Add heavy shadows or gradients -- keep Notion-like flat, subtle aesthetic
- Skip data-binding resolution -- always resolve JSON Pointers before rendering
- Create A2UI components without registering in catalog -- use `registerCustomComponent()`
- Mix CSS-in-JS with plain CSS -- use plain CSS with CSS custom properties
- Use `"type"` on components -- the correct A2UI field is `"component"`
- Nest properties inside a `"properties"` dict -- A2UI properties are flat
- Use invented message types like `surfaceUpdate` or `beginRendering`
- Forget to implement standard functions in the data-binding evaluator

## Cross-References

- **Chat Layer**: Python backend that produces A2UI v0.10 JSONL -> see `chat-layer` skill
- **Composing Workflows**: ChatLayer L2 composition -> see `composing-workflows` skill
- **Testing**: Component and hook tests -> see `testing-openbench` skill

For architecture details, see `docs/CHAT_UI_ARCHITECTURE.md`
For design tokens, see `docs/DESIGN_SYSTEM.md`
