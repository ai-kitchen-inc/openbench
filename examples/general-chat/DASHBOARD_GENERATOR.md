# General Chat Dashboard Generator

General Chat can generate dashboards from uploaded CSV/XLSX files using the
OpenBench `dashboard-generator` SDK skill or the standardized
`mcp/dashboard-generator-mcp` standalone server.

## User Flow

1. Open General Chat.
2. Upload a `.csv` or `.xlsx` file in the Sources panel.
3. Optionally upload a dashboard template: `.html`, `.htm`, or a markdown
   design brief named like `design.md` / `dashboard-template.md`.
4. Ask: `buatkan dashboard dari data ini` or
   `buatkan dashboard dari data ini pakai template yang saya upload`.
5. The agent calls:
   - `extract_metadata`
   - `aggregate_data` with read-only SQLite SQL
   - `generate_dashboard`, with `template_path=...` when an uploaded template
     source is present and requested
6. The dashboard appears as a link in chat and as a side-by-side A2UI artifact
   panel.

For an MCP-only test run, start General Chat with:

```powershell
openbench demo run general-chat-dashboard-generator
```

That run disables the default SDK dashboard skill and loads the MCP tools as
`dashboard_generator.extract_metadata`, `dashboard_generator.aggregate_data`,
and `dashboard_generator.generate_dashboard`.

Equivalent manual fallback:

```powershell
cd examples\general-chat
.\scripts\run_with_dashboard_generator_mcp.ps1
```

## Runtime Files

Generated dashboards are written to `examples/general-chat/downloads/` by
default and served from `/downloads/...`.

CSV/XLSX source uploads are kept after a chat turn so the user can upload first
and request a dashboard later. They are removed when the source, source list, or
session is deleted.

Dashboard template uploads are also kept after a chat turn. The source context
exposes `Dashboard template path:` so both SDK and MCP dashboard tools can read
the user-provided template directly.

## Environment

Required:

```dotenv
GOOGLE_API_KEY=...
```

Optional:

```dotenv
DASHBOARD_RENDER_ADAPTER=auto
STITCH_API_KEY=...
STITCH_API_URL=https://stitch.googleapis.com/mcp
STITCH_PROJECT_ID=
GENERAL_CHAT_DOWNLOAD_DIR=downloads
```

When `STITCH_API_URL` is absent, OpenBench uses the local dashboard HTML
renderer.

## Adapter Layer

The dashboard skill separates agentic planning from presentation rendering:

```text
Dashboard(StitchAdapter(A2UI(AgenticCore(LLM, (Skills, MCP)))))
```

General Chat lets OpenBench select the adapter through
`DASHBOARD_RENDER_ADAPTER`:

- `auto`: use Stitch when configured, otherwise local fallback
- `default`: force the built-in `DashboardGenerator`
- `stitch`: force the Stitch adapter path, with local fallback on failure

`https://stitch.googleapis.com/mcp` is an MCP JSON-RPC endpoint. The adapter
uses `tools/list`, `create_project`, and `generate_screen_from_text`; it does
not expect the first response to contain HTML.

## Run

From the repo root:

```bash
pip install -e ".[all]"
openbench demo run general-chat
```

Run mode differences:

- `openbench demo run general-chat`: base General Chat. Dashboard generation
  uses the bundled SDK skill by default. MCP registry remains available in the
  UI, but no dedicated dashboard MCP server is forced on.
- `openbench demo run general-chat-dashboard-generator`: MCP-only dashboard
  test. It disables the SDK dashboard skill and exposes only
  `dashboard_generator.extract_metadata`, `dashboard_generator.aggregate_data`,
  and `dashboard_generator.generate_dashboard`.
- `openbench demo run general-chat-all`: registry-mode General Chat with all
  bundled MCP integrations seeded together, including dashboard generator plus
  the other MCP demos when their dependencies are available.

In the browser, use the same testing flow for all three modes: open the frontend
URL printed by the demo runner, click the Sources/upload control, choose the
CSV/XLSX file, wait until the source status is ready, then ask
`buatkan dashboard dari data ini`.

For template testing, use the sample files in
`examples/general-chat/template-dashboard-sample/`: upload `design.md` or
`template.html` with your spreadsheet, then ask for a dashboard using the
uploaded template.

Expected MCP progress for the dedicated dashboard run:

```text
Running dashboard_generator_extract_metadata
Running dashboard_generator_aggregate_data
Running dashboard_generator_generate_dashboard
```

If `extract_metadata` repeats until timeout, check the backend log. The
dashboard MCP loader keeps the stdio server alive across calls so Windows stdio
cleanup cannot consume the tool timeout, and Gemini replay now keeps the
original raw function-call parts when SDK argument containers normalize to the
same JSON as the parsed tool call.

When retesting after a failed run, start a new chat session or clear the old
session. General Chat sanitizes persisted unsafe tool exchanges, but a fresh
session makes it easier to confirm that the new metadata -> aggregate -> render
chain is the one being exercised.

Manual fallback:

```bash
cd examples/general-chat
pip install -e .
uvicorn server:app --port 8005 --reload --reload-dir src
```

In a second terminal:

```bash
cd examples/general-chat/frontend
pnpm install
pnpm dev
```

Open `http://localhost:5173`.
