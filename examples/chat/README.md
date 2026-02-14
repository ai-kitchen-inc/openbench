# OpenBench Chat Demo

End-to-end demo: Python AG-UI backend + React frontend using `@openbench/chat-ui`.

## Features

- **Gemini agent** with real LLM reasoning, tool calling, and multi-turn memory
- **Web search** via Google Search grounding (GroundedSearchSource)
- **File upload & analysis** -- upload PDFs/text files, agent reads and answers questions
- **Knowledge base** -- curated data on renewable energy, AI trends, market data
- **Calculator** -- math expression evaluation
- **Rich UI** -- A2UI v0.10 streaming with charts, forms, file cards, markdown

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
- "Compare solar and wind energy costs" (uses knowledge_lookup + reasoning)
- Upload a PDF -> "Summarize this document" (uses analyze_file tool)
- Any open-ended question (direct LLM response)

## Project Structure

```
examples/chat/
├── gemini_agent.py         # Gemini agent (BaseAgent + 5 tools)
├── server.py               # FastAPI server (AG-UI + REST + upload)
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
|                                       |                                      |
+--------------------------------------+  ChatEngine                          |
                                        |    Gemini Agent (BaseAgent)          |
                                        |      search_web                     |
                                        |      analyze_file                   |
                                        |      knowledge_lookup               |
                                        |      calculate                      |
                                        |      get_datetime                   |
                                        +--------------------------------------+
```
