# LCI Ignite X

AI-powered LCA (Life Cycle Assessment) analysis platform built on OpenBench SDK.

## Prerequisites

- Python >= 3.10
- Node.js >= 18
- pnpm (`npm install -g pnpm`)

## Quick Start

```bash
# Install OpenBench (from repo root, one-time)
pip install -e .

# Set environment (copy and fill in .env.example)
cp .env.example .env

# Run via demo CLI (auto-installs Python deps, builds chat-ui, starts backend :8003 + frontend :5173)
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
│   │   ├── sources/
│   │   │   ├── easylca.py           # EasyLCASource(DataSource)
│   │   │   └── simapro_csv.py       # SimaProCSVSource(DataSource)
│   │   └── attachment_handler.py    # CSV format detection + DataSource factory
│   ├── intelligence/
│   │   ├── io_table_agent.py        # IOTableAgent(BaseAgent)
│   │   ├── hotspot_agent.py         # HotspotAnalysisAgent(BaseAgent)
│   │   ├── narrative_agent.py       # NarrativeHotspotAgent(BaseAgent)
│   │   ├── tools.py                 # ContextVar render-items tools
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

## OpenBench SDK APIs Used

- `DataSource`, `RawData` — CSV data sources
- `BaseAgent` — All 3 domain agents
- `OutputGenerator`, `GeneratedOutput` — DOCX export
- `ChatEngine`, `AGUIHandler`, `AGUIActionHandler` — Chat transport
- `FileStore`, `FileContentExtractor` — File upload handling
- `Workflow`, `Chain` — Pipeline orchestration
- `SQLiteMemoryStore`, `PersistentMemory` — Conversation persistence
- `PineconeStore`, `GoogleEmbeddingProvider` — PROPER 2025 RAG
