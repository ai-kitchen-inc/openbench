# CLAUDE.md

Guidance for Claude Code when working with this repository.

## Critical Rules (Read First!)

**Before writing ANY code:**
- [ ] READ the file you're about to modify
- [ ] SEARCH for existing patterns (`Grep` for similar code)
- [ ] VERIFY imports exist (don't guess!)
- [ ] CHECK method signatures before calling them
- [ ] FOLLOW conventions from existing codebase
- [ ] ASK when uncertain - don't guess implementation details

**Never:**
- Invent imports/classes/methods that don't exist
- Add unused imports or dead code
- Assume file contents without reading
- Skip running tests after changes
- Guess when you can ask the user

## Project Overview

**OpenBench** - Open-source Python SDK for composable AI workflows.

**Core Concepts:**
- **DataSource** - Raw data (PDFs, APIs, databases)
- **Agent** - AI processing
- **OutputGenerator** - Generated artifacts (PDF, PPTX, audio)

**Three-Layer Architecture:** Data Layer -> Intelligence Layer -> Output Layer

**Design Principles:**
1. Everything is Chainable (`invoke()`, `|`, `&` operators)
2. Composition Over Configuration
3. Implementation Independence (swap providers without code changes)
4. Two-Level Orchestration (L1 components, L2 layers)
5. DAG Workflows

**Frontend SDK:**
- `@openbench/chat-ui` -- React component library for chat interfaces
- A2UI v0.10 (Google) declarative JSON streaming protocol for rich UI rendering
- AG-UI protocol transport (SSE event streaming + REST actions)

## Positioning & Classification

**OpenBench is a Workflow Orchestrator + Agent Runtime + Universal Control Plane for AI.**

It orchestrates workflows across frameworks AND provides built-in agent capabilities
(BaseAgent with reasoning loop, tools, memory, RAG).

> When routing a new capability, check [docs/MENTAL_MODEL.md](docs/MENTAL_MODEL.md)
> first — it defines the four pillars (MCP / Skill / Agentic / Output) and the
> decision matrix that says where each capability belongs. Storage, data, and LLM
> providers are plumbing under Agentic, **not** pillars.

### What OpenBench IS

| Role | Description |
|------|-------------|
| **Workflow Orchestrator** | Compose steps with `\|` and `&` operators |
| **Universal Control Plane** | Connect any framework via adapters |
| **Data Pipeline** | ETL for AI (Extract -> Transform -> Load) |
| **Multi-Agent Coordinator** | Chain multiple agents from different frameworks |
| **Agent Runtime** | Built-in BaseAgent with reasoning loop, tools, memory, RAG |

### What OpenBench is NOT

| Not This | Because |
|----------|---------|
| **Autonomous AI** | Not self-directed — user defines workflow or agent goals |
| **Single-Framework** | Does not compete with LangChain/CrewAI, connects them |

### AI Systems Taxonomy

```
Level 1: LLM (Base Model)
         └── GPT-4, Claude, Gemini - text in, text out

Level 2: LLM Agent (Single Agent)  <-- OPENBENCH (BaseAgent)
         └── LLM + Tools + Memory + Reasoning Loop
         └── Built-in: BaseAgent, SimpleAgent, StructuredOutputAgent
         └── External: LangChain Agent, Google ADK Agent (via adapters)

Level 3: Multi-Agent System (Agentic AI)
         └── Multiple LLM Agents collaborating
         └── Examples: CrewAI crews, AutoGen teams

Level 4: Workflow Orchestrator  <-- OPENBENCH (Core)
         └── Coordinates agents + data + outputs
         └── Framework agnostic, DAG-based composition

Level 5: AI Platform
         └── Full infrastructure (compute, storage, monitoring)
         └── Examples: AWS Bedrock, Google Vertex AI
```

OpenBench spans **Level 2 + Level 4**: provides both built-in agent capabilities
(BaseAgent with reasoning loop, tool calling, memory, RAG) and workflow orchestration
(`|` `&` operators, L1/L2 layers, framework adapters).

### Analogy

OpenBench is like **"Kubernetes + built-in containers"** — it handles coordination AND provides ready-to-use agents.

| System | Role |
|--------|------|
| **Kubernetes** | Orchestrates containers, doesn't run code |
| **Airflow** | Orchestrates tasks, doesn't process data |
| **OpenBench** | Orchestrates AI workflows + provides built-in agents (BaseAgent) |

## Project Structure

```
openbench/
├── src/openbench/
│   ├── __init__.py              # Package exports
│   ├── core/                    # Core abstractions and infrastructure
│   │   ├── __init__.py          # Public API exports
│   │   ├── abstractions.py      # Base interfaces (DataSource, Agent, OutputGenerator)
│   │   ├── chainable.py         # DAG workflow composition (Chain, Parallel, Conditional)
│   │   ├── registry.py          # Dynamic plugin registration with decorators
│   │   ├── providers.py         # Centralized Provider Service + credential encryption
│   │   ├── config.py            # Single source of truth Config + model registry
│   │   ├── layers.py            # L2 system-level orchestrators
│   │   └── state.py             # State management & checkpointing
│   ├── data/                    # Data layer
│   │   ├── sources/             # Data source implementations
│   │   │   ├── pdf.py           # PDF data source with chunking
│   │   │   ├── grounded_search.py # Grounded search source (Tavily, Google, DDG)
│   │   │   └── langextract.py   # Structured entity extraction (Google LangExtract)
│   │   └── stores/              # Vector store implementations
│   │       ├── base.py          # Base DataStore abstraction
│   │       └── pinecone.py      # Pinecone vector store
│   ├── adapters/                # Framework adapters
│   │   ├── google_adk.py        # Google ADK adapter
│   │   ├── langchain.py         # LangChain adapter
│   │   ├── crewai.py            # CrewAI adapter
│   │   ├── ag2.py               # AG2 adapter
│   │   └── e2b.py               # E2B adapter
│   ├── intelligence/            # AI agent layer
│   │   ├── base.py              # Framework-agnostic BaseAgent, ToolExecutor, AgentMemory, QueryRewriter
│   │   ├── agents.py            # Agent implementations (Research, Analysis, Content)
│   │   ├── llm_providers.py     # Concrete LLM providers (GeminiLLMProvider)
│   │   ├── embeddings.py        # Embedding providers (Google, OpenAI)
│   │   ├── planning.py          # TaskPlanner, TaskPlan (task decomposition)
│   │   ├── memory.py            # PersistentMemory, SQLiteMemoryStore
│   │   ├── persona.py           # Persona (SOUL/STYLE/AGENTS) — agent identity layer
│   │   ├── skill.py             # Skill dataclass — reusable capability packages
│   │   ├── skill_registry.py    # SkillRegistry (two-tier: SDK + project)
│   │   └── layer.py             # AgentFactory for creating agents
│   ├── mcp/                     # MCP pillar — full client/server integration
│   │   ├── client.py            # Multi-server MCP client
│   │   ├── server.py            # OpenBench MCP server wrapper
│   │   ├── adapters.py          # Expose MCP tools via OpenBench Tool abstraction
│   │   ├── schema.py            # Function-tool <-> MCP tool schema adapters
│   │   ├── tool_registry.py     # Load/wrap OpenBench tools for MCP exposure
│   │   ├── discovery.py         # Discovery data structures for MCP clients
│   │   ├── transports.py        # MCP client transports (stdio, streamable HTTP)
│   │   ├── toolhive.py          # ToolHive discovery + control helpers
│   │   ├── policy.py            # Security policy for MCP tool access
│   │   ├── prompts.py           # Reusable MCP prompts
│   │   ├── resources.py         # MCP resource helpers for skills
│   │   ├── observability.py     # Observability helpers for MCP calls
│   │   ├── config.py            # MCP configuration models
│   │   ├── standard_config.py   # Standard MCP client config parsing
│   │   └── errors.py            # Structured MCP errors
│   ├── integrations/            # Optional third-party integrations (extras)
│   │   ├── mcp/                 # MCPClient Protocol — surface for MCP-backed skills
│   │   ├── gdrive/              # Google Drive storage (backend, file/memory/session store, scratchpad, persona source)
│   │   └── firebase_auth/       # Firebase Auth (verifier, token store, Drive OAuth)
│   ├── skills/                  # Bundled SDK skills (loaded by SkillRegistry.load_sdk_skills())
│   │   ├── data-context-extractor/  # Read CSV/TSV/XLSX/JSON → normalized payload
│   │   ├── data-visualization/      # Build ObChart-compatible chart dicts
│   │   ├── export-excel/            # Single + multi-sheet .xlsx writer
│   │   ├── query-explorer/          # filter/sort/group/distinct/top-N over records
│   │   ├── drive-explorer/          # Search/read Google Drive via MCP server
│   │   ├── memory-scratchpad/       # Persistent user-editable markdown memory
│   │   ├── pdf-tools/               # Read/analyze/manipulate/generate PDFs
│   │   └── web-search/              # Web search via Gemini Google Search grounding
│   ├── testing/                 # Public storage-backend contract test harness
│   ├── chat/                    # Chat layer (A2UI-powered)
│   │   ├── engine.py            # ChatEngine (Chainable) -- main orchestrator
│   │   ├── session.py           # ChatSession, ChatMessage, Attachment
│   │   ├── layer.py             # ChatLayer (L2) + ChatFactory
│   │   ├── a2ui/                # A2UI v0.10 message building
│   │   │   ├── builder.py       # A2UIMessageBuilder -- A2UI v0.10 JSONL generator
│   │   │   ├── catalog.py       # Custom catalog (ObChart, ObFileCard, ObCodeBlock, ObMarkdown, ObTable, ObCallout)
│   │   │   └── schema.py        # A2UI v0.10 message types and validation
│   │   ├── renderers/           # Content -> A2UI component renderers (11 total)
│   │   │   ├── base.py          # ContentRenderer ABC + Registry
│   │   │   ├── text.py          # TextRenderer
│   │   │   ├── chart.py         # ChartRenderer
│   │   │   ├── code.py          # CodeRenderer
│   │   │   ├── form.py          # FormRenderer
│   │   │   ├── file.py          # FileRenderer
│   │   │   ├── media.py         # MediaRenderer
│   │   │   ├── list.py          # ListRenderer
│   │   │   ├── tabs.py          # TabsRenderer
│   │   │   ├── modal.py         # ModalRenderer
│   │   │   ├── table.py         # TableRenderer
│   │   │   └── callout.py       # CalloutRenderer
│   │   └── transport/           # AG-UI protocol transport
│   │       ├── agui.py          # AGUIHandler -- AG-UI SSE event streaming
│   │       └── agui_actions.py  # AGUIActionHandler -- REST for A2UI actions
│   ├── output/                  # Output generation layer
│   │   ├── generators.py        # Output generator implementations
│   │   └── layer.py             # OutputFactory for generating outputs
│   ├── workflows/               # Workflow system
│   │   └── workflow.py          # Named workflows with state management
│   ├── cli/                     # Command-line interface
│   │   ├── main.py              # CLI entry point
│   │   └── commands/            # CLI command groups (init, project, data, agent, workflow, generate, provider, models, config, tools, mcp, demo)
│   └── utils/                   # Utilities
├── studio/
│   └── chat-ui/                 # @openbench/chat-ui (React SDK)
│       ├── src/
│       │   ├── core/            # AG-UI transport, JSONL processor, Zustand store
│       │   ├── a2ui/            # SurfaceRenderer, catalog, standard + custom components
│       │   ├── components/      # ChatProvider, ChatPanel, MessageList, SessionSidebar
│       │   └── hooks/           # useChat, useA2UIProcessor
│       ├── styles/              # Default CSS (Notion-inspired, Lucide icons)
│       └── tests/
├── tests/                       # Test suite
├── examples/                    # Example workflows
├── docs/                        # Documentation
├── pyproject.toml               # Python project configuration
└── requirements.txt             # Dependencies
```

## Core Abstractions

### Composition Patterns

```python
# Sequential: A -> B -> C
workflow = step_a | step_b | step_c

# Parallel
workflow = step_a & step_b & step_c

# DAG: A -> (B & C) -> D
workflow = step_a | Parallel([step_b, step_c]) | step_d

# L2: Compose layers
workflow = DataLayer(sources=sources) | IntelligenceLayer(agents=agents) | OutputLayer(generators=outputs)

# L2: With chat layer
workflow = DataLayer(sources=[pdf]) | ChatLayer(agent=rag_agent)
workflow = ChatLayer(agent=agent) | OutputLayer(generators=[transcript])
```

### Registry and Workflows

```python
DataSourceRegistry.register('pdf', 'custom', MyPDFSource)
source = DataSourceRegistry.create('pdf', 'custom', path='./docs')

workflow = Workflow(name="report", chain=data | intelligence | output, checkpoints=True)
result = workflow.run({"project": "Q1 2026"})
```

### Persona & Skill Layer

**Persona** = WHO the agent is (identity). **Skill** = WHAT the agent can do
(capability). They are orthogonal: one persona per agent, N skills per agent.
See `.tmp/RFC-PERSONA-LAYER.md` for the full spec.

#### Persona — agent identity from `soul/` directories

A persona is composed from three markdown files in a `soul/` directory:

```
soul/
├── SOUL.md     # Identity: "I am an LCA analyst. I prioritize accuracy over speed."
├── STYLE.md    # Voice: "Reply in Indonesian. Use markdown tables for results."
└── AGENTS.md   # Rules: "Always call xql_catalog first. Never fabricate data."
```

Load it via the `persona=` parameter on `BaseAgent`:

```python
from openbench.intelligence.base import BaseAgent
from openbench.intelligence.persona import Persona

# Option A: Path-based (most common)
agent = BaseAgent(goal="Analyze data", persona="examples/lci-mini/soul/")

# Option B: Explicit Persona object
persona = Persona.from_dir("examples/lci-mini/soul/")
agent = BaseAgent(goal="Analyze data", persona=persona)

# Option C: Inline string (testing / dynamic composition)
agent = BaseAgent(goal="Analyze data", persona=Persona.from_prompt("You are..."))
```

`persona=` takes precedence over `system_prompt=` — passing both logs a
warning. `PersistentMemory` sessions replay the persona on resume.

#### Skills — reusable capability packages

A skill is a directory containing `SKILL.md`, optional `references/*.md`,
and optional `tools.py`. The skill loader auto-discovers `FOO_SCHEMA` +
`foo()` pairs in `tools.py` and registers them with the agent.

Two tiers:

1. **SDK skills** — bundled in `src/openbench/skills/`. Every project gets
   them for free. Currently: `data-context-extractor`, `data-visualization`,
   `export-excel`, `query-explorer`, `drive-explorer` (MCP-backed Google
   Drive), `memory-scratchpad` (persistent markdown memory), `pdf-tools`
   (read/generate PDFs), `web-search` (Gemini Google Search grounding).
2. **Project skills** — domain-specific, loaded from project paths.
   Project names override SDK names of the same skill (project wins).

```python
agent = BaseAgent(
    goal="Analyze uploaded spreadsheet",
    persona="soul/",
    skills=[
        # SDK skills — bare names, resolved via load_sdk_skills()
        "data-context-extractor",
        "query-explorer",
        "data-visualization",
        "export-excel",
        # Project skills — paths
        "skills/my-domain-parser",
        "skills/my-domain-rules",    # knowledge-only, no tools
    ],
)
```

Every `BaseAgent` owns its own `SkillRegistry` instance (not a global
singleton) so two agents in the same process can have different skill sets.
Skills can be **tool-bearing** (expose callables via `tools.py`) or
**knowledge-only** (only contribute `SKILL.md` + references to the system
prompt).

#### Authoring a new SDK skill

1. Create `src/openbench/skills/<skill-name>/` with `SKILL.md` (H1 =
   skill name, first paragraph = description, required `## Triggers`
   and `## Version` sections, optional `## Dependencies`).
2. Add `references/*.md` for any domain knowledge the agent needs
   alongside the description.
3. If the skill has tools, add `tools.py` with callables + matching
   `FOO_SCHEMA` dicts (uppercase variable → lowercase function, same
   prefix). The loader discovers pairs by convention — no decorators.
4. Add tests in `tests/test_sdk_skills.py` following the existing pattern
   (discovery + per-tool correctness + ChartRenderer/FileRenderer contract
   round-trip when applicable).

#### Key rules

- **Fail fast on init**: missing `SKILL.md`, malformed H1, and import
  errors in `tools.py` raise at `BaseAgent` construction — not at tool
  call time.
- **Lazy optional deps**: SDK skills import pandas/openpyxl inside tool
  functions (never at module top) so loading a skill never fails due to
  missing extras. The error only surfaces on actual tool invocation.
- **No tool name collisions**: `SkillRegistry.collect_tools()` raises
  `ValueError` if two loaded skills expose the same tool name.
- **Token budget is advisory**: `SkillRegistry.summary()` reports
  `context_chars` — use it to watch budget, but enforcement is not yet
  implemented (RFC Milestone 3).

## Build and Development

```bash
# Use Python 3.12 environment
conda activate py312

# Install
pip install -e .                 # Core
pip install -e ".[all]"          # All features
pip install -e ".[security]"     # With encryption
pip install -e ".[vector]"       # Pinecone vector store
pip install -e ".[search]"       # Tavily, Google Search, DuckDuckGo
pip install -e ".[google]"       # Google GenAI SDK
pip install -e ".[chat]"         # FastAPI + AG-UI for chat

# Test
python -m unittest discover tests -v
pytest tests/ --cov=openbench

# Examples
python examples/workflows/reports/sustainability_report.py
python examples/core/core_abstractions_demo.py

# Code quality
black src/ tests/ examples/
ruff check src/ tests/
mypy src/openbench/
```

## Examples Structure

```
examples/
├── core/           # Core abstractions and orchestration demos
├── adapters/       # Framework adapter examples
├── data/           # Data source examples
├── embeddings/     # Embedding provider demos
├── stores/         # Vector store examples (Pinecone)
│   ├── pinecone_store_demo.py
│   └── hybrid_search_demo.py        # Vector + BM25 keyword reranking
├── intelligence/   # Agent and LLM provider demos
│   ├── gemini_agent_demo.py
│   ├── agentic_research_demo.py
│   ├── agentic_analysis_demo.py
│   ├── query_rewriter_demo.py       # Query rewriting for better retrieval
│   ├── multi_hop_rag_demo.py        # Agent-driven iterative retrieval
│   ├── combined_rag_demo.py         # All 3 features combined ("Golden Stack")
│   ├── planning_demo.py             # Task decomposition before execution
│   ├── persistent_memory_demo.py    # SQLite-backed cross-session memory
│   └── parallel_tools_demo.py       # Concurrent tool execution
├── chat/           # Chat layer examples
│   ├── basic_chat_demo.py          # ChatEngine standalone
│   ├── chat_with_rag_demo.py       # DataLayer | ChatLayer pipeline
│   └── server.py                   # FastAPI AG-UI server
├── general-chat/    # Full-stack general chat app (files, URLs, images, MCP servers)
│   └── src/general_chat/          # Python package
├── mcp/             # MCP gateway/server configs (ToolHive, Docker MCP gateway)
├── image-search-mcp/   # Local DINOv3 + FAISS image similarity MCP server (CIFAR-10)
├── sam-segmentation-mcp/  # Dockerized SAM 3 concept-counting MCP server
├── lci-ignite-x/    # Full-stack LCA analysis app (Backend + React frontend)
│   ├── server.py                  # Demo entry point (:8003)
│   ├── frontend/                 # React app (@openbench/chat-ui)
│   └── src/lci_ignite/          # Python package (data, intelligence, output)
└── workflows/      # Complete E2E workflow examples
    ├── pdf/        # PDF processing workflows
    │   ├── pdf_google_adk_workflow.py
    │   ├── pdf_indexer.py
    │   └── pdf_rag_workflow.py
    ├── entity/     # Entity extraction workflows
    │   ├── entity_extraction_workflow.py
    │   └── entity_analysis_adk_workflow.py
    ├── research/   # Research agent workflows
    │   ├── research_agent.py
    │   └── hybrid_research_agent.py
    └── reports/    # End-to-end report generation
        ├── sustainability_report.py
        └── knowledge_base_workflow.py
```

## Google Model References

Use newer model names (minimum 2.5 series):
- `gemini-2.5-flash` - Fast, cost-effective
- `gemini-2.5-pro` - Balanced performance
- `gemini-3-flash-preview` - Latest preview

Avoid outdated: `gemini-1.5-pro`, `gemini-1.5-flash`, `gemini-2.0-flash-exp`

## Git Conventions

- Commits without Claude watermark (no `Co-Authored-By`)
- Use conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`

## Code Quality Rules (Anti-Hallucination)

### MUST DO Before Writing Code

1. **Read before write** - ALWAYS read existing files before modifying. Never assume file contents.
2. **Verify imports exist** - Check that modules/classes/functions exist before importing:
   ```python
   # WRONG: Assuming import exists
   from openbench.core import SomeClass  # Does SomeClass exist?

   # RIGHT: First verify with Grep or Read
   # grep "class SomeClass" src/openbench/
   ```
3. **Check method signatures** - Read the actual class before calling methods:
   ```python
   # WRONG: Guessing method parameters
   source.extract(format="json")  # Does extract() take format param?

   # RIGHT: Read the class definition first
   ```
4. **Verify base classes** - Check abstract methods before implementing subclasses

### NEVER DO

1. **Never invent APIs** - Don't create function calls that don't exist in the codebase
2. **Never guess imports** - If unsure, search the codebase first
3. **Never assume patterns** - Read existing similar code before writing new code
4. **Never add unused imports** - Only import what you actually use
5. **Never add unused code** - No dead functions, classes, or variables
6. **Never guess when uncertain** - Ask the user instead of making assumptions

### When to Ask the User

Use `AskUserQuestion` when:
- Multiple valid implementation approaches exist
- Requirements are ambiguous
- You're unsure about naming conventions
- External dependencies or API choices are needed
- The implementation could go multiple ways

```
Example: "Should I use async/await or threading for this operation?"
Example: "Which embedding model should I use: OpenAI or Google?"
```

### Verification Workflow

```
1. User requests feature/fix
2. READ existing relevant files first
3. SEARCH for similar patterns in codebase
4. ASK user if implementation approach is unclear
5. VERIFY imports and dependencies exist
6. WRITE code following existing patterns
7. TEST the code runs without import/attribute errors
8. VERIFY no unused imports or dead code
```

### Code Reusability Rules

1. **Follow existing patterns** - Look at similar files before creating new ones
2. **Use existing utilities** - Search for helper functions before writing new ones
3. **Consistent naming** - Match existing naming conventions in the codebase
4. **Single responsibility** - One class/function does one thing well

### Testing Requirements

1. **Test all new code** - Every new function/class needs tests
2. **Run tests before committing** - `python -m unittest discover tests -v`
3. **Test edge cases** - Empty inputs, None values, invalid parameters
4. **Mock external dependencies** - Don't call real APIs in unit tests

## Development Guidelines

### Creating Components

```python
class MyDataSource(DataSource):
    @property
    def source_type(self) -> str: return "custom"
    @property
    def source_id(self) -> str: return "my-source"
    def get_metadata(self): return {"name": "My Source"}
    def extract(self) -> RawData: return RawData(content="data", content_type="text", metadata={}, source=self)
    def validate(self) -> bool: return True

DataSourceRegistry.register('custom', 'my-impl', MyDataSource)
```

### Requirements

- **Tests required** for all new code (`src/foo.py` -> `tests/test_foo.py`)
- Python 3.10+, type hints, PEP 8, black formatting (line length: 100), Google-style docstrings

## Key Files Reference

| File | Purpose |
|------|---------|
| `src/openbench/core/abstractions.py` | Base interfaces (DataSource, Agent, OutputGenerator) |
| `src/openbench/core/chainable.py` | Composition primitives (Chain, Parallel, Conditional) |
| `src/openbench/core/registry.py` | Dynamic plugin registry with decorators |
| `src/openbench/core/providers.py` | Centralized Provider Service + credential encryption |
| `src/openbench/core/config.py` | Single source of truth Config + model registry |
| `src/openbench/core/layers.py` | L2 orchestrators (DataLayer, IntelligenceLayer, OutputLayer) |
| `src/openbench/core/state.py` | State management and checkpointing |
| `src/openbench/core/context.py` | Context management for workflows |
| `src/openbench/intelligence/base.py` | Framework-agnostic BaseAgent, ToolExecutor, AgentMemory, QueryRewriter |
| `src/openbench/intelligence/agents.py` | Pre-built agents (Research, Analysis, Content, Action, Meta) |
| `src/openbench/intelligence/llm_providers.py` | Concrete LLM providers (GeminiLLMProvider) |
| `src/openbench/intelligence/embeddings.py` | Embedding providers (Google, OpenAI) |
| `src/openbench/intelligence/planning.py` | TaskPlanner, TaskPlan (task decomposition) |
| `src/openbench/intelligence/memory.py` | PersistentMemory, SQLiteMemoryStore (persistent conversation) |
| `src/openbench/intelligence/persona.py` | Persona (SOUL/STYLE/AGENTS composer) — agent identity layer |
| `src/openbench/intelligence/skill.py` | Skill dataclass — SKILL.md + references/ + tools.py loader |
| `src/openbench/intelligence/skill_registry.py` | SkillRegistry — two-tier SDK + project skill resolution |
| `src/openbench/intelligence/layer.py` | AgentFactory for creating agents |
| `src/openbench/skills/data-context-extractor/` | SDK skill: CSV/TSV/XLSX/JSON reader with schema summary |
| `src/openbench/skills/data-visualization/` | SDK skill: ObChart-compatible chart dict builders |
| `src/openbench/skills/export-excel/` | SDK skill: single + multi-sheet .xlsx writer |
| `src/openbench/skills/query-explorer/` | SDK skill: filter / sort / group / distinct / top-N over records |
| `src/openbench/skills/drive-explorer/` | SDK skill: search/read Google Drive via an MCP server |
| `src/openbench/skills/memory-scratchpad/` | SDK skill: persistent user-editable markdown memory |
| `src/openbench/skills/pdf-tools/` | SDK skill: read / analyze / manipulate / generate PDFs |
| `src/openbench/skills/web-search/` | SDK skill: web search via Gemini Google Search grounding |
| `src/openbench/mcp/client.py` | Multi-server MCP client (transports, ToolHive discovery) |
| `src/openbench/mcp/server.py` | OpenBench MCP server wrapper (exposes tools over MCP) |
| `src/openbench/mcp/adapters.py` | Expose MCP tools through OpenBench's Tool abstraction |
| `src/openbench/mcp/tool_registry.py` | Load + wrap OpenBench function tools for MCP exposure |
| `src/openbench/mcp/policy.py` | Security policy for MCP tool access |
| `src/openbench/integrations/mcp/client.py` | MCPClient Protocol — surface for MCP-backed skills |
| `src/openbench/integrations/gdrive/` | Google Drive storage (backend, file/memory/session store, scratchpad, persona) |
| `src/openbench/integrations/firebase_auth/` | Firebase Auth (verifier, token store, Drive OAuth) |
| `src/openbench/core/storage.py` | StorageBackend ABC + storage provider plumbing |
| `src/openbench/testing/` | Public storage-backend contract test harness for implementers |
| `src/openbench/cli/commands/mcp.py` | CLI: MCP server/client commands |
| `src/openbench/data/sources/pdf.py` | PDF data source with chunking support |
| `src/openbench/data/sources/grounded_search.py` | Grounded search (Tavily, Google, DuckDuckGo) |
| `src/openbench/data/sources/langextract.py` | Structured entity extraction (Google LangExtract) |
| `src/openbench/data/stores/base.py` | Base DataStore abstraction, HybridSearchMixin, chunking |
| `src/openbench/data/stores/pinecone.py` | Pinecone vector store implementation |
| `src/openbench/adapters/google_adk.py` | Google ADK framework adapter |
| `src/openbench/workflows/workflow.py` | Named workflows with state |
| `src/openbench/chat/engine.py` | ChatEngine (Chainable) -- main chat orchestrator |
| `src/openbench/chat/session.py` | ChatSession, ChatMessage, Attachment |
| `src/openbench/chat/layer.py` | ChatLayer (L2) composable with other layers |
| `src/openbench/chat/a2ui/builder.py` | A2UIMessageBuilder -- JSONL generator |
| `src/openbench/chat/a2ui/catalog.py` | Custom A2UI catalog (ObChart, ObFileCard, ObCodeBlock, ObMarkdown, ObTable, ObCallout) |
| `src/openbench/chat/renderers/base.py` | ContentRenderer ABC + ContentRendererRegistry |
| `src/openbench/chat/transport/agui.py` | AGUIHandler -- AG-UI SSE event streaming |
| `src/openbench/chat/transport/agui_actions.py` | AGUIActionHandler -- REST for A2UI actions |
| `studio/chat-ui/src/index.ts` | @openbench/chat-ui public API exports |
| `studio/chat-ui/src/types.ts` | TypeScript interfaces for chat messages, A2UI, etc. |
| `studio/chat-ui/src/a2ui/surface-renderer.tsx` | A2UI adjacency list to React tree |
| `studio/chat-ui/src/a2ui/catalog.ts` | Component registry (standard + custom) |
| `studio/chat-ui/src/core/chat-store.ts` | Zustand store (sessions, messages, streaming) |

## Slash Commands

| Command | Description |
|---------|-------------|
| `/test` | Run test suite |
| `/lint` | Run linting and formatting |
| `/example` | Run an example workflow |
| `/check` | Run all quality checks (lint + type check + tests) |
| `/coverage` | Run tests with coverage report |

## Documentation Skills (Claude Code Auto-Invoked)

These are **Claude Code meta-skills** (authoring guidance for contributors)
— distinct from the OpenBench **Skill Layer** (runtime agent capabilities,
see `## Core Abstractions → Persona & Skill Layer` above).

| Skill | Triggers On |
|-------|-------------|
| **composing-workflows** | Creating workflows, L1/L2 composition, DAG patterns |
| **creating-abstractions** | Implementing DataSource, Agent, OutputGenerator, DataStore |
| **data-layer** | PineconeStore, chunking, embeddings, RAG, vector search |
| **intelligence-layer** | BaseAgent, LLM providers, tools, memory, RAG agents |
| **output-layer** | PDF, PPTX, Dashboard, Audio, Markdown generators |
| **chat-layer** | ChatEngine, A2UI v0.10 builder, content renderers, AG-UI transport, ChatLayer L2 |
| **chat-ui** | @openbench/chat-ui React SDK, A2UI v0.10 components (18 standard + 6 custom), hooks, design system |
| **adapters** | LangChain, CrewAI, AG2, E2B, Google ADK adapters |
| **testing-openbench** | Writing tests, test patterns, coverage |

## Design System

**Notion-inspired. Monochrome. Icon-driven. No emojis.** Applies to all UI/UX across the project.

- **Colors**: Carbon gray scale (#1a1a1a on #ffffff), blue accent for links only
- **Icons**: Lucide React -- 16px inline, 18px buttons, 1.5px stroke, inherit color
- **Typography**: System font stack, 14px base (--ob-text-base)
- **Borders**: 1px solid rgba(0,0,0,0.08) -- subtle, not heavy shadows
- **Spacing**: 4px base unit, all spacing multiples of 4
- **Shadows**: Almost none -- only modals and dropdowns
- **Transitions**: 150ms ease for micro-interactions

**Rules:**
- Never use emojis -- use Lucide icons for all visual indicators
- Never use colored icons except for status (error/success/warning)
- Never use heavy shadows or gradients
- All CSS via custom properties with `--ob-` prefix
- Dark mode via `[data-theme="dark"]` attribute

Full design tokens: [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md)

## Frontend Build (studio/chat-ui)

```bash
cd studio/chat-ui
pnpm install              # Install dependencies
pnpm dev                  # Dev server
pnpm build                # Build library (ESM + .d.ts)
pnpm tsc --noEmit         # Type check
pnpm vitest               # Run tests
```

## Additional Documentation

- [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) - Installation and first workflow
- [docs/API.md](docs/API.md) - Complete API reference
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - Architecture overview
- [docs/MENTAL_MODEL.md](docs/MENTAL_MODEL.md) - Four pillars (MCP / Skill / Agentic / Output) + decision matrix
- [docs/MCP.md](docs/MCP.md) - MCP client/server usage guide
- [docs/MCP_ARCHITECTURE.md](docs/MCP_ARCHITECTURE.md) - MCP pillar architecture
- [docs/STORAGE.md](docs/STORAGE.md) - Storage backends (Drive, SQLite) + StorageBackend ABC
- [docs/CUSTOM-BACKEND.md](docs/CUSTOM-BACKEND.md) - Implementing a custom storage backend
- [docs/CHAT_UI_ARCHITECTURE.md](docs/CHAT_UI_ARCHITECTURE.md) - Chat UI SDK architecture
- [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) - Design tokens and visual language
- [examples/README.md](examples/README.md) - Example usage patterns

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
