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

## Positioning & Classification

**OpenBench is a Workflow Orchestrator + Universal Control Plane for Agentic AI.**

It is NOT an agent itself, but a platform for coordinating agents from various frameworks.

### What OpenBench IS

| Role | Description |
|------|-------------|
| **Workflow Orchestrator** | Compose steps with `\|` and `&` operators |
| **Universal Control Plane** | Connect any framework via adapters |
| **Data Pipeline** | ETL for AI (Extract -> Transform -> Load) |
| **Multi-Agent Coordinator** | Chain multiple agents from different frameworks |

### What OpenBench is NOT

| Not This | Because |
|----------|---------|
| **LLM Agent** | Does not execute reasoning, only orchestrates |
| **Agent Framework** | Does not compete with LangChain/CrewAI, connects them |
| **Agentic AI** | Not autonomous, user defines workflow |

### AI Systems Taxonomy

```
Level 1: LLM (Base Model)
         └── GPT-4, Claude, Gemini - text in, text out

Level 2: LLM Agent (Single Agent)
         └── LLM + Tools + Memory + Reasoning Loop
         └── Frameworks: LangChain Agent, Google ADK Agent

Level 3: Multi-Agent System (Agentic AI)
         └── Multiple LLM Agents collaborating
         └── Examples: CrewAI crews, AutoGen teams

Level 4: Workflow Orchestrator  <-- OPENBENCH
         └── Coordinates agents + data + outputs
         └── Framework agnostic, DAG-based composition

Level 5: AI Platform
         └── Full infrastructure (compute, storage, monitoring)
         └── Examples: AWS Bedrock, Google Vertex AI
```

### Analogy

OpenBench is like **"Kubernetes for AI Agents"** - it handles coordination, not execution.

| System | Role |
|--------|------|
| **Kubernetes** | Orchestrates containers, doesn't run code |
| **Airflow** | Orchestrates tasks, doesn't process data |
| **OpenBench** | Orchestrates AI agents, doesn't do reasoning |

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
│   ├── intelligence/            # AI agent layer
│   │   ├── base.py              # Framework-agnostic BaseAgent, ToolExecutor, AgentMemory
│   │   ├── agents.py            # Agent implementations (Research, Analysis, Content)
│   │   └── layer.py             # AgentFactory for creating agents
│   ├── output/                  # Output generation layer
│   │   ├── generators.py        # Output generator implementations
│   │   └── layer.py             # OutputFactory for generating outputs
│   ├── workflows/               # Workflow system
│   │   └── workflow.py          # Named workflows with state management
│   ├── cli/                     # Command-line interface
│   │   ├── main.py              # CLI entry point
│   │   └── commands/            # CLI command groups (init, data, agent, workflow, provider, models)
│   └── utils/                   # Utilities
├── tests/                       # Test suite (320 tests)
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
```

### Registry and Workflows

```python
DataSourceRegistry.register('pdf', 'custom', MyPDFSource)
source = DataSourceRegistry.create('pdf', 'custom', path='./docs')

workflow = Workflow(name="report", chain=data | intelligence | output, checkpoints=True)
result = workflow.run({"project": "Q1 2026"})
```

## Build and Development

```bash
# Use Python 3.12 environment
conda activate py312

# Install
pip install -e .                 # Core
pip install -e ".[all]"          # All features
pip install -e ".[security]"     # With encryption

# Test
python -m unittest discover tests -v
pytest tests/ --cov=openbench

# Examples
python examples/workflows/sustainability_report.py
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
└── workflows/      # Complete E2E workflow examples
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
| `src/openbench/intelligence/base.py` | Framework-agnostic BaseAgent, ToolExecutor, AgentMemory |
| `src/openbench/workflows/workflow.py` | Named workflows with state |

## Slash Commands

| Command | Description |
|---------|-------------|
| `/test` | Run test suite |
| `/lint` | Run linting and formatting |
| `/example` | Run an example workflow |

## Skills (Auto-Invoked)

| Skill | Triggers On |
|-------|-------------|
| **composing-workflows** | Creating workflows, L1/L2 composition, DAG patterns |
| **creating-abstractions** | Implementing DataSource, Agent, OutputGenerator, DataStore |
| **data-layer** | PineconeStore, chunking, embeddings, RAG, vector search |
| **testing-openbench** | Writing tests, test patterns, coverage |

## Additional Documentation

- [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) - Installation and first workflow
- [docs/API.md](docs/API.md) - Complete API reference
- [docs/architecture.md](docs/architecture.md) - Architecture overview
- [examples/README.md](examples/README.md) - Example usage patterns
