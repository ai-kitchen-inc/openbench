# LCA Compliance Checker

Full-stack example demonstrating OpenBench as intelligence + orchestration layer for **ISO 14040/14044 LCA compliance** automation.

## What It Does

An AI assistant that validates Life Cycle Assessment (LCA) studies against:

- **ISO 14040/14044** — International LCA standard ("shall" requirements)
- **PCR (Product Category Rules)** — Industry-specific requirements (construction, packaging, electronics, food/beverage)
- **Pedoman LCA KLH Indonesia** — Indonesian regulatory requirements (grid emission factor, SNI alignment, local databases)

## Architecture

```
Frontend (React + @openbench/chat-ui)
    ↕ AG-UI SSE + REST
Backend (FastAPI)
    ↕
LCA Agent (BaseAgent + 19 tools)
    ↕
LCA Engine (pure calculations, no OpenBench imports)
```

## Features

| Feature | Description |
|---------|-------------|
| **19 domain tools** | ISO compliance, PCR checks, data quality, benchmarking, document analysis |
| **Rich UI** | A2UI tables, charts, callouts, forms via AG-UI streaming |
| **Task planning** | Complex reviews decomposed into steps automatically |
| **Parallel tools** | Multiple compliance checks run concurrently |
| **Persistent memory** | Conversation history survives server restarts (SQLite) |
| **Document upload** | Upload LCA reports for analysis and review |
| **PDF reports** | Generate compliance reports as downloadable PDFs |

## Quick Start

```bash
# 1. Install dependencies
make install

# 2. Set API key
export GOOGLE_API_KEY=your-key-here

# 3. Run both server + frontend
make dev
```

Server runs on port **8002**, frontend on port **5173** (proxied).

## Sample Queries

| Query | What Happens |
|-------|-------------|
| "Check ISO 14044 compliance for LCA-2024-001" | Full ISO compliance table + callout |
| "Compare impact results with packaging benchmarks" | Bar chart + percentile table |
| "Review company CP-001 compliance status" | Company profile + LCA study overview |
| "What are PCR requirements for construction?" | PCR template reference callout |
| "Check data quality for LCA-2024-003" | Pedigree matrix table + quality rating |
| "Run full compliance review for LCA-2024-002" | Multi-step: ISO + PCR + KLH + benchmarks |
| "Generate compliance report for LCA-2024-001" | PDF report download |

## Mock Data

### Companies

| ID | Company | Industry | Compliance Level |
|----|---------|----------|-----------------|
| CP-001 | PT Green Packaging Indonesia | Packaging | Good (all phases, critical review) |
| CP-002 | PT Beton Nusantara | Construction | Partial (missing interpretation) |
| CP-003 | PT Elektronik Maju | Electronics | Poor (missing LCIA, poor data quality) |

### LCA Studies

| ID | Product | Phases | Impact Categories |
|----|---------|--------|------------------|
| LCA-2024-001 | Corrugated cardboard box | All 4 | 6 (GWP, AP, EP, POCP, ODP, ADP) |
| LCA-2024-002 | Ready-mix concrete C30 | 3 of 4 | 6 (GWP, AP, EP, POCP, ODP, ADP) |
| LCA-2024-003 | USB-C charger 20W | 2 of 4 | 1 (GWP only) |

## File Structure

```
examples/lca-checker/
├── lca_engine.py          # Pure calculation functions (no OpenBench imports)
├── standards_data.py      # ISO 14040/44 + PCR + Pedoman KLH requirements
├── mock_data.py           # Company profiles, LCA studies, benchmarks
├── schemas.py             # 19 tool schemas (OpenAI function-calling format)
├── prompt.py              # System prompt with tool-first rendering
├── lca_agent.py           # Agent factory + 19 tool functions + ContextVar isolation
├── server.py              # FastAPI server + action handlers
├── Makefile               # Dev commands
├── sample_files/          # Sample documents for upload testing
│   ├── sample_lca_report.txt
│   └── sample_company_profile.txt
└── frontend/              # React app
    ├── src/App.tsx
    ├── src/main.tsx
    ├── src/global.css
    ├── index.html
    ├── package.json
    ├── vite.config.ts
    └── tsconfig.json
```

## Tools Reference

| # | Group | Tool | Description |
|---|-------|------|-------------|
| 1 | ISO | `check_goal_scope` | Check Goal & Scope (ISO 14044 4.2) |
| 2 | ISO | `check_lci` | Check LCI (ISO 14044 4.3) |
| 3 | ISO | `check_lcia` | Check LCIA (ISO 14044 4.4) |
| 4 | ISO | `check_interpretation` | Check Interpretation (ISO 14044 4.5) |
| 5 | ISO | `check_full_iso_compliance` | All phases at once |
| 6 | PCR | `check_pcr_compliance` | PCR-specific requirements |
| 7 | PCR | `list_pcr_categories` | List available PCR templates |
| 8 | KLH | `check_klh_compliance` | Pedoman KLH Indonesia |
| 9 | Quality | `assess_data_quality` | Pedigree matrix scoring |
| 10 | Benchmark | `compare_benchmarks` | Industry EPD comparison |
| 11 | Lookup | `lookup_company_profile` | Company profile by ID |
| 12 | Lookup | `lookup_lca_study` | LCA study data by ID |
| 13 | Reference | `lookup_standard_reference` | ISO/PCR/KLH text lookup |
| 14 | Document | `analyze_document` | Read uploaded files |
| 15 | Review | `create_compliance_review_form` | Interactive review form |
| 16 | Report | `generate_compliance_report` | PDF report generation |
| 17 | Visual | `create_chart` | Bar/line/pie charts |
| 18 | Visual | `create_table` | Structured tables |
| 19 | Visual | `create_callout` | Status callouts |

## Anti-Hallucination Design

- Recommendations are **hints with citations** (e.g., "per ISO 14044 Section 4.2.3.2"), never fabricated compliance status
- All compliance checks reference specific ISO section numbers
- Data quality scoring uses established pedigree matrix methodology
- Benchmark comparisons cite EPD database sources
