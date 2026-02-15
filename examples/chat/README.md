# OpenBench Chat Demo

End-to-end demo: Python AG-UI backend + React frontend using `@openbench/chat-ui`.

## Features

- **Gemini agent** with real LLM reasoning, tool calling, and multi-turn memory
- **Web search** via Google Search grounding (GroundedSearchSource)
- **File upload & analysis** -- upload PDFs/text files, agent reads and answers questions
- **Knowledge base** -- curated data on renewable energy, AI trends, market data
- **Calculator** -- math expression evaluation
- **Rich UI** -- A2UI v0.10 streaming with charts, forms, file cards, markdown
- **Task Planning** -- agent decomposes complex queries into steps before execution
- **Parallel Tool Execution** -- multiple tools run concurrently for faster responses
- **Persistent Memory** -- conversations survive server restarts via SQLite

## Quick Start

### 1. Start the backend

```bash
cd examples/chat
pip install fastapi uvicorn

export GOOGLE_API_KEY=your-key-here
uvicorn server:app --port 8000 --reload
```

### 2. Start the frontend

```bash
cd examples/chat/frontend
pnpm install
pnpm dev
```

### 3. Open the browser

Navigate to http://localhost:5173

## Example Prompts

- "Search the web for latest AI agent trends" (uses search_web tool)
- "What are the latest AI trends?" (uses knowledge_lookup tool)
- "Calculate sqrt(144) * pi" (uses calculate tool)
- "What time is it?" (uses get_datetime tool)
- "Compare solar and wind energy costs with a chart" (uses knowledge_lookup + create_chart)
- Upload a PDF -> "Summarize this document" (uses analyze_file tool)
- "Give me AI news, market data, and current time" (planning + parallel tools)
- "What did we discuss earlier?" (persistent memory)

## Project Structure

```
examples/chat/
├── gemini_agent.py         # Gemini agent (BaseAgent + 10 tools + Phase 2 params)
├── server.py               # FastAPI server (AG-UI + REST + upload + memory)
├── schemas.py              # Tool schemas (OpenAI function-calling format)
├── prompt.py               # System prompt with tool + capability descriptions
├── frontend/
│   ├── package.json        # Vite + React + @openbench/chat-ui
│   ├── tsconfig.json       # TypeScript config
│   ├── vite.config.ts      # Vite dev (proxies SSE/REST to :8000)
│   ├── index.html          # Entry HTML
│   └── src/
│       ├── main.tsx        # React entry
│       ├── global.css      # Fullscreen reset
│       └── App.tsx         # Drop-in: ChatProvider + SessionSidebar + ChatPanel
└── README.md
```

## Frontend

### App.tsx -- Drop-in

Uses `ChatProvider` + `SessionSidebar` + `ChatPanel`. Minimal code, full features.

## Architecture

```
Browser (React)                         Server (Python)
+--------------------------------------+--------------------------------------+
|                                       |                                      |
|  ChatProvider                         |  FastAPI                             |
|    SessionSidebar                     |                                      |
|    ChatPanel                          |  POST /awp ------> AGUIHandler       |
|      MessageList  <--- SSE stream --- |    TextMessageStart/Content/End      |
|      A2UI surfaces <-- SSE stream --- |    Custom (A2UI createSurface, ...)  |
|      ChatInput --- POST /awp -------> |                                      |
|                                       |  POST /chat/action > ActionHandler   |
|                                       |  POST /chat/upload > file upload     |
|                                       |  GET  /sessions    > memory sessions |
|                                       |                                      |
+--------------------------------------+  ChatEngine                          |
                                        |    Gemini Agent (BaseAgent)          |
                                        |      search_web                     |
                                        |      analyze_file                   |
                                        |      knowledge_lookup               |
                                        |      calculate                      |
                                        |      get_datetime                   |
                                        |    AgenticAGUIHandler               |
                                        |      PersistentMemory (SQLite)      |
                                        |      Planning + Parallel Tools      |
                                        +--------------------------------------+
```
