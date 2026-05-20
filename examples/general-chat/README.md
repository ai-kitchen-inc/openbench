# General Chat — Document-Aware Assistant

A full-stack chat demo built on OpenBench. Upload PDFs, Word docs, PowerPoint
slides, spreadsheets, or paste a URL — then ask the Gemini agent questions
about the content.

**Stack:** FastAPI backend (AG-UI / SSE) + React frontend (`@openbench/chat-ui`)

---

## Prerequisites

| Tool | Minimum version |
|------|----------------|
| Python | 3.10 |
| Node.js | 18 |
| pnpm | 8 |
| conda (optional) | any |

You also need a **Google API key** with the Gemini API enabled.
Get one at [aistudio.google.com](https://aistudio.google.com/app/apikey).

For internet source discovery, you should also configure a **Tavily API key**.
Get one at [tavily.com](https://tavily.com/).

---

## 1 — Install OpenBench (parent package)

From the **repo root** (`openbench/`):

```bash
pip install -e ".[all]"
```

This installs the `openbench` SDK that the server imports.

---

## 2 — Configure environment

Copy the template and fill in your key.

Linux/macOS:

```bash
cd examples/general-chat
cp .env.example .env   # if .env.example exists, otherwise edit .env directly
```

Windows (PowerShell):

```powershell
cd examples/general-chat
if (Test-Path .env.example) { Copy-Item .env.example .env } else { New-Item .env -ItemType File -Force }
```

Open `.env` and set at minimum:

```dotenv
GOOGLE_API_KEY=YOUR_KEY_HERE
TAVILY_API_KEY=YOUR_TAVILY_KEY_HERE
```

The other variables in `.env` are optional overrides:

| Variable | Default | Purpose |
|----------|---------|---------|
| `GENERAL_CHAT_MODEL` | `gemini-3-flash-preview` | Gemini model to use |
| `GENERAL_CHAT_UPLOAD_DIR` | `uploads/` | Where uploaded files are stored |
| `GENERAL_CHAT_DOWNLOAD_DIR` | `downloads/` | Where generated exports go |
| `GENERAL_CHAT_STORAGE_ROOT` | `.openbench/` | Session + source JSON storage |
| `GENERAL_CHAT_MEMORY_DB` | `general_chat_memory.db` | SQLite persistent memory |
| `GENERAL_CHAT_MAX_SOURCE_BYTES` | `26214400` (25 MB) | Max size per uploaded source |
| `GENERAL_CHAT_DISCOVERY_PROVIDER` | `tavily` | Primary internet search provider |
| `GENERAL_CHAT_DISCOVERY_PROVIDERS` | `tavily` | Ordered fallback provider list |
| `OPENBENCH_AUTH_DISABLED` | `1` | Disable auth (keep `1` for local dev) |
| `GENERAL_CHAT_MCP_ENABLED` | `0` | Enable opt-in MCP tool adapters for testing |
| `GENERAL_CHAT_MCP_MODE` | `local` | `local` uses in-process OpenBench MCP; `external` uses configured MCP servers |
| `GENERAL_CHAT_MCP_CONFIG` | `mcp/openbench-mcp.yaml` | MCP config file for General Chat |
| `GENERAL_CHAT_MCP_APPROVED_TOOLS` | query tools | Comma-separated namespaced MCP tools exposed to the chat agent |

---

## 3 — Start with OpenBench demo runner (recommended)

```bash
openbench demo run general-chat
```

What this does:

- Starts backend (`uvicorn`) for `examples/general-chat/server.py`
- Starts frontend dev server if `frontend/package.json` exists
- Auto-installs Python deps for the demo when needed
- Auto-installs/builds `studio/chat-ui` when needed

Useful options:

```bash
# Backend only
openbench demo run general-chat --no-frontend

# Skip auto-install steps (faster if already set up)
openbench demo run general-chat --no-install

# Override backend port
openbench demo run general-chat --port 8006
```

You can list all demos with:

```bash
openbench demo list
```

---

## 4 — Manual startup (fallback)

Use this only if you do not want to use the demo runner.

### 4.1 Install Python dependencies

```bash
cd examples/general-chat
pip install -e .
```

This installs `fastapi`, `uvicorn`, `docling`, `python-docx`, `pandas`,
`openpyxl`, `tavily-python`, and the other deps listed in `pyproject.toml`.

### 4.2 Start backend

```bash
cd examples/general-chat
uvicorn server:app --port 8005 --reload
```

Verify it is running: open `http://localhost:8005/health`

Expected response:

```json
{"status":"ok","service":"general-chat"}
```

The startup log shows which model, persona, and skills are loaded.

### 4.3 Build and start frontend (second terminal)

In a **second terminal**:

```bash
cd examples/general-chat/frontend

# Install deps (uses pnpm)
pnpm install

# Dev server (hot-reload, proxies /awp → :8005)
pnpm dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

### Production build (optional)

```bash
pnpm build
# Outputs to frontend/dist/
```

Linux/macOS:

```bash
GENERAL_CHAT_STATIC_DIR=frontend/dist uvicorn server:app --port 8005
```

Windows (PowerShell):

```powershell
$env:GENERAL_CHAT_STATIC_DIR="frontend/dist"
uvicorn server:app --port 8005
```

---

## Supported source types

| Type | How to add |
|------|-----------|
| PDF | Upload via paperclip |
| Word (`.docx`, `.doc`) | Upload via paperclip |
| PowerPoint (`.pptx`, `.ppt`) | Upload via paperclip |
| Excel (`.xlsx`, `.xls`) | Upload via paperclip |
| Plain text / CSV / Markdown / JSON | Upload via paperclip |
| Website | Paste a URL in the Sources panel |
| Raw text | Paste directly in the Sources panel |

Max file size: 25 MB per source (override with `GENERAL_CHAT_MAX_SOURCE_BYTES`).

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/awp` | AG-UI SSE chat endpoint |
| `POST` | `/chat/upload` | Upload a source file |
| `GET` | `/chat/sources/discover?q=...` | Search the internet for candidate sources |
| `GET` | `/chat/sources/{thread_id}` | List sources for a session |
| `POST` | `/chat/sources/{thread_id}/url` | Add a URL source |
| `POST` | `/chat/sources/{thread_id}/text` | Add a plain-text source |
| `DELETE` | `/chat/sources/{thread_id}/{source_id}` | Delete a source |
| `GET` | `/sessions` | List chat sessions |
| `DELETE` | `/sessions/{session_id}` | Delete a session |
| `GET` | `/persona` | Inspect loaded persona |
| `GET` | `/skills` | Inspect loaded skills |
| `GET` | `/mcp/tools` | Inspect opt-in MCP tool adapters loaded into the chat agent |
| `GET` | `/mcp/catalogs` | List registered MCP servers and discovered tools |
| `POST` | `/mcp/catalogs/import` | Register pasted standard `mcpServers` JSON |

---

## Persona

The agent's identity is loaded from `soul/`:

```
soul/
├── SOUL.md    # Who the agent is
├── STYLE.md   # How it responds
└── AGENTS.md  # Behavioural rules
```

Edit these files to change the agent's personality without touching code.

---

## MCP tool testing

General Chat is tool-free by default so uploaded PDF, Word, and PowerPoint text
is answered from the injected chat context. To test MCP tools through the chat
agent, enable the opt-in MCP mode:

```powershell
$env:GENERAL_CHAT_MCP_ENABLED="1"
$env:GENERAL_CHAT_MCP_MODE="local"
$env:GENERAL_CHAT_MCP_CONFIG="mcp/openbench-mcp.yaml"
uvicorn server:app --port 8005 --reload
```

Then verify:

```powershell
Invoke-RestMethod http://localhost:8005/mcp/tools
```

For a complete walkthrough, see [MCP_TUTORIAL.md](MCP_TUTORIAL.md).

The MCP Servers panel also accepts standard MCP client JSON:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp/playwright"]
    }
  }
}
```

After registration, load tools from the server, toggle the server or individual
tools, and ask chat questions that use the enabled MCP tools.

### Image Search MCP

General Chat can also load the local Dockerized DINOv3 CIFAR-10 image search
MCP server. First build the image-search container from the repo root:

```powershell
docker compose -f examples\image-search-mcp\docker-compose.yml --profile cpu build
```

Make sure Hugging Face access is available on the host:

```powershell
hf auth login
```

Then start General Chat with the image-search MCP config:

```powershell
cd examples/general-chat
.\scripts\run_with_image_search_mcp.ps1
```

Verify the image-search tools are loaded:

```powershell
Invoke-RestMethod http://localhost:8005/mcp/tools
```

Expected namespaced tools include:

```text
image_search.list_index_stats
image_search.index_images
image_search.search_similar_images
image_search.rebuild_index
```

In the UI, use explicit tool-forcing prompts:

```text
Use the image_search MCP tool to list the image index stats.
```

```text
Use the image_search MCP tools to index 16 CIFAR-10 training images with batch size 4, then search similar images for CIFAR-10 test image index 0 and return the top 3 results with image ids, labels, and similarity scores.
```

You can also upload a random `.png`, `.jpg`, `.jpeg`, or `.webp` image in the
Sources panel and ask:

```text
Use the uploaded image source with image_search.search_similar_images. Index 16 CIFAR-10 training images with batch size 4 if needed, then return the top 3 similar images with visible thumbnails, image ids, labels, and similarity scores.
```

---

## Troubleshooting

**`GOOGLE_API_KEY` error on startup**
Set the key in `.env` or export it before running uvicorn.

Linux/macOS:
```bash
export GOOGLE_API_KEY=YOUR_KEY_HERE
uvicorn server:app --port 8005 --reload
```

Windows (PowerShell):
```powershell
$env:GOOGLE_API_KEY="YOUR_KEY_HERE"
uvicorn server:app --port 8005 --reload
```

**Internet search returns a configuration warning**
Set `TAVILY_API_KEY` in `.env` to enable source discovery search.

Linux/macOS:
```bash
export TAVILY_API_KEY=YOUR_KEY_HERE
uvicorn server:app --port 8005 --reload
```

Windows (PowerShell):
```powershell
$env:TAVILY_API_KEY="YOUR_KEY_HERE"
uvicorn server:app --port 8005 --reload
```

**`docling` install takes a long time**
Docling downloads ML models on first run. This is normal; subsequent starts
are fast.

**`pnpm: command not found`**
Install pnpm:
- `npm install -g pnpm`, or
- `corepack enable` then `corepack prepare pnpm@latest --activate`

**Port already in use**
Use `openbench demo run general-chat --port 8006`.
If running manually, change backend port and update `frontend/vite.config.ts`
proxy target to match.

**Frontend can't reach the backend**
Ensure the backend is on `:8005` and the Vite dev proxy points there.
Check `frontend/vite.config.ts` for the proxy config.
