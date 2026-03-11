# LCI Ignite X

AI-powered Life Cycle Assessment (LCA) analysis platform built on the [OpenBench](../../README.md) SDK.

Helps LCA consultants analyze Life Cycle Inventory data for PROPER 2025 submissions.

## Features

- Parse easyLCA and SimaPro CSV files
- Build Input-Output tables with category aggregation
- Identify environmental hotspots (Pareto 80/20 analysis)
- Generate narrative reports with PROPER 2025 references
- Export analysis to .docx format
- Persistent conversation memory per session

## Prerequisites

- Python >= 3.10
- Node.js >= 18
- pnpm (`npm install -g pnpm`)
- Google Gemini API key

## Quick Start

```bash
# 1. Clone the repository
git clone -b feat/lci-ignite-x https://github.com/ai-kitchen-inc/openbench.git
cd openbench

# 2. Install OpenBench SDK
pip install -e .

# 3. Configure environment
cp examples/lci-ignite-x/.env.example examples/lci-ignite-x/.env
# Edit .env and set your GOOGLE_API_KEY

# 4. Run
openbench demo run lci-ignite-x
```

This single command will:
- Install lci-ignite-x Python dependencies (`pip install -e .`)
- Build @openbench/chat-ui if not already built (`pnpm install && pnpm build`)
- Start the backend on http://localhost:8003
- Start the frontend on http://localhost:5173

Open http://localhost:5173 and upload your easyLCA or SimaPro CSV file.

## Architecture

```
Frontend (React)           Backend (FastAPI)           Intelligence
@openbench/chat-ui    -->  AG-UI SSE (/awp)      -->  Coordinator Agent
                           REST (/chat/action)         |-- IO Table tools
                           Upload (/chat/upload)        |-- Hotspot tools
                                                        |-- Narrative tools
                                                        |-- Export tools
```

The coordinator agent dispatches to 11 domain tools that produce A2UI render items (charts, tables, callouts, markdown) streamed to the frontend via AG-UI protocol.

## Sample Data

`docs/input.xlsx` contains a PHM (Pertamina Hulu Mahakam) oil & gas LCA dataset with 33 sheets covering 5 operational areas (BSP, SPU, NPU, CPU, CPA).

`docs/input_easylca.csv` is the pre-converted easyLCA format ready for upload.

See [CLAUDE.md](CLAUDE.md) for detailed project structure and patterns.
