# OpenBench Chat Demo

End-to-end demo: Python AG-UI backend + React frontend using `@openbench/chat-ui`.

## Features

- **Gemini agent** with real LLM reasoning, tool calling, and multi-turn memory
- **Web search** via Google Search grounding (GroundedSearchSource)
- **Entity extraction** via LangExtract (structured extraction from text/PDF)
- **File upload & analysis** -- upload PDFs/text files, agent reads and answers questions
- **Knowledge base** -- curated data on renewable energy, AI trends, market data
- **Calculator** -- math expression evaluation
- **Rich UI** -- A2UI v0.10 streaming with 17 tools and 12 rich UI component types
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

## Rich UI Components

The agent can render 12 types of rich UI via A2UI v0.10 components:

| # | Component | Tool | A2UI Component | Description |
|---|-----------|------|----------------|-------------|
| 1 | Chart | `create_chart` | ObChart | Bar, line, pie, scatter, area charts |
| 2 | Form | `create_form` | TextField, CheckBox, Slider, etc. | Interactive input forms |
| 3 | File Card | `show_file` | ObFileCard | File download cards |
| 4 | Generated File | `generate_file` | ObFileCard | Create + download files |
| 5 | Code Block | `create_code_block` | ObCodeBlock | Syntax-highlighted code |
| 6 | Media | `show_media` | Image, Video, AudioPlayer | Inline images, video, audio |
| 7 | List | `create_list` | List + Text | Ordered/unordered lists with subtitles |
| 8 | Tabs | `create_tabs` | Tabs + ObMarkdown | Tabbed content panels |
| 9 | Modal | `show_modal` | Modal + ObMarkdown | Overlay dialogs |
| 10 | Table | `create_table` | ObTable | Structured tabular data (headers + rows) |
| 11 | Callout | `create_callout` | ObCallout | Styled callout boxes (info/success/warning) |
| 12 | Markdown | *(text response)* | ObMarkdown | Rich text via streaming |

## Example Prompts

### Lists (create_list)

```
List the top 5 renewable energy sources
```
```
Show me the steps to deploy a Python app to production
```
```
What are the key AI agent frameworks in 2025?
```
```
Rank the most popular programming languages
```
```
Give me a list of 10 healthy breakfast ideas
```

### Charts (create_chart)

```
Compare solar and wind energy costs with a chart
```
```
Show a bar chart of global VC funding by sector
```
```
Create a pie chart of renewable energy market share
```
```
Show AI model parameter growth over time as a line chart
```
```
Create a scatter chart of energy sources by cost vs capacity
```

### Tables (create_table)

```
Create a table comparing solar, wind, and hydro energy: cost, capacity, and growth rate
```
```
Show a comparison table of Python vs JavaScript vs Rust
```
```
Make a table of the top 5 tech companies with revenue, employees, and market cap
```
```
Build a specification table for the latest AI models: name, parameters, release date, and benchmark score
```

### Callouts (create_callout)

```
Give me a tip about improving code performance
```
```
Show a warning about common security vulnerabilities in web apps
```
```
Display a success message about completing the data migration
```
```
Show an info callout explaining how renewable energy credits work
```
```
Warn me about the limitations of this data
```

### Code Blocks (create_code_block)

```
Write a Python quicksort implementation
```
```
Show me a TypeScript React hook for dark mode
```
```
Write a SQL query to find top customers by revenue
```
```
Implement a binary search in JavaScript
```
```
Write a Python FastAPI endpoint with error handling
```

### Forms (create_form)

```
Create a feedback form with name, email, and rating
```
```
Make a registration form for a conference
```
```
Build a settings form with notification preferences
```
```
Create a contact form with name, email, subject, and message
```

### Tabs (create_tabs)

```
Compare solar, wind, and storage in tabs
```
```
Explain Python, JavaScript, and Rust in tabs
```
```
Show AI trends by category: models, agents, and regulation
```
```
Compare renewable energy sources in a tabbed view
```

### Modal (show_modal)

```
Show me a summary of AI trends in a modal
```
```
Display important disclaimers about this data in a modal
```
```
Highlight the key takeaways about solar energy in a modal
```

### Media (show_media)

```
Show me this image: https://upload.wikimedia.org/wikipedia/commons/a/a7/Camponotus_flavomarginatus_ant.jpg
```
```
Display this video: https://www.w3schools.com/html/mov_bbb.mp4
```

### Generated Files (generate_file)

```
Generate a CSV of renewable energy data
```
```
Create a markdown report about AI trends
```
```
Export our conversation as a text file
```
```
Generate an HTML page with a summary of solar energy
```
```
Create a JSON file with market data for tech stocks
```

### File Cards (show_file)

```
Show me the quarterly report PDF
```

### Web Search (search_web)

```
Search the web for latest AI agent trends
```
```
What's happening in the tech industry this week?
```
```
Find recent news about climate change
```

### Entity Extraction (extract_entities)

```
Extract people, organizations, and dates from this article: [paste text]
```
*(Upload a PDF, then:)*
```
Extract key entities from the uploaded document
```

### Knowledge Base (knowledge_lookup)

```
What are the latest AI trends?
```
```
Tell me about solar energy capacity
```
```
How is the venture capital market doing?
```

### Calculator (calculate)

```
Calculate sqrt(144) * pi
```
```
What is 2^10 + log(1000)?
```

### Date/Time (get_datetime)

```
What time is it?
```
```
What's today's date?
```

### File Analysis (analyze_file)

*(Upload a PDF or text file, then:)*
```
Summarize this document
```
```
What are the key points in the uploaded file?
```

### Multi-Tool Combinations

These prompts trigger multiple tools working together:

```
Give me AI news, market data, and current time
```
*(planning + parallel tools: search_web, knowledge_lookup, get_datetime)*

```
Look up renewable energy data and organize it in tabs
```
*(knowledge_lookup + create_tabs)*

```
Search for AI frameworks and show them as a list
```
*(search_web + create_list)*

```
Compare solar vs wind costs with both a chart and a table
```
*(knowledge_lookup + create_chart + create_table)*

```
Write a Python function and generate it as a downloadable file
```
*(create_code_block + generate_file)*

```
List the top AI companies and warn me about market volatility
```
*(create_list + create_callout)*

```
Create a comparison table of databases and add a tip about choosing the right one
```
*(create_table + create_callout)*

```
Show renewable energy data as a chart, list the sources, and add a note about data accuracy
```
*(knowledge_lookup + create_chart + create_list + create_callout)*

### Memory

```
What did we discuss earlier?
```
```
Remind me what you said about solar energy
```

## Project Structure

```
examples/chat/
├── gemini_agent.py         # Gemini agent (BaseAgent + 17 tools + Phase 2 params)
├── server.py               # FastAPI server (AG-UI + REST + upload + memory)
├── schemas.py              # Tool schemas (OpenAI function-calling format)
├── prompt.py               # System prompt with tool-first rendering rules
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

## Tools Reference

| Tool | Function | Parameters |
|------|----------|------------|
| `search_web` | Web search via Gemini grounding | `query` |
| `extract_entities` | Structured entity extraction | `prompt`, `text?`, `filename?` |
| `analyze_file` | Read uploaded file content | `filename?` |
| `knowledge_lookup` | Curated knowledge base | `topic`, `subtopic?` |
| `calculate` | Math expression evaluation | `expression` |
| `get_datetime` | Current date and time | *(none)* |
| `create_chart` | Visual charts | `chart_type`, `title`, `data`, `options?` |
| `create_form` | Interactive forms | `title`, `fields`, `submit_label?` |
| `show_file` | File download cards | `name`, `url`, `mime_type?`, `size?` |
| `generate_file` | Create downloadable files | `filename`, `content`, `mime_type?` |
| `create_code_block` | Syntax-highlighted code | `code`, `language`, `title?` |
| `show_media` | Inline images/video/audio | `url`, `media_type`, `title?`, `caption?` |
| `create_list` | Structured lists | `title`, `items`, `ordered?` |
| `create_tabs` | Tabbed interfaces | `title`, `tabs` |
| `show_modal` | Modal overlays | `title`, `content` |
| `create_table` | Structured tables | `title`, `headers`, `rows`, `caption?` |
| `create_callout` | Styled callout boxes | `content`, `variant?`, `title?` |

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
                                        |      17 tools (see table above)     |
                                        |    AgenticAGUIHandler               |
                                        |      PersistentMemory (SQLite)      |
                                        |      Planning + Parallel Tools      |
                                        +--------------------------------------+
```
