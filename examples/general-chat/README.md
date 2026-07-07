# General Chat

A full-stack general-purpose chat demo built on OpenBench. You can optionally
add PDFs, Word docs, PowerPoint slides, spreadsheets, URLs, text, or images as
context while still asking normal chat questions. Uploaded images are analyzed
through OpenBench's VLM layer before the text agent answers, so the same chat
can describe general images or read visible vehicle plate numbers.

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

## 1 â€” Install OpenBench (parent package)

From the **repo root** (`openbench/`):

```bash
pip install -e ".[all]"
```

This installs the `openbench` SDK that the server imports.

---

## 2 â€” Configure environment

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

Dashboard generation from CSV/XLSX works with the built-in local renderer. If
you have a Stitch endpoint, you can also set:

```dotenv
DASHBOARD_RENDER_ADAPTER=auto
STITCH_API_KEY=YOUR_STITCH_KEY_HERE
STITCH_API_URL=https://stitch.googleapis.com/mcp
# Optional: reuse an existing project instead of creating one per dashboard.
STITCH_PROJECT_ID=
```

The other variables in `.env` are optional overrides:

| Variable | Default | Purpose |
|----------|---------|---------|
| `GENERAL_CHAT_MODEL` | `gemini-3-flash-preview` | Gemini model to use |
| `GENERAL_CHAT_VLM_ENABLED` | `1` | Enable VLM analysis for uploaded images |
| `GENERAL_CHAT_VLM_MODEL` | `gemini-2.5-flash` | Vision model: `gemini-2.5-flash`, `gemma-2b`, `gemma-4b`, or a raw model id |
| `GENERAL_CHAT_VLM_PROVIDER` | inferred | Optional override: `gemini` or `ollama` |
| `GENERAL_CHAT_VLM_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible endpoint for local Gemma/Ollama VLM calls |
| `GENERAL_CHAT_VLM_TEMPERATURE` | `0.2` | VLM sampling temperature |
| `GENERAL_CHAT_VLM_MAX_OUTPUT_TOKENS` | `2048` | Max visual-analysis output tokens |
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
| `GENERAL_CHAT_MCP_REGISTRY_ENABLED` | `1` | Set to `0` for dedicated single-server demo scripts so saved registry servers are ignored |
| `DASHBOARD_RENDER_ADAPTER` | `auto` | Dashboard presentation adapter: `auto`, `default`, or `stitch` |
| `STITCH_API_KEY` | unset | Optional Stitch credential for dashboard HTML generation |
| `STITCH_API_URL` | unset | Optional Stitch endpoint; `https://stitch.googleapis.com/mcp` uses MCP mode |
| `STITCH_API_MODE` | auto | Optional `mcp` or `direct`; `/mcp` URLs are detected automatically |
| `STITCH_PROJECT_ID` | unset | Optional existing Stitch project id to reuse |

---

## 3 â€” Start with OpenBench demo runner (recommended)

```bash
openbench demo run general-chat
```

What this does:

- Starts backend (`uvicorn`) for `examples/general-chat/server.py`
- Starts frontend dev server if `frontend/package.json` exists
- Auto-installs Python deps for the demo when needed
- Auto-installs/builds `studio/chat-ui` when needed
- Starts as the base MCP-free chat demo, ignoring optional MCP settings saved
  in `.env` or `.openbench`

MCP-enabled demos remain available through dedicated commands such as
`openbench demo run general-chat-dashboard-generator`,
`openbench demo run general-chat-image-search` and
`openbench demo run general-chat-sam-segmentation`, or by starting the backend
manually with explicit `GENERAL_CHAT_MCP_*` environment variables.

To launch one session with every bundled General Chat MCP integration registered
together, use either command below:

```bash
openbench demo run general-chat --all-mcp
# or
openbench demo run general-chat-all
```

This all-MCP launcher keeps General Chat in registry mode, seeds the MCP Servers
registry with dashboard generator, filesystem, generic API, image-search, SAM
segmentation, Docker MCP Gateway, and internal OpenBench tools, then imports any
currently running ToolHive workloads. It does not start ToolHive workloads for
you; start them in ToolHive first if you want ToolHive tools available in the
same chat session.

The all-MCP launcher uses an isolated registry under `.openbench/all-mcp`.
Existing servers saved through the regular General Chat MCP UI stay available to
`openbench demo run general-chat`, but stopped or stale entries from that default
registry are not loaded by `general-chat-all`.

Dashboard-specific MCP test:

```bash
openbench demo run general-chat-dashboard-generator
```

This starts General Chat with only the standardized
`mcp/dashboard-generator-mcp` server enabled. The legacy SDK dashboard skill is
disabled for that run, so a successful dashboard proves the MCP path is working.
After upload, ask `buatkan dashboard dari data ini`; the progress should move
from `dashboard_generator_extract_metadata` to aggregation and then
`dashboard_generator_generate_dashboard`.

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

## 4 â€” Manual startup (fallback)

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

# Dev server (hot-reload, proxies /awp â†’ :8005)
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
| CSV / Excel (`.csv`, `.xlsx`, `.xls`) | Upload via paperclip; dashboard-ready |
| Plain text / Markdown / JSON | Upload via paperclip |
| Image (`.png`, `.jpg`, `.jpeg`, `.webp`) | Upload via paperclip; VLM-ready |
| Website | Paste a URL in the Sources panel |
| Raw text | Paste directly in the Sources panel |

Max file size: 25 MB per source (override with `GENERAL_CHAT_MAX_SOURCE_BYTES`).

---

## Image understanding and plate reading

General Chat configures an OpenBench VLM provider at startup. The default is
Gemini 2.5 Flash through the Gemini API:

```dotenv
GENERAL_CHAT_VLM_ENABLED=1
GENERAL_CHAT_VLM_MODEL=gemini-2.5-flash
GOOGLE_API_KEY=YOUR_KEY_HERE
```

To use your local Ollama Gemma models instead:

```powershell
# 2B model
$env:GENERAL_CHAT_VLM_MODEL="gemma-2b"

# or 4B model
$env:GENERAL_CHAT_VLM_MODEL="gemma-4b"

# default Ollama OpenAI-compatible endpoint
$env:GENERAL_CHAT_VLM_BASE_URL="http://localhost:11434/v1"
```

`gemma-2b` resolves to Ollama model `gemma4:e2b`, and `gemma-4b` resolves to
`gemma4:e4b`. `GENERAL_CHAT_VLM_BASE_URL` is only used for the local
Ollama/Gemma provider; Gemini continues to use the Google Gemini API.

The aliases map to the downloaded Ollama model names:

| Env value | Provider | Model sent to provider |
|-----------|----------|------------------------|
| `gemini-2.5-flash` | Gemini API | `gemini-2.5-flash` |
| `gemma-2b` | Ollama/OpenAI-compatible | `gemma4:e2b` |
| `gemma-4b` | Ollama/OpenAI-compatible | `gemma4:e4b` |

When an image source is attached, the server runs `VisionAgent` first and adds a
`visual-observations.md` context attachment for the main chat agent. The
VisionAgent loads only the `vehicle-plate-reading` skill as a domain prompt,
so plate-number requests get a structured result while normal image questions
stay general.

Try prompts like:

```text
gambar ini tentang apa?
```

```text
baca plat nomor kendaraan pada gambar ini
```

For plate tasks, the expected answer separates `plate_text`, `confidence`,
`evidence`, and `uncertainty`. If the plate is not readable, the agent should
say that no readable plate is visible instead of guessing.

---

## Dashboard generator

General Chat loads the OpenBench `dashboard-generator` SDK skill by default, and
the same tools are also available as the standardized
`mcp/dashboard-generator-mcp` server. Upload a CSV/XLSX file, then ask something
like:

```text
buatkan dashboard dari data ini
```

The agent follows the dashboard SOP from the skill:

1. Read file metadata with `extract_metadata`.
2. Write read-only SQLite SQL queries against table `data`.
3. Run `aggregate_data` with the SQL query.
4. Build a declarative ViewModel (A2UI-style JSON, not raw UI code).
5. Render the artifact with `generate_dashboard`.

Spreadsheet rows are not pasted into the LLM prompt. General Chat passes only
the local file path and dashboard SOP to the agent; the skill tools inspect
metadata and run aggregations from the file.

Users may also upload their own dashboard template. `.html` / `.htm` files and
markdown design briefs named like `design.md` or `dashboard-template.md` are
stored as dashboard template sources. When the user asks to use one, the agent
passes the uploaded `Dashboard template path` to `generate_dashboard` as
`template_path`. If no template is uploaded or requested, the existing
default/Stitch adapter selection is unchanged. Sample upload templates live in
`template-dashboard-sample/`.

The result appears as a chat link and in the right-side dashboard artifact
window. Generated HTML files are written to `downloads/` and served from
`/downloads/...`.

To test the standalone MCP version only:

```powershell
cd examples\general-chat
.\scripts\run_with_dashboard_generator_mcp.ps1
```

This starts General Chat with `GENERAL_CHAT_DASHBOARD_SKILL_ENABLED=0`, loads
`mcp/dashboard-generator-mcp` over stdio, and exposes these provider-safe tools
to the agent:

- `dashboard_generator_extract_metadata`
- `dashboard_generator_aggregate_data`
- `dashboard_generator_generate_dashboard`

In the web UI, open the MCP Servers panel, confirm the `dashboard_generator`
server/tools are loaded if you are using registry mode, upload the spreadsheet
through the paperclip/Sources area, then ask `buatkan dashboard dari data ini`.
The dashboard should appear in the right-side artifact panel.

Dashboard rendering uses the OpenBench dashboard adapter layer. By default,
`DASHBOARD_RENDER_ADAPTER=auto` uses Stitch when a Stitch key is configured and
falls back to the built-in `DashboardGenerator`; set it to `default` to force
the local renderer or `stitch` to force the Stitch adapter path.

For `https://stitch.googleapis.com/mcp`, OpenBench uses the Stitch MCP flow:
`tools/list`, `create_project` (unless `STITCH_PROJECT_ID` is set), and
`generate_screen_from_text`. A successful MCP response is treated as Stitch
usage even when the response contains project/screen metadata instead of raw
HTML.

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

## Chat-based CIFAR-10 image search through MCP

General Chat can render CIFAR-10 visual similarity results directly in the chat
surface. Upload a `.png`, `.jpg`, `.jpeg`, or `.webp` source, then ask for the
top-k similar CIFAR-10 images. The chat agent calls
`image_search.search_similar_images` with the uploaded image MCP path, the MCP
server searches its persisted CIFAR-10 vector index, and the backend renders the
returned preview URLs with rank, label, score, and image id. The browser never
loads or searches the full CIFAR-10 dataset.

Recommended local startup:

```powershell
cd mcp\image-search-mcp
docker compose --profile cpu build

cd ..\general-chat
.\scripts\run_with_image_search_mcp.ps1
```

The first full indexing run may download CIFAR-10 via `torchvision` and DINOv3
weights via Hugging Face. Preview PNGs are written under
`mcp/image-search-mcp/data/previews` and served by the General Chat backend
at `/image-search/previews/...`.
The image-search MCP service can search any initialized non-empty index. Verify
`image_search.list_index_stats` reports `healthy=true`; partial indexes report
`complete=false` and `partial=true`, while the full index reports
`active_count=60000`, `train_count=50000`, `test_count=10000`, and
`complete=true`. Full indexing improves coverage and should be run outside the
live chat turn:

```powershell
cd mcp\image-search-mcp
$env:VECTOR_BACKEND="hnswlib"
$env:IMAGE_SEARCH_PROGRESS="1"
python -c "from app.service import get_service; print(get_service().rebuild_index(batch_size=64))"
python -c "from app.service import get_service; print(get_service().list_index_stats())"
```

---

## Persona

The agent's identity is loaded from `soul/`:

```
soul/
â”œâ”€â”€ SOUL.md    # Who the agent is
â”œâ”€â”€ STYLE.md   # How it responds
â””â”€â”€ AGENTS.md  # Behavioural rules
```

Edit these files to change the agent's personality without touching code.

---

## MCP tool testing

General Chat is tool-free by default. Uploaded files and sources remain optional
context for the chat agent. To test MCP tools through the chat agent, enable the
opt-in MCP mode:

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

To test all bundled MCP integrations in one run:

```powershell
openbench demo run general-chat-all
```

Then inspect:

```powershell
Invoke-RestMethod http://localhost:8005/mcp/tools
```

Expected `namespaced_tool_names` include the internal OpenBench query tools and,
when dependencies are available, tools from `dashboard_generator`, `filesystem`,
`generic_api`, `image_search`, `sam_segmentation`, Docker MCP Gateway, and any
running ToolHive workloads.
Optional services that are missing or not built remain visible through
`/mcp/catalogs` and `/mcp/tools` diagnostics rather than being silently hidden.
`general-chat-all` uses the isolated `examples/general-chat/.openbench/all-mcp`
registry root, so stale default-registry servers from normal General Chat runs
are not loaded.

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

For custom Docker imports, Docker `env` values are safe whether you paste them
in JSON or enter them with the **Docker env** key/value fields. Literal values
are encrypted before `servers.json` is saved, redacted in the UI, and decrypted
only when OpenBench starts the MCP server. For example, you can paste:

```json
{
  "mcpServers": {
    "grafana": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-e",
        "GRAFANA_URL",
        "-e",
        "GRAFANA_API_KEY",
        "mcp/grafana",
        "--transport=stdio"
      ],
      "env": {
        "GRAFANA_URL": "http://localhost:3000",
        "GRAFANA_API_KEY": "<your service account token>"
      }
    }
  }
}
```

You can also leave `env` out of the JSON and add rows such as
`GRAFANA_URL=http://localhost:3000` and `GRAFANA_API_KEY=<token>` in the Docker
env table. Manual rows are applied to Docker servers and override same-name JSON
env values. Advanced configs may still reference reusable managed values with
`${secret:KEY}`.

To avoid storing a value in OpenBench at all, reference your local environment
and start General Chat with the env var set locally:

```powershell
$env:GRAFANA_API_KEY="your_service_account_token"
openbench demo run general-chat
```

After registration, load tools from the server, toggle the server or individual
tools, and ask chat questions that use the enabled MCP tools.

### Image Search MCP

General Chat can also load the local Dockerized DINOv3 CIFAR-10 image search
MCP server. First build the image-search container from the repo root:

```powershell
docker compose -f mcp\image-search-mcp\docker-compose.yml --profile cpu build
```

Make sure Hugging Face access is available on the host:

```powershell
hf auth login
```

Then start General Chat with the image-search MCP config:

```powershell
openbench demo run general-chat-image-search
```

For combined testing with SAM, generic API, Docker MCP Gateway, filesystem MCP,
internal OpenBench tools, and running ToolHive workloads, use
`openbench demo run general-chat --all-mcp` instead.

The older PowerShell helper remains available at
`examples/general-chat/scripts/run_with_image_search_mcp.ps1` if you need to
set the environment manually.

Verify the image-search tools are loaded:

```powershell
Invoke-RestMethod http://localhost:8005/mcp/tools
```

Expected namespaced tools include:

```text
image_search.list_index_stats
image_search.search_similar_images
```

If `image_search` reports `Connection closed`, the Docker stdio process exited
before MCP handshake. Rebuild or inspect the image and run the standalone smoke
test to see container startup errors:

```powershell
docker image inspect openbench/image-search-mcp:cpu
python mcp\image-search-mcp\scripts\test_mcp_server.py --mode docker
```

In the UI, use explicit tool-forcing prompts:

```text
Use the image_search MCP tool to list the image index stats.
```

```text
Use image_search.list_index_stats to verify the CIFAR-10 index is healthy, then use image_search.search_similar_images for CIFAR-10 test image index 0 and return the top 3 results with image ids, labels, splits, dataset indexes, and similarity scores. If the index is partial, mention that coverage is partial.
```

You can also upload a random `.png`, `.jpg`, `.jpeg`, or `.webp` image in the
Sources panel and ask:

```text
Use the uploaded image source with image_search.search_similar_images. If the index is empty or uninitialized, tell me to build it outside chat; otherwise return the top 3 similar images with visible thumbnails, image ids, labels, splits, dataset indexes, and similarity scores. If the index is partial, mention that coverage is partial.
```

### SAM 3 Concept Counting MCP

General Chat can also load the local Dockerized Ultralytics SAM 3 MCP server.
It counts objects matching a text concept such as `dog`, `person`, `red apple`,
or `yellow school bus`. It is SAM 3 only and does not support SAM 1, SAM 2,
FastSAM, or MobileSAM fallbacks.

Ultralytics does not auto-download `sam3.pt`, and the official weights are gated
on Hugging Face. After receiving access, either place `sam3.pt` at
`mcp/sam-segmentation-mcp/weights/sam3.pt` or set `HF_TOKEN` so Docker
Compose can download the weights during build. Then build the container from the
repo root:

```powershell
$env:HF_TOKEN="hf_..."   # optional if weights/sam3.pt already exists
docker compose -f mcp\sam-segmentation-mcp\docker-compose.yml --profile cpu build
```

If you already ran `hf auth login`, you can use the helper script instead:

```powershell
mcp\sam-segmentation-mcp\scripts\build_with_sam3.ps1
```

The compose build defaults `SAM3_PREINSTALL=required`, so it fails early if the
weights cannot be copied or downloaded. The General Chat MCP config uses the
weights baked into `openbench/sam-segmentation-mcp:cpu` at `/models/sam3.pt`.

Start General Chat with the SAM 3 MCP config:

```powershell
openbench demo run general-chat-sam-segmentation
```

For combined testing with image search, generic API, Docker MCP Gateway,
filesystem MCP, internal OpenBench tools, and running ToolHive workloads, use
`openbench demo run general-chat --all-mcp` instead.

SAM debug images are written under `examples/general-chat/uploads/_sam_debug`
and are returned by the tool as `/uploads/_sam_debug/...` URLs when detections
are available.

The older PowerShell helper remains available at
`examples/general-chat/scripts/run_with_sam_segmentation_mcp.ps1` if you need to
set the environment manually.

Verify the tool is loaded:

```powershell
Invoke-RestMethod http://localhost:8005/mcp/tools
```

Expected namespaced tools include:

```text
sam_segmentation.count_objects_with_sam3
```

Successful SAM count results include a `count`; General Chat should answer from
that value after one call for the same image/concept. `service_info` and
filesystem MCP tools are diagnostics only. Uploaded image paths under
`/general-chat/uploads/...` are mounted for the image MCP containers and are not
inside the filesystem MCP sandbox unless you explicitly change that sandbox.

Upload a `.png`, `.jpg`, `.jpeg`, or `.webp` image in the Sources panel and ask:

```text
How many dogs are in this image? Use the SAM 3 counting tool.
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
