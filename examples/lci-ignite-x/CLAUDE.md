# LCI Ignite X

AI-powered LCA (Life Cycle Assessment) analysis platform built on OpenBench SDK.

## Quick Start

```bash
# Install
pip install -e .

# Set environment
export GOOGLE_API_KEY=your-key
export PINECONE_API_KEY=your-key  # Optional, for PROPER 2025 RAG

# Run server
uvicorn lci_ignite.server.app:create_app --factory --port 8000
```

## Project Structure

```
src/lci_ignite/
├── config.py                    # LCIConfig dataclass
├── data/
│   ├── sources/
│   │   ├── easylca.py           # EasyLCASource(DataSource)
│   │   └── simapro_csv.py       # SimaProCSVSource(DataSource)
│   └── attachment_handler.py    # CSV format detection + DataSource factory
├── intelligence/
│   ├── io_table_agent.py        # IOTableAgent(BaseAgent)
│   ├── hotspot_agent.py         # HotspotAnalysisAgent(BaseAgent)
│   ├── narrative_agent.py       # NarrativeHotspotAgent(BaseAgent)
│   ├── tools.py                 # ContextVar render-items tools
│   └── prompts.py               # LCA domain system prompts
├── output/
│   └── docx_generator.py        # DocxReportGenerator(OutputGenerator)
├── chat/
│   └── step_indicator.py        # Pipeline progress tracking
├── server/
│   ├── app.py                   # FastAPI create_app()
│   └── handler.py               # LCIAGUIHandler(AGUIHandler)
├── pipeline/
│   └── lca_pipeline.py          # build_lca_pipeline() -> Workflow
└── indexer/
    └── proper_indexer.py        # PROPER 2025 Pinecone indexer
```

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
- `Workflow`, `Chain` — Pipeline orchestration
- `SQLiteMemoryStore`, `PersistentMemory` — Conversation persistence
- `PineconeStore`, `GoogleEmbeddingProvider` — PROPER 2025 RAG
