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
| `OPENBENCH_AUTH_DISABLED` | `1` | Disable auth (keep `1` for local dev) |

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
`openpyxl`, and the other deps listed in `pyproject.toml`.

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
| `GET` | `/chat/sources/{thread_id}` | List sources for a session |
| `POST` | `/chat/sources/{thread_id}/url` | Add a URL source |
| `POST` | `/chat/sources/{thread_id}/text` | Add a plain-text source |
| `DELETE` | `/chat/sources/{thread_id}/{source_id}` | Delete a source |
| `GET` | `/sessions` | List chat sessions |
| `DELETE` | `/sessions/{session_id}` | Delete a session |
| `GET` | `/persona` | Inspect loaded persona |
| `GET` | `/skills` | Inspect loaded skills |

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
