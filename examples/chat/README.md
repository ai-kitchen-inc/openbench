# OpenBench Chat Demo

End-to-end demo: Python WebSocket backend + React frontend using `@openbench/chat-ui`.

## Two Modes

| Mode | When | Agent | Capabilities |
|------|------|-------|-------------|
| **Gemini** | `GOOGLE_API_KEY` is set | `BaseAgent` + `GeminiLLMProvider` | Real LLM reasoning, tool calling, multi-turn memory |
| **Mock** | No API key | `MockAgent` | Deterministic responses based on keywords |

The server auto-detects which mode to use at startup.

## Quick Start

### 1. Start the backend

```bash
cd examples/chat
pip install fastapi uvicorn websockets

# Option A: With real Gemini agent
export GOOGLE_API_KEY=your-key-here
uvicorn server:app --port 8000 --reload

# Option B: Without API key (mock agent)
uvicorn server:app --port 8000 --reload
```

### 2. Start the frontend

```bash
cd examples/chat/frontend
npm install
npm run dev
```

### 3. Open the browser

Navigate to http://localhost:5173

## Example Prompts

### Mock mode (keyword-based)

| Prompt | Content Type |
|--------|-------------|
| `chart` or `sales` | Bar chart |
| `pie` | Pie chart |
| `line` or `trend` | Line chart |
| `form` or `register` | Interactive form |
| `file` or `download` | File card |
| anything else | Markdown text |

### Gemini mode (real AI)

- "What are the latest AI trends?" (uses knowledge_lookup tool)
- "Calculate sqrt(144) * pi" (uses calculate tool)
- "What time is it?" (uses get_datetime tool)
- "Compare solar and wind energy costs" (tool + reasoning)
- Any open-ended question (direct LLM response)

## Project Structure

```
examples/chat/
├── mock_agent.py           # Mock agent (no API key)
├── gemini_agent.py         # Real Gemini agent (BaseAgent + tools)
├── server.py               # FastAPI server (auto-detects mode)
├── frontend/
│   ├── package.json        # Vite + React + @openbench/chat-ui
│   ├── tsconfig.json       # TypeScript config
│   ├── vite.config.ts      # Vite dev (proxies WS to :8000)
│   ├── index.html          # Entry HTML
│   └── src/
│       ├── main.tsx        # React entry
│       ├── global.css      # Fullscreen reset
│       ├── App.tsx         # Drop-in: ChatProvider + SessionSidebar + ChatPanel
│       └── CustomApp.tsx   # Hook-based: useChat() + SurfaceRenderer
└── README.md
```

## Two Frontend Examples

### App.tsx (default) -- Drop-in

Uses `ChatProvider` + `SessionSidebar` + `ChatPanel`. Minimal code, full features.

### CustomApp.tsx -- Custom UI

Uses `useChat()` hook + `SurfaceRenderer` for a fully custom layout.
Switch by changing the import in `main.tsx`:

```tsx
import App from './CustomApp';
```

## Architecture

```
Browser (React)              Server (Python)
┌──────────────┐             ┌──────────────────┐
│ ChatProvider  │◄──── WS ──►│ FastAPI           │
│  └─ ChatPanel│             │  └─ WS Server     │
│     └─ A2UI  │             │     └─ ChatEngine  │
│       render  │             │       └─ Agent     │
└──────────────┘             │          ├─ Gemini │
                             │          └─ Tools  │
                             └──────────────────┘
```
