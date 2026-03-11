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

Install the following tools if you don't have them yet.

### 1. Git

| OS | Install |
|----|---------|
| **macOS** | Open Terminal, run `xcode-select --install` |
| **Windows** | Download from [git-scm.com](https://git-scm.com/download/win), run installer (use default settings) |

Verify: `git --version`

### 2. Python (>= 3.10)

| OS | Install |
|----|---------|
| **macOS** | Download from [python.org](https://www.python.org/downloads/) or `brew install python@3.12` |
| **Windows** | Download from [python.org](https://www.python.org/downloads/), check "Add Python to PATH" during install |

Verify: `python3 --version` (macOS) or `python --version` (Windows)

### 3. Node.js (>= 18)

| OS | Install |
|----|---------|
| **macOS** | Download from [nodejs.org](https://nodejs.org/) (LTS) or `brew install node` |
| **Windows** | Download from [nodejs.org](https://nodejs.org/) (LTS), run installer |

Verify: `node --version`

### 4. pnpm

After Node.js is installed:

```bash
npm install -g pnpm
```

Verify: `pnpm --version`

## Quick Start

Open **Terminal** (macOS) or **Command Prompt / PowerShell** (Windows):

```bash
# 1. Clone the repository
git clone -b feat/lci-ignite-x https://github.com/ai-kitchen-inc/openbench.git
cd openbench

# 2. Install OpenBench SDK
pip install -e .
```

Configure your API key:

**macOS / Linux:**
```bash
cp examples/lci-ignite-x/.env.example examples/lci-ignite-x/.env
```
Then open `examples/lci-ignite-x/.env` in a text editor and set your `GOOGLE_API_KEY`.

**Windows:**
```cmd
copy examples\lci-ignite-x\.env.example examples\lci-ignite-x\.env
```
Then open `examples\lci-ignite-x\.env` in Notepad and set your `GOOGLE_API_KEY`.

```bash
# 4. Run
openbench demo run lci-ignite-x
```

This single command will:
- Install lci-ignite-x Python dependencies automatically
- Build @openbench/chat-ui if not already built
- Start the backend on http://localhost:8003
- Start the frontend on http://localhost:5173

Open http://localhost:5173 in your browser and upload your easyLCA or SimaPro CSV file.

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

See [CLAUDE.md](CLAUDE.md) for detailed project structure and patterns.
