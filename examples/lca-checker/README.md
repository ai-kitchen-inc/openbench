# LCA Compliance Checker

Full-stack example demonstrating OpenBench as intelligence + orchestration layer for **ISO 14040/14044 LCA compliance** automation, with RAG-powered semantic search over standards and corporate sustainability reports.

## What It Does

An AI assistant that validates Life Cycle Assessment (LCA) studies against:

- **ISO 14040/14044** — International LCA standard ("shall" requirements)
- **PCR (Product Category Rules)** — Industry-specific requirements (construction, packaging, electronics, food/beverage)
- **Pedoman LCA KLH Indonesia** — Indonesian regulatory requirements (grid emission factor, SNI alignment, local databases)
- **Corporate sustainability reports** — Semantic search over indexed documents (e.g., PT Japfa Comfeed Indonesia Tbk SR 2024)

## Architecture

```
Frontend (React + @openbench/chat-ui)
    ↕ AG-UI SSE + REST
Backend (FastAPI)
    ↕
LCA Agent (BaseAgent + 22 tools)
    ├── 19 core tools (always available)
    └── 3 RAG tools (optional, Pinecone)
    ↕                          ↕
LCA Engine                 Pinecone Vector Store
(pure calculations)        ├── ns: lca-standards (51 docs)
                           └── ns: japfa (SR 2024)
```

## Features

| Feature | Description |
|---------|-------------|
| **22 domain tools** | 19 core + 3 RAG (semantic search over standards + documents) |
| **RAG search** | Semantic search over ISO/PCR/KLH standards and Japfa sustainability report |
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

## RAG Setup (Optional)

Enable semantic search over LCA standards and corporate sustainability reports using Pinecone vector store.

```bash
# 1. Install with RAG dependencies
make install-rag

# 2. Set API keys
export GOOGLE_API_KEY=your-google-key
export PINECONE_API_KEY=your-pinecone-key
export PINECONE_INDEX=openbench          # default: "openbench"

# 3. Run server (standards auto-indexed on first startup)
make dev
```

### Pinecone Index Structure

```
Index: openbench
├── namespace: lca-standards    → 51 pre-indexed standards documents (auto-indexed)
│   ├── ISO 14044 requirements (32 docs)
│   ├── PCR templates (4 docs)
│   ├── Pedoman KLH requirements (7 docs)
│   └── Impact categories (8 docs)
└── namespace: japfa            → PT Japfa Comfeed Indonesia SR 2024 (pre-indexed)
```

### RAG Tools

| Tool | Description |
|------|-------------|
| `search_standards` | Semantic search across ISO 14044, PCR, KLH, impact categories |
| `search_documents` | Search Japfa sustainability report and other indexed documents |
| `index_document` | Index uploaded files into vector store for search |

**Graceful degradation**: Without `PINECONE_API_KEY`, the server starts normally with 19 tools and no errors. RAG tools are simply not registered.

## Sample Queries

### Core Tools

| Query | What Happens |
|-------|-------------|
| "Check ISO 14044 compliance for LCA-2024-001" | Full ISO compliance table + callout |
| "Compare impact results with packaging benchmarks" | Bar chart + percentile table |
| "Review company CP-001 compliance status" | Company profile + LCA study overview |
| "What are PCR requirements for construction?" | PCR template reference callout |
| "Check data quality for LCA-2024-003" | Pedigree matrix table + quality rating |
| "Run full compliance review for LCA-2024-002" | Multi-step: ISO + PCR + KLH + benchmarks |
| "Generate compliance report for LCA-2024-001" | PDF report download |

### RAG Queries (requires Pinecone)

| Query | What Happens |
|-------|-------------|
| "What does ISO say about allocation procedures?" | `search_standards` across 51 standards docs |
| "Search standards for functional unit requirements" | `search_standards` with ISO filter |
| "How does Japfa implement LCA for aquaculture?" | `search_documents` in japfa namespace |
| "What is Japfa's Sustainability-Linked Bond commitment?" | `search_documents` — SLB section |
| "Search Japfa report for emission reduction targets" | `search_documents` — GHG emissions |
| "What are Japfa's water recycling initiatives?" | `search_documents` — water conservation |
| "How does Japfa address animal welfare?" | `search_documents` — animal welfare section |

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

### Japfa Sustainability Report 2024 (indexed in Pinecone)

Key topics available for RAG search:

| Topic | Content |
|-------|---------|
| LCA Budidaya Perairan | Cradle-to-grave LCA for aquaculture operations |
| Sustainability-Linked Bond | Water recycling facilities at 8 poultry units + 1 hatchery |
| Climate Scenario Analysis | CSA for climate risk and opportunity identification |
| JAPFA for Kids | Nutrition program — 762 children improved nutrition status |
| Water Conservation | Water recycling facilities, water efficiency targets |
| Emission Reduction | GHG emission management, energy efficiency practices |
| Animal Welfare | Penerapan kesejahteraan hewan across poultry and aquaculture |
| ESG Governance | SRI-KEHATI Index, FTSE Russell, Komite Keberlanjutan |
| JSRS | Japfa Sustainability Reporting System — data validation |

## File Structure

```
examples/lca-checker/
├── lca_engine.py          # Pure calculation functions (no OpenBench imports)
├── standards_data.py      # ISO 14040/44 + PCR + Pedoman KLH requirements
├── mock_data.py           # Company profiles, LCA studies, benchmarks
├── schemas.py             # 22 tool schemas (OpenAI function-calling format)
├── prompt.py              # System prompt with tool-first rendering
├── lca_agent.py           # Agent factory + 22 tool functions + ContextVar isolation
├── rag_setup.py           # RAG store builders + standards indexing (optional)
├── query_japfa_demo.py    # Standalone script to query japfa namespace
├── server.py              # FastAPI server + action handlers + RAG init
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
| 13 | Reference | `lookup_standard_reference` | ISO/PCR/KLH text lookup (exact key) |
| 14 | Document | `analyze_document` | Read uploaded files |
| 15 | Review | `create_compliance_review_form` | Interactive review form |
| 16 | Report | `generate_compliance_report` | PDF report generation |
| 17 | Visual | `create_chart` | Bar/line/pie charts |
| 18 | Visual | `create_table` | Structured tables |
| 19 | Visual | `create_callout` | Status callouts |
| 20 | RAG | `search_standards` | Semantic search across standards |
| 21 | RAG | `search_documents` | Search Japfa SR and indexed documents |
| 22 | RAG | `index_document` | Index uploaded files for search |

## Anti-Hallucination Design

- Recommendations are **hints with citations** (e.g., "per ISO 14044 Section 4.2.3.2"), never fabricated compliance status
- All compliance checks reference specific ISO section numbers
- Data quality scoring uses established pedigree matrix methodology
- Benchmark comparisons cite EPD database sources
- RAG search returns relevance scores — agent can assess confidence before citing
