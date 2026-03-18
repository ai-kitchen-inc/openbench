# LCI Ignite X

AI-powered LCA (Life Cycle Assessment) analysis platform built on OpenBench SDK.

## Prerequisites

- Python >= 3.10
- Node.js >= 18
- pnpm (`npm install -g pnpm`)

## Quick Start

```bash
# 1. Clone
git clone -b feat/lci-ignite-x https://github.com/ai-kitchen-inc/openbench.git
cd openbench

# 2. Install OpenBench SDK
pip install -e .

# 3. Configure environment
cp examples/lci-ignite-x/.env.example examples/lci-ignite-x/.env
# Edit .env and set your GOOGLE_API_KEY

# 4. Run (auto-installs Python deps, builds chat-ui, starts backend :8003 + frontend :5173)
openbench demo run lci-ignite-x
```

## Project Structure

```
examples/lci-ignite-x/
├── server.py                    # Demo entry point (uvicorn server:app --port 8003)
├── pyproject.toml               # Python package config
├── .env.example                 # Environment variables template
├── docs/
│   ├── input.xlsx               # Sample PHM LCA Excel dataset (33 sheets)
│   └── input_easylca.csv        # Converted easyLCA CSV for upload
├── scripts/
│   └── index_proper_docs.py     # PROPER 2025 Pinecone indexer
├── frontend/                    # React frontend (@openbench/chat-ui)
│   ├── package.json             # pnpm dependencies
│   ├── vite.config.ts           # Vite dev server, proxies to :8003
│   ├── src/
│   │   ├── App.tsx              # ChatProvider + ChatPanel + SessionSidebar
│   │   ├── main.tsx             # React root
│   │   └── global.css           # Fullscreen layout styles
│   └── index.html
├── src/lci_ignite/
│   ├── config.py                    # LCIConfig dataclass
│   ├── data/
│   │   ├── lci_schema.py            # Standard 17 LDI categories, normalization, validation
│   │   ├── excel_profile.py         # ExcelProfile metadata extractor (Layer 2)
│   │   ├── mapping_profiles/        # Company-specific column mappings
│   │   │   ├── __init__.py          # Profile loader/saver/matcher
│   │   │   └── pertamina_pep_tanjung.json  # Pertamina EP LDI profile
│   │   ├── sources/
│   │   │   ├── easylca.py           # EasyLCASource(DataSource)
│   │   │   ├── simapro_csv.py       # SimaProCSVSource(DataSource)
│   │   │   └── excel_lci.py         # ExcelLCISource(DataSource) — generic LDI parser
│   │   └── attachment_handler.py    # CSV/Excel format detection + DataSource factory
│   ├── intelligence/
│   │   ├── io_table_agent.py        # IOTableAgent(BaseAgent) — 11 tools
│   │   ├── hotspot_agent.py         # HotspotAnalysisAgent(BaseAgent)
│   │   ├── narrative_agent.py       # NarrativeHotspotAgent(BaseAgent)
│   │   ├── tools.py                 # 18 ContextVar render-items tools
│   │   └── prompts.py               # LCA domain system prompts
│   ├── output/
│   │   └── docx_generator.py        # DocxReportGenerator(OutputGenerator)
│   ├── chat/
│   │   └── step_indicator.py        # Pipeline progress tracking
│   ├── server/
│   │   ├── app.py                   # FastAPI create_app()
│   │   └── handler.py               # LCIAGUIHandler(AGUIHandler)
│   ├── pipeline/
│   │   └── lca_pipeline.py          # build_lca_pipeline() -> Workflow
│   └── indexer/
│       └── proper_indexer.py        # PROPER 2025 Pinecone indexer
└── tests/
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_API_KEY` | (required) | Google Gemini API key |
| `PINECONE_API_KEY` | (optional) | Pinecone API key for PROPER 2025 RAG |
| `PINECONE_INDEX_NAME` | `lci-ignite` | Pinecone index name |
| `PINECONE_NAMESPACE` | `proper-2025` | Pinecone namespace |
| `LCI_MODEL` | `gemini-2.5-flash` | Gemini model name |
| `LCI_TEMPERATURE` | `0.3` | LLM temperature |
| `LCI_MEMORY_DB` | `lci_memory.db` | SQLite memory database path |
| `LCI_UPLOAD_DIR` | `./uploads` | Upload directory |
| `LCI_EMBEDDING_MODEL` | `text-embedding-004` | Google embedding model |

## Testing

```bash
conda activate py312
python -m pytest tests/unit/ -v           # Unit tests
python -m pytest tests/integration/ -v    # Integration tests
python -m pytest tests/ --cov=lci_ignite  # Coverage
```

## Key Patterns

- **ContextVar render-items**: Tools push A2UI visualization data to `contextvars.ContextVar`
- **Per-session memory**: `LCIAGUIHandler` creates `PersistentMemory` per AG-UI threadId
- **Pareto analysis**: `calculate_pareto()` identifies 80/20 environmental hotspots
- **Multi-hop RAG**: `HotspotAnalysisAgent` uses `multi_hop_rag=True` for PROPER 2025 retrieval
- **3-Layer Parsing**: Format Detection (deterministic) → Structure Extraction (ExcelProfile) → Semantic Mapping (LLM, one-time per company)
- **MappingProfile**: JSON config per company format, auto-matched by sheet name or header overlap >80%
- **1-Sheet Input**: User uploads only LDI Master sheet; IO Table is BUILT by the system (not parsed from 46-sheet Excel)

## Tools (18 Total)

### Data Processing (7 new)
| Tool | Description |
|------|-------------|
| `analyze_excel_structure` | Extract ExcelProfile metadata (Layer 2, no LLM) |
| `parse_ldi_sheet` | Parse LDI Master using MappingProfile → Standard LCI Schema |
| `apply_unit_conversions` | Convert units (ton→kg, barrel→L, m3→L) |
| `calculate_functional_unit` | Calculate per-MJ FU values per product |
| `select_pareto_items` | Top N items + aggregate rest into "Lainnya" |
| `validate_data_quality` | Detect known issues (N2O=NOx, missing ×1000) |
| `build_proper_io_table` | Build 11-column × 25-section PROPER IO Table |

### IO Table (4)
| Tool | Description |
|------|-------------|
| `create_io_table` | Simple 5-column IO table (CSV flow) |
| `aggregate_by_category` | Sum amounts by category |
| `validate_units` | Check unit consistency |
| `create_io_table_chart` | IO table visualization |

### Hotspot (4)
| Tool | Description |
|------|-------------|
| `calculate_pareto` | 80/20 Pareto analysis |
| `create_pareto_chart` | Pareto chart visualization |
| `create_hotspot_table` | Ranked hotspot summary table |
| `create_hotspot_callout` | Critical findings callout |

### Output (3)
| Tool | Description |
|------|-------------|
| `create_narrative_markdown` | Narrative section rendering |
| `create_narrative_callout` | Key recommendations callout |
| `export_to_docx` | Generate .docx report via DocxReportGenerator |

## OpenBench SDK APIs Used

- `DataSource`, `RawData` — CSV and Excel data sources
- `BaseAgent` — All 3 domain agents
- `OutputGenerator`, `GeneratedOutput` — DOCX export
- `ChatEngine`, `AGUIHandler`, `AGUIActionHandler` — Chat transport
- `FileStore`, `FileContentExtractor` — File upload handling
- `Workflow`, `Chain` — Pipeline orchestration
- `SQLiteMemoryStore`, `PersistentMemory` — Conversation persistence
- `PineconeStore`, `GoogleEmbeddingProvider` — PROPER 2025 RAG
