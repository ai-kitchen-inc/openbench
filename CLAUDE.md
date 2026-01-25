# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**OpenBench** is an **open-source Python SDK** for building composable AI workflows. It provides a unified framework for orchestrating data extraction, AI processing, and output generation.

**Tagline:** Build. Orchestrate. Export. Scale.

### Core Concepts ("AI Kitchen" Paradigm)

- **DataSource** (Pantry) - Raw data: PDFs, APIs, databases, CSVs
- **Agent** (Chef) - AI that processes and reasons over data
- **OutputGenerator** (Dish) - Generated artifacts: PDF, PPTX, audio

### Architecture: Three-Layer Model

```
┌─────────────────────────────────────────────────────────┐
│                     OUTPUT LAYER                        │
│  Generate outputs: PDF, PowerPoint, Audio, Dashboards  │
│  OutputGenerator abstraction                           │
└─────────────────────────────────────────────────────────┘
                            ▲
                            │
┌─────────────────────────────────────────────────────────┐
│                  INTELLIGENCE LAYER                     │
│  Execute AI tasks: Research, Analysis, Content         │
│  Agent & LLMProvider abstractions                      │
└─────────────────────────────────────────────────────────┘
                            ▲
                            │
┌─────────────────────────────────────────────────────────┐
│                      DATA LAYER                         │
│  Extract and index from sources                        │
│  DataSource & DataStore abstractions                   │
└─────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Everything is Chainable** - All components implement `invoke()` and support `|` and `&` operators
2. **Composition Over Configuration** - Build workflows by composing components, not flags
3. **Implementation Independence** - Swap providers (OpenAI ↔ Anthropic) without code changes
4. **Two-Level Orchestration** - L1 (components) and L2 (layers) composition
5. **DAG Workflows** - Express complex directed acyclic graphs in code

## Project Structure

```
openbench/
├── src/openbench/
│   ├── __init__.py              # Package exports
│   ├── core/                    # Core abstractions and infrastructure
│   │   ├── __init__.py          # Public API exports
│   │   ├── abstractions.py      # Base interfaces (DataSource, Agent, OutputGenerator)
│   │   ├── chainable.py         # DAG workflow composition (Chain, Parallel, Conditional)
│   │   ├── registry.py          # Provider registration factories
│   │   ├── layers.py            # L2 system-level orchestrators
│   │   └── state.py             # State management & checkpointing
│   ├── intelligence/            # AI agent layer
│   │   ├── agents.py            # Agent implementations
│   │   └── layer.py             # Intelligence layer orchestrator
│   ├── output/                  # Output generation layer
│   │   ├── generators.py        # Output generator implementations
│   │   └── layer.py             # Output layer orchestrator
│   ├── workflows/               # Workflow system
│   │   └── workflow.py          # Named workflows with state management
│   ├── cli/                     # Command-line interface
│   │   ├── main.py              # CLI entry point
│   │   └── commands/            # CLI command groups (init, data, agent, workflow, etc.)
│   └── utils/                   # Utilities
├── tests/                       # Test suite (77 tests)
├── examples/                    # Example workflows
├── docs/                        # Documentation
├── pyproject.toml               # Python project configuration
└── requirements.txt             # Dependencies
```

## Core Abstractions

### Chainable Interface

All components implement the `Chainable` interface:

```python
class Chainable(ABC):
    def invoke(self, input: Any, config: Optional[RunnableConfig] = None) -> Any:
        """Execute this component"""
        pass

    def __or__(self, other: Chainable) -> Chain:
        """Pipe operator: self | other (sequential)"""
        return Chain([self, other])

    def __and__(self, other: Chainable) -> Parallel:
        """And operator: self & other (parallel)"""
        return Parallel([self, other])
```

### Composition Patterns

```python
# Sequential: A → B → C
workflow = step_a | step_b | step_c

# Parallel: [A, B, C] concurrently
workflow = step_a & step_b & step_c

# Complex DAG: A → (B & C) → D
workflow = step_a | Parallel([step_b, step_c]) | step_d

# Conditional branching
workflow = Conditional(
    condition=lambda x: x["type"] == "research",
    true_branch=research_agent,
    false_branch=analysis_agent
)
```

### L1 vs L2 Composition

**L1 (Component-level):**
```python
# Compose individual components
sources = source1 | source2 | source3
agents = agent1 | agent2
outputs = Parallel([pdf_gen, pptx_gen])
```

**L2 (System-level):**
```python
# Compose into layers
data_layer = DataLayer(sources=sources, stores=[vector_store])
intelligence_layer = IntelligenceLayer(agents=agents)
output_layer = OutputLayer(generators=outputs)

# Then compose layers
workflow = data_layer | intelligence_layer | output_layer
```

### Registry Pattern

```python
# Register implementation
DataSourceRegistry.register('pdf', 'custom', MyPDFSource)

# Create instance - swap providers easily
source = DataSourceRegistry.create('pdf', 'custom', path='./docs')
```

### Named Workflows with State

```python
from openbench.workflows import Workflow
from openbench.core import LocalStateStore

workflow = Workflow(
    name="sustainability-report",
    chain=data_layer | intelligence_layer | output_layer,
    state_store=LocalStateStore(base_path="./workflow_state"),
    checkpoints=True
)

result = workflow.run({"project": "Q1 2026"})
```

## Build and Development Commands

### Installation

```bash
# Install in development mode
pip install -e .

# Install with all dependencies
pip install -e ".[all]"

# Install specific extras
pip install -e ".[dev]"          # Testing and dev tools
pip install -e ".[data]"         # Data processing (pandas, chromadb)
pip install -e ".[intelligence]" # LLM providers (openai, anthropic)
pip install -e ".[output]"       # Output generation (reportlab, python-pptx)
```

### Running Tests

```bash
# Run all tests
python -m unittest discover tests -v

# Run specific test file
python -m unittest tests.test_abstractions -v
python -m unittest tests.test_chainable -v

# Run with pytest (if installed)
pytest tests/ -v
pytest tests/ --cov=openbench  # With coverage
```

### Running Examples

```bash
# Complete sustainability report workflow
python examples/sustainability_report.py

# Core abstractions demo
python examples/core_abstractions_demo.py

# L1/L2 orchestration demo
python examples/orchestration_demo.py
```

### Code Quality

```bash
# Format code
black src/ tests/ examples/

# Lint
ruff check src/ tests/

# Type checking
mypy src/openbench/
```

## Development Guidelines

### Creating New Components

1. **Extend the abstract base class:**

```python
from openbench.core import DataSource, RawData

class MyDataSource(DataSource):
    @property
    def source_type(self) -> str:
        return "custom"

    @property
    def source_id(self) -> str:
        return "my-source"

    def get_metadata(self) -> Dict[str, Any]:
        return {"name": "My Source"}

    def extract(self) -> RawData:
        return RawData(content="data", content_type="text", metadata={}, source=self)

    def validate(self) -> bool:
        return True
```

2. **Register the implementation:**

```python
from openbench.core import DataSourceRegistry
DataSourceRegistry.register('custom', 'my-impl', MyDataSource)
```

3. **Write tests immediately:**

```python
import unittest
from my_module import MyDataSource

class TestMyDataSource(unittest.TestCase):
    def test_extract(self):
        source = MyDataSource()
        result = source.extract()
        self.assertIsNotNone(result.content)
```

### Test-Driven Development

**Every new code MUST include unit tests.**

```
Test file conventions:
  src/openbench/core/foo.py   → tests/test_foo.py
  src/openbench/workflows/    → tests/test_workflow.py
```

### Code Style

- **Python 3.10+** required
- Use **type hints** for all public functions
- Follow **PEP 8** style guide
- Use **black** for formatting (line length: 100)
- Use **Google-style docstrings**

## Key Files Reference

| File | Purpose |
|------|---------|
| `src/openbench/core/abstractions.py` | Base interfaces (DataSource, Agent, OutputGenerator) |
| `src/openbench/core/chainable.py` | Composition primitives (Chain, Parallel, Conditional) |
| `src/openbench/core/registry.py` | Registry pattern for all abstractions |
| `src/openbench/core/layers.py` | L2 orchestrators (DataLayer, IntelligenceLayer, OutputLayer) |
| `src/openbench/core/state.py` | State management and checkpointing |
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
