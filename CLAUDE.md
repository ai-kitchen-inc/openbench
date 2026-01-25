# CLAUDE.md

Guidance for Claude Code when working with this repository.

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
├── tests/                       # Test suite (194 tests)
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
# Install
pip install -e .                 # Core
pip install -e ".[all]"          # All features
pip install -e ".[security]"     # With encryption

# Test
python -m unittest discover tests -v
pytest tests/ --cov=openbench

# Examples
python examples/sustainability_report.py
python examples/core_abstractions_demo.py

# Code quality
black src/ tests/ examples/
ruff check src/ tests/
mypy src/openbench/
```

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
| **creating-abstractions** | Implementing DataSource, Agent, OutputGenerator |
| **testing-openbench** | Writing tests, test patterns, coverage |

## Additional Documentation

- [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) - Installation and first workflow
- [docs/API.md](docs/API.md) - Complete API reference
- [docs/architecture.md](docs/architecture.md) - Architecture overview
- [examples/README.md](examples/README.md) - Example usage patterns
