# OpenBench Examples

Production-ready examples demonstrating OpenBench's composable abstractions and workflow patterns.

## Directory Structure

```
examples/
├── core/                        # Core concepts (no API key needed)
│   ├── core_abstractions_demo.py
│   ├── orchestration_demo.py
│   └── agent_registry_demo.py
├── adapters/                    # Framework adapters (no API key needed)
│   └── framework_adapters_demo.py
├── chat/                        # Chat UI demo (AG-UI + A2UI)
│   ├── gemini_agent.py          # Gemini agent with tools
│   ├── server.py                # FastAPI AG-UI server
│   ├── frontend/                # React frontend (@openbench/chat-ui)
│   └── README.md
├── embeddings/                  # Embedding provider demos
│   ├── embedding_providers_demo.py
│   └── dynamic_registration_demo.py
├── intelligence/                # Agent and LLM provider demos
│   ├── gemini_agent_demo.py
│   ├── agentic_research_demo.py
│   ├── agentic_analysis_demo.py
│   ├── query_rewriter_demo.py   # Query rewriting for better retrieval
│   ├── multi_hop_rag_demo.py    # Agent-driven iterative retrieval
│   └── combined_rag_demo.py     # All 3 features combined ("Golden Stack")
├── stores/                      # Vector store examples
│   ├── pinecone_store_demo.py
│   └── hybrid_search_demo.py    # Vector + BM25 keyword reranking
├── workflows/                   # Complete end-to-end workflows
│   ├── pdf/                     # PDF processing workflows
│   │   ├── pdf_google_adk_workflow.py
│   │   ├── pdf_indexer.py
│   │   └── pdf_rag_workflow.py
│   ├── entity/                  # Entity extraction workflows
│   │   ├── entity_extraction_workflow.py
│   │   └── entity_analysis_adk_workflow.py
│   ├── research/                # Research agent workflows
│   │   ├── research_agent.py
│   │   └── hybrid_research_agent.py
│   └── reports/                 # End-to-end report generation
│       ├── sustainability_report.py
│       └── knowledge_base_workflow.py
├── lci-ignite-x/                  # Full-stack LCA analysis platform
│   ├── server.py                  # Demo entry point (:8003)
│   ├── frontend/                  # React app (@openbench/chat-ui)
│   ├── src/lci_ignite/            # Python package
│   └── README.md
└── README.md
```

## Quick Start

Examples that run immediately without API keys:

```bash
python examples/core/core_abstractions_demo.py
python examples/core/orchestration_demo.py
python examples/core/agent_registry_demo.py
python examples/adapters/framework_adapters_demo.py
python examples/workflows/reports/sustainability_report.py
```

Examples that require API keys:

```bash
export GOOGLE_API_KEY=your-google-api-key
export PINECONE_API_KEY=your-pinecone-api-key  # for RAG/vector examples

python examples/intelligence/gemini_agent_demo.py
python examples/embeddings/embedding_providers_demo.py
python examples/workflows/research/hybrid_research_agent.py "revenue 2024 acme" --mode rag
```

---

## Core Examples (`core/`)

No API keys required. All use mock data.

### 1. Core Abstractions Demo (`core/core_abstractions_demo.py`)

Foundational Chainable abstractions and composition patterns:
- Custom DataSource, Agent, OutputGenerator implementations
- Registry pattern for provider selection
- Sequential (`A | B | C`), Parallel (`A & B & C`), Conditional, Router
- Complex DAG structures
- Stateful workflows with checkpointing

```bash
python examples/core/core_abstractions_demo.py
```

### 2. L1/L2 Orchestration Demo (`core/orchestration_demo.py`)

Two-level composition — components (L1) into systems (L2):
- L1: `source1 | source2`, `agent1 | agent2`
- L2: `DataLayer | IntelligenceLayer | OutputLayer`
- DAG workflows within layers
- `create_workflow()` helper for rapid prototyping

```bash
python examples/core/orchestration_demo.py
```

### 3. Agent Registry Demo (`core/agent_registry_demo.py`)

Dynamic agent registration and creation via AgentFactory:
- List built-in agent types and providers
- Create agents using factory pattern
- Register custom agents
- Use custom agents in workflows

```bash
python examples/core/agent_registry_demo.py
```

---

## Adapter Examples (`adapters/`)

No API keys required. Uses mock framework implementations.

### 4. Framework Adapters Demo (`adapters/framework_adapters_demo.py`)

OpenBench as universal control plane for multiple AI frameworks:
- FrameworkAdapter minimal interface
- Mock LangChain, AG2, CrewAI, E2B adapter examples
- Mixed-framework workflows (combine agents from different frameworks)
- Zero migration — use existing agents as-is

```bash
python examples/adapters/framework_adapters_demo.py
```

---

## Chat Demo (`chat/`)

### 5. Chat Demo (`chat/`)

Full-stack chat application: Python AG-UI backend + React frontend with `@openbench/chat-ui`.

- **Progressive token streaming** -- text appears word-by-word via AG-UI protocol
- **Gemini agent** with real LLM reasoning, tool calling, and multi-turn memory
- **10 tools**: search_web, analyze_file, knowledge_lookup, calculate, get_datetime, extract_entities, create_chart, create_form, show_file, generate_file
- **File upload** -- upload PDFs/text files for agent analysis
- **Rich UI** -- A2UI v0.10 streaming with charts, forms, file cards, markdown
- **Agentic AI** -- task planning, parallel tool execution, persistent memory (SQLite)

**Requires:** `GOOGLE_API_KEY`

```bash
# Backend
cd examples/chat
export GOOGLE_API_KEY=your-key-here
uvicorn server:app --port 8000 --reload

# Frontend (separate terminal)
cd examples/chat/frontend
pnpm install
pnpm dev
```

See [chat/README.md](chat/README.md) for full details.

---

## Embedding Examples (`embeddings/`)

### 6. Embedding Providers Demo (`embeddings/embedding_providers_demo.py`)

Vector embedding generation with GoogleEmbeddingProvider:
- Single text embedding
- Batch embeddings
- Similarity comparison between texts

**Requires:** `GOOGLE_API_KEY`

```bash
python examples/embeddings/embedding_providers_demo.py
```

### 6b. Dynamic Registration Demo (`embeddings/dynamic_registration_demo.py`)

Runtime registration of new embedding models and providers:
- Register new model to existing provider (`register_model`)
- Register completely new provider (`register_provider`)
- Auto-resolve provider from model name (`resolve_embedding_provider`)
- Error handling for invalid registrations

**Requires:** None (uses mock provider)

```bash
python examples/embeddings/dynamic_registration_demo.py
```

---

## Intelligence Examples (`intelligence/`)

### 7. Gemini Agent Demo (`intelligence/gemini_agent_demo.py`)

**Runs `BaseAgent.execute()` with a real reasoning loop and tool calling.**

Three demo patterns:
- **Demo 1 — Direct LLM**: Call `GeminiLLMProvider.generate()` directly
- **Demo 2 — Agent + Tools**: BaseAgent with tool calling (calculate + knowledge_lookup), reasoning loop iterates until done
- **Demo 3 — Multi-turn**: Agent with memory persistence across conversation turns

**Requires:** `GOOGLE_API_KEY`, `pip install google-genai`

```bash
python examples/intelligence/gemini_agent_demo.py            # All demos
python examples/intelligence/gemini_agent_demo.py --demo 2    # Tools only
python examples/intelligence/gemini_agent_demo.py --model gemini-2.5-pro
```

### 8. Agentic Research Demo (`intelligence/agentic_research_demo.py`)

**BaseAgent reasoning loop with RAG + Web Search — three approaches.**

Three demo patterns:
- **Demo 1 — Built-in Store**: `BaseAgent(store=PineconeStore(...))` — auto-retrieves every `execute()`
- **Demo 2 — Tool-based**: Agent decides when to call `search_web` / `search_knowledge_base` tools
- **Demo 3 — Combined**: Built-in store for auto-context + `search_web` tool for extra info

**Requires:** `GOOGLE_API_KEY`, `PINECONE_API_KEY` (optional — demos skip gracefully)

```bash
python examples/intelligence/agentic_research_demo.py                     # All demos
python examples/intelligence/agentic_research_demo.py --demo 2            # Tool-based only
python examples/intelligence/agentic_research_demo.py --demo 2 -q "acme revenue 2024"
python examples/intelligence/agentic_research_demo.py --model gemini-2.5-pro
```

### 9. Agentic Analysis Demo (`intelligence/agentic_analysis_demo.py`)

**AnalysisAgent + StructuredOutputAgent — three analysis approaches.**

Three demo patterns:
- **Demo 1 — AnalysisAgent + Tools**: `AnalysisAgent` with `calculate` + `search_web` tools for data-driven analysis
- **Demo 2 — Document Analysis**: `AnalysisAgent(store=PineconeStore(...))` for RAG-based document analysis
- **Demo 3 — Structured Output**: `StructuredOutputAgent` returns validated JSON analysis results

**Requires:** `GOOGLE_API_KEY`, `PINECONE_API_KEY` (optional — Demo 2 skips gracefully)

```bash
python examples/intelligence/agentic_analysis_demo.py                     # All demos
python examples/intelligence/agentic_analysis_demo.py --demo 1            # Tools only
python examples/intelligence/agentic_analysis_demo.py --demo 3            # Structured JSON
python examples/intelligence/agentic_analysis_demo.py --demo 1 -q "analyze AI market growth"
python examples/intelligence/agentic_analysis_demo.py --model gemini-2.5-pro
```

### 10. Query Rewriter Demo (`intelligence/query_rewriter_demo.py`)

**LLM-based query enhancement for better RAG retrieval.**

QueryRewriter rewrites a user query into 1-3 optimized search queries,
improving semantic search recall without changing application code.

Two demo patterns:
- **Demo 1 -- Standalone**: Use `QueryRewriter` directly to see how queries are rewritten
- **Demo 2 -- With BaseAgent**: Enable `query_rewriter=True` on BaseAgent for automatic rewriting

**Requires:** `GOOGLE_API_KEY`, `PINECONE_API_KEY` (optional -- Demo 2 skips gracefully)

```bash
python examples/intelligence/query_rewriter_demo.py              # All demos
python examples/intelligence/query_rewriter_demo.py --demo 1     # Standalone only
python examples/intelligence/query_rewriter_demo.py --model gemini-2.5-pro
```

### 11. Multi-Hop RAG Demo (`intelligence/multi_hop_rag_demo.py`)

**Agent-driven iterative knowledge retrieval.**

With `multi_hop_rag=True`, BaseAgent receives a `retrieve_knowledge` tool and
decides when and what to search during its reasoning loop -- enabling multi-step
research where the agent refines queries based on initial findings.

Two demo patterns:
- **Demo 1 -- Auto-RAG (baseline)**: Single-pass retrieval at start (for comparison)
- **Demo 2 -- Multi-Hop RAG**: Agent calls `retrieve_knowledge` multiple times during reasoning

**Requires:** `GOOGLE_API_KEY`, `PINECONE_API_KEY`

```bash
python examples/intelligence/multi_hop_rag_demo.py               # All demos
python examples/intelligence/multi_hop_rag_demo.py --demo 2      # Multi-hop only
python examples/intelligence/multi_hop_rag_demo.py -q "custom query"
```

### 12. Combined RAG Demo -- The "Golden Stack" (`intelligence/combined_rag_demo.py`)

**All three retrieval features working together for maximum quality.**

Combines Query Rewriter + Multi-Hop RAG + Hybrid Search. Each operates at a
different level and composes without conflict:

```
Agent calls retrieve_knowledge("cloud revenue Q3 vs Q4")
|
+-- QueryRewriter.rewrite()
|     -> "cloud division revenue Q3"
|     -> "cloud division revenue Q4"
|     -> "quarterly cloud earnings report"
|
+-- for each rewritten query:
|     +-- store.search() with Hybrid Search (vector + BM25)
|
Agent reads Q3 results, needs Q4 from a different document
|
+-- Agent calls retrieve_knowledge("Q4 financial report cloud")   <- Multi-Hop
|     +-- (same flow: rewrite -> hybrid search)
|
Agent has Q3 + Q4 data -> calculates difference -> final answer
```

**Requires:** `GOOGLE_API_KEY`, `PINECONE_API_KEY`

```bash
python examples/intelligence/combined_rag_demo.py
python examples/intelligence/combined_rag_demo.py --vector-weight 0.5
python examples/intelligence/combined_rag_demo.py -q "your custom query"
```

---

## Store Examples (`stores/`)

### 13. Pinecone Store Demo (`stores/pinecone_store_demo.py`)

Vector storage and semantic search with PineconeStore:
- Create/connect to Pinecone index
- Index documents with chunking and embeddings
- Semantic search queries
- Index stats and management

**Requires:** `PINECONE_API_KEY`, `GOOGLE_API_KEY`

```bash
python examples/stores/pinecone_store_demo.py
```

### 14. Hybrid Search Demo (`stores/hybrid_search_demo.py`)

**Vector + BM25 keyword scoring for better retrieval.**

HybridSearchMixin combines vector similarity with BM25 keyword scoring to
improve search quality -- especially for exact term matches that pure
semantic search can miss.

Three demo patterns:
- **Demo 1 -- Standalone BM25**: Use `HybridSearchMixin` directly (no API keys needed)
- **Demo 2 -- PineconeStore**: Compare vector-only vs hybrid search results
- **Demo 3 -- With BaseAgent**: Full RAG pipeline with hybrid-enabled store

**Requires:** Demo 1: None. Demo 2+3: `GOOGLE_API_KEY` + `PINECONE_API_KEY`

```bash
python examples/stores/hybrid_search_demo.py                     # All demos
python examples/stores/hybrid_search_demo.py --demo 1            # BM25 only (no API keys)
python examples/stores/hybrid_search_demo.py --vector-weight 0.5
```

---

## Workflow Examples (`workflows/`)

### PDF Workflows (`workflows/pdf/`)

#### 15. PDF + Google ADK Workflow (`workflows/pdf/pdf_google_adk_workflow.py`)

End-to-end: PDF → GoogleADK (Gemini) → PDF/Markdown output:
- PDF text extraction with PDFSource
- AI processing via GoogleADKAdapter
- PDF or Markdown output generation
- Named workflow with checkpoints

**Requires:** `GOOGLE_API_KEY`

```bash
python examples/workflows/pdf/pdf_google_adk_workflow.py input.pdf output.pdf
python examples/workflows/pdf/pdf_google_adk_workflow.py input.pdf output.pdf --goal "Summarize key points"
python examples/workflows/pdf/pdf_google_adk_workflow.py input.pdf output.md --format markdown
```

#### 16. PDF Indexer (`workflows/pdf/pdf_indexer.py`)

Data ingestion: PDF → chunking → embeddings → PineconeStore:
- PDF text extraction and chunking
- Embedding generation with Google gemini-embedding-001
- Batch indexing to Pinecone
- Configurable chunk size and overlap

**Requires:** `PINECONE_API_KEY`, `GOOGLE_API_KEY`

```bash
python examples/workflows/pdf/pdf_indexer.py document.pdf
python examples/workflows/pdf/pdf_indexer.py document.pdf --namespace my-project
python examples/workflows/pdf/pdf_indexer.py ./docs/*.pdf --batch
```

#### 17. PDF RAG Workflow (`workflows/pdf/pdf_rag_workflow.py`)

Full RAG pipeline using L2 composition:
- `DataLayer(PDFSource, PineconeStore) | IntelligenceLayer(GoogleADK) | OutputLayer(MarkdownGenerator)`
- Workflow class with checkpoints

**Requires:** `PINECONE_API_KEY`, `GOOGLE_API_KEY`

```bash
python examples/workflows/pdf/pdf_rag_workflow.py document.pdf
python examples/workflows/pdf/pdf_rag_workflow.py document.pdf -o report.md
python examples/workflows/pdf/pdf_rag_workflow.py document.pdf -q "What is this about?"
```

### Entity Extraction (`workflows/entity/`)

#### 18. Entity Extraction Workflow (`workflows/entity/entity_extraction_workflow.py`)

Structured extraction: PDF/text → LangExtractSource → entities:
- Few-shot examples for domain-specific extraction
- Class filtering (person, date, amount, etc.)
- Multi-provider (Gemini, OpenAI, Ollama)
- Multi-pass for long documents

**Requires:** `GOOGLE_API_KEY`, `pip install langextract`

```bash
python examples/workflows/entity/entity_extraction_workflow.py report.pdf
python examples/workflows/entity/entity_extraction_workflow.py report.pdf --classes person date amount
python examples/workflows/entity/entity_extraction_workflow.py report.pdf --provider openai
```

#### 19. Entity Analysis + ADK (`workflows/entity/entity_analysis_adk_workflow.py`)

Combines extraction with Gemini analysis — 4 demo patterns:
1. Step-by-step: extract entities → analyze with Gemini
2. L1 chain: `PDFSource | LangExtractSource` → ADK analysis
3. L2 composition: `DataLayer | IntelligenceLayer | OutputLayer`
4. Multi-analysis: same entities, different perspectives

**Requires:** `GOOGLE_API_KEY`, `pip install langextract`

```bash
python examples/workflows/entity/entity_analysis_adk_workflow.py
python examples/workflows/entity/entity_analysis_adk_workflow.py report.pdf
python examples/workflows/entity/entity_analysis_adk_workflow.py --demo 1
```

### Research Workflows (`workflows/research/`)

#### 20. Research Agent (`workflows/research/research_agent.py`)

RAG-powered research agent with interactive REPL:
- PineconeStore retrieval with similarity scoring
- LLM synthesis with citations `[1]`, `[2]`, etc.
- Interactive mode: `/quit`, `/clear`, `/stats`
- Follow-up questions with conversation context

**Requires:** `PINECONE_API_KEY`, `GOOGLE_API_KEY`

```bash
python examples/workflows/research/research_agent.py "What is sustainability?"
python examples/workflows/research/research_agent.py --interactive
python examples/workflows/research/research_agent.py "Explain findings" --namespace my-project
```

#### 21. Hybrid Research Agent (`workflows/research/hybrid_research_agent.py`)

Multi-mode research with auto-namespace detection. **Used by openclaw telegram-agent.**

Three search modes:
- **grounded**: GroundedSearchSource (Gemini with built-in web search)
- **rag**: PineconeStore only (indexed knowledge base)
- **hybrid**: RAG + web enrichment (always combines both sources)

Features:
- Auto-detect namespace from query keywords (e.g., "acme" → namespace `acme`)
- Interactive REPL with `/grounded`, `/rag`, `/hybrid` mode switching
- `--quiet` mode for chatbot integration (minimal output)

**Requires:** `GOOGLE_API_KEY`, `PINECONE_API_KEY` (for rag/hybrid modes)

```bash
python examples/workflows/research/hybrid_research_agent.py "AI trends 2026" --mode grounded
python examples/workflows/research/hybrid_research_agent.py "check acme company profile" --mode rag
python examples/workflows/research/hybrid_research_agent.py "revenue 2024" --mode rag --namespace acme
python examples/workflows/research/hybrid_research_agent.py --list-namespaces
python examples/workflows/research/hybrid_research_agent.py --interactive
```

### Reports (`workflows/reports/`)

#### 22. Sustainability Report (`workflows/reports/sustainability_report.py`)

Complete real-world ESG/sustainability report generation. **No API key needed — uses mock data.**

- Parallel data extraction from multiple sources
- Sequential multi-agent processing (Research → Analysis → Content)
- Parallel output generation (PDF & PowerPoint)
- Named workflow with state management and checkpointing
- ProjectContext for multi-tenant isolation

```bash
python examples/workflows/reports/sustainability_report.py
```

#### 23. Knowledge Base Workflow (`workflows/reports/knowledge_base_workflow.py`)

Complete RAG pipeline — index, query, or full pipeline:
- `index`: PDFs → chunking → PineconeStore
- `query`: Query → RAG → Agent → Response
- `pipeline`: Index then query in one step
- L2 composition: `DataLayer | IntelligenceLayer | OutputLayer`

**Requires:** `PINECONE_API_KEY`, `GOOGLE_API_KEY`

```bash
python examples/workflows/reports/knowledge_base_workflow.py index ./docs/*.pdf --namespace my-kb
python examples/workflows/reports/knowledge_base_workflow.py query "What is sustainability?" --namespace my-kb
python examples/workflows/reports/knowledge_base_workflow.py pipeline doc.pdf "Summarize the document"
```

---

## LCI Ignite X (`lci-ignite-x/`)

### 24. LCI Ignite X (`lci-ignite-x/`)

Full-stack LCA (Life Cycle Assessment) analysis platform:
- **Backend**: FastAPI with AG-UI SSE streaming, file upload, persistent memory
- **Frontend**: React app with @openbench/chat-ui (ChatPanel, SessionSidebar, dark mode)
- **Intelligence**: Coordinator agent with 11 domain tools (IO table, Pareto hotspot, narrative, DOCX export)
- **Data**: easyLCA and SimaPro CSV parsers
- **RAG**: PROPER 2025 document retrieval via Pinecone

**Requires:** Python >= 3.10, Node.js >= 18, pnpm, `GOOGLE_API_KEY`, optionally `PINECONE_API_KEY`

```bash
openbench demo run lci-ignite-x    # Auto-installs deps, builds chat-ui, starts :8003 + :5173
# Or manually:
cd examples/lci-ignite-x
pip install -e .
uvicorn server:app --port 8003 --reload
cd frontend && pnpm install && pnpm dev
```

See [lci-ignite-x/README.md](lci-ignite-x/README.md) for full details.

---

## Summary

| # | Example | API Keys | What it demonstrates |
|---|---------|----------|---------------------|
| 1 | `core/core_abstractions_demo.py` | None | Abstractions, Registry, DAG, State |
| 2 | `core/orchestration_demo.py` | None | L1/L2 composition, create_workflow() |
| 3 | `core/agent_registry_demo.py` | None | AgentFactory, dynamic registration |
| 4 | `adapters/framework_adapters_demo.py` | None | Multi-framework orchestration |
| 5 | `chat/` | Google | AG-UI streaming, A2UI rich UI, file upload, planning, parallel tools, persistent memory |
| 6a | `embeddings/embedding_providers_demo.py` | Google | Vector embeddings |
| 6b | `embeddings/dynamic_registration_demo.py` | None | Dynamic model/provider registration |
| 7 | `intelligence/gemini_agent_demo.py` | Google | BaseAgent reasoning loop + tools |
| 8 | `intelligence/agentic_research_demo.py` | Google (+Pinecone) | BaseAgent + RAG + web search |
| 9 | `intelligence/agentic_analysis_demo.py` | Google (+Pinecone) | AnalysisAgent + StructuredOutputAgent |
| 10 | `intelligence/query_rewriter_demo.py` | Google (+Pinecone) | LLM-based query enhancement for RAG |
| 11 | `intelligence/multi_hop_rag_demo.py` | Google + Pinecone | Agent-driven iterative retrieval |
| 12 | `intelligence/combined_rag_demo.py` | Google + Pinecone | "Golden Stack" -- all 3 features combined |
| 13 | `stores/pinecone_store_demo.py` | Google + Pinecone | Vector store, semantic search |
| 14 | `stores/hybrid_search_demo.py` | None (Demo 1) | Vector + BM25 keyword reranking |
| 15 | `workflows/pdf/pdf_google_adk_workflow.py` | Google | PDF → Gemini → PDF/Markdown |
| 16 | `workflows/pdf/pdf_indexer.py` | Google + Pinecone | PDF → chunking → Pinecone |
| 17 | `workflows/pdf/pdf_rag_workflow.py` | Google + Pinecone | Full RAG with L2 layers |
| 18 | `workflows/entity/entity_extraction_workflow.py` | Google | PDF → entities |
| 19 | `workflows/entity/entity_analysis_adk_workflow.py` | Google | Extraction + Gemini analysis |
| 20 | `workflows/research/research_agent.py` | Google + Pinecone | RAG agent + interactive REPL |
| 21 | `workflows/research/hybrid_research_agent.py` | Google + Pinecone | Multi-mode research, openclaw |
| 22 | `workflows/reports/sustainability_report.py` | None | Full E2E report (mock data) |
| 23 | `workflows/reports/knowledge_base_workflow.py` | Google + Pinecone | Index → Query RAG pipeline |
| 24 | `lci-ignite-x/` | Google (+Pinecone) | Full-stack LCA analysis: IO tables, Pareto hotspots, DOCX export, AG-UI streaming |

## Common Patterns

### Sequential Workflow

```python
from openbench.core import DataLayer, IntelligenceLayer, OutputLayer

workflow = data_layer | intelligence_layer | output_layer
result = workflow.invoke({"query": "analyze sustainability"})
```

### Parallel Processing

```python
from openbench.core import Parallel

data_layer = DataLayer(sources=Parallel([pdf_source, api_source, csv_source]))
output_layer = OutputLayer(generators=pdf_generator & pptx_generator)
```

### Named Workflow with Checkpointing

```python
from openbench.workflows import Workflow

workflow = Workflow(
    name="my-workflow",
    chain=data_layer | intelligence_layer | output_layer,
    checkpoints=True
)
result = workflow.run({"project": "Analysis"})
```

## Need Help?

- [Getting Started Guide](../docs/GETTING_STARTED.md)
- [API Reference](../docs/API.md)
- [Architecture Overview](../docs/ARCHITECTURE.md)
- [GitHub Issues](https://github.com/ai-kitchen-inc/openbench/issues)
