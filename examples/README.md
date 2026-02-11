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
├── data/                        # Data source examples
│   └── langextract_demo.py
├── embeddings/                  # Embedding provider demos
│   ├── embedding_providers_demo.py
│   └── dynamic_registration_demo.py
├── intelligence/                # Agent and LLM provider demos
│   ├── gemini_agent_demo.py
│   └── agentic_research_demo.py
├── stores/                      # Vector store examples
│   └── pinecone_store_demo.py
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

## Data Examples (`data/`)

### 5. LangExtract Demo (`data/langextract_demo.py`)

Structured entity extraction using LangExtractSource:
- Few-shot examples for domain-specific extraction
- Multi-provider support (Gemini, OpenAI, Ollama)
- Class filtering (extract only specific entity types)
- Long document processing

**Requires:** `GOOGLE_API_KEY`, `pip install langextract`

```bash
python examples/data/langextract_demo.py
```

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

---

## Store Examples (`stores/`)

### 10. Pinecone Store Demo (`stores/pinecone_store_demo.py`)

Vector storage and semantic search with PineconeStore:
- Create/connect to Pinecone index
- Index documents with chunking and embeddings
- Semantic search queries
- Index stats and management

**Requires:** `PINECONE_API_KEY`, `GOOGLE_API_KEY`

```bash
python examples/stores/pinecone_store_demo.py
```

---

## Workflow Examples (`workflows/`)

### PDF Workflows (`workflows/pdf/`)

#### 11. PDF + Google ADK Workflow (`workflows/pdf/pdf_google_adk_workflow.py`)

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

#### 12. PDF Indexer (`workflows/pdf/pdf_indexer.py`)

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

#### 13. PDF RAG Workflow (`workflows/pdf/pdf_rag_workflow.py`)

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

#### 14. Entity Extraction Workflow (`workflows/entity/entity_extraction_workflow.py`)

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

#### 15. Entity Analysis + ADK (`workflows/entity/entity_analysis_adk_workflow.py`)

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

#### 16. Research Agent (`workflows/research/research_agent.py`)

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

#### 17. Hybrid Research Agent (`workflows/research/hybrid_research_agent.py`)

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

#### 18. Sustainability Report (`workflows/reports/sustainability_report.py`)

Complete real-world ESG/sustainability report generation. **No API key needed — uses mock data.**

- Parallel data extraction from multiple sources
- Sequential multi-agent processing (Research → Analysis → Content)
- Parallel output generation (PDF & PowerPoint)
- Named workflow with state management and checkpointing
- ProjectContext for multi-tenant isolation

```bash
python examples/workflows/reports/sustainability_report.py
```

#### 19. Knowledge Base Workflow (`workflows/reports/knowledge_base_workflow.py`)

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

## Summary

| # | Example | API Keys | What it demonstrates |
|---|---------|----------|---------------------|
| 1 | `core/core_abstractions_demo.py` | None | Abstractions, Registry, DAG, State |
| 2 | `core/orchestration_demo.py` | None | L1/L2 composition, create_workflow() |
| 3 | `core/agent_registry_demo.py` | None | AgentFactory, dynamic registration |
| 4 | `adapters/framework_adapters_demo.py` | None | Multi-framework orchestration |
| 5 | `data/langextract_demo.py` | Google | Structured entity extraction |
| 6a | `embeddings/embedding_providers_demo.py` | Google | Vector embeddings |
| 6b | `embeddings/dynamic_registration_demo.py` | None | Dynamic model/provider registration |
| 7 | `intelligence/gemini_agent_demo.py` | Google | BaseAgent reasoning loop + tools |
| 8 | `intelligence/agentic_research_demo.py` | Google (+Pinecone) | BaseAgent + RAG + web search |
| 9 | `intelligence/agentic_analysis_demo.py` | Google (+Pinecone) | AnalysisAgent + StructuredOutputAgent |
| 10 | `stores/pinecone_store_demo.py` | Google + Pinecone | Vector store, semantic search |
| 11 | `workflows/pdf/pdf_google_adk_workflow.py` | Google | PDF → Gemini → PDF/Markdown |
| 12 | `workflows/pdf/pdf_indexer.py` | Google + Pinecone | PDF → chunking → Pinecone |
| 13 | `workflows/pdf/pdf_rag_workflow.py` | Google + Pinecone | Full RAG with L2 layers |
| 14 | `workflows/entity/entity_extraction_workflow.py` | Google | PDF → entities |
| 15 | `workflows/entity/entity_analysis_adk_workflow.py` | Google | Extraction + Gemini analysis |
| 16 | `workflows/research/research_agent.py` | Google + Pinecone | RAG agent + interactive REPL |
| 17 | `workflows/research/hybrid_research_agent.py` | Google + Pinecone | Multi-mode research, openclaw |
| 18 | `workflows/reports/sustainability_report.py` | None | Full E2E report (mock data) |
| 19 | `workflows/reports/knowledge_base_workflow.py` | Google + Pinecone | Index → Query RAG pipeline |

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
- [Architecture Overview](../docs/architecture.md)
- [GitHub Issues](https://github.com/ai-kitchen-inc/openbench/issues)
