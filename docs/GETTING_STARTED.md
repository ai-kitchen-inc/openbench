# Getting Started with OpenBench

---

## Installation

```bash
git clone https://github.com/ai-kitchen-inc/openbench.git
cd openbench
pip install -e .

# Verify
python -c "from openbench.core import Chainable; print('OpenBench installed')"
```

**Optional extras:**
```bash
pip install -e ".[dev]"          # Testing/dev tools
pip install -e ".[all]"          # All features
pip install -e ".[security]"     # Credential encryption
```

---

## Quick Test

```bash
python -m unittest discover tests -v
# Expected: 955 Python tests + 193 TypeScript tests
```

---

## Your First Workflow

**Core Components (L1):** `DataSource`, `Agent`, `OutputGenerator`

**System Layers (L2):** `DataLayer`, `IntelligenceLayer`, `OutputLayer`

**Composition:** `|` (sequential), `&` (parallel), `Workflow` (stateful)

### Example

```python
from openbench.core import (
    DataLayer, IntelligenceLayer, OutputLayer,
    Parallel
)

# Create layers
data_layer = DataLayer(sources=my_source)
intelligence_layer = IntelligenceLayer(agents=my_agent)
output_layer = OutputLayer(generators=my_generator)

# Compose into end-to-end workflow
workflow = data_layer | intelligence_layer | output_layer

# Execute
result = workflow.invoke({"query": "analyze sustainability"})
```

---

## Run the Examples

```bash
python examples/core/core_abstractions_demo.py       # Core abstractions, registry, composition
python examples/core/orchestration_demo.py           # L1/L2 two-level composition
python examples/workflows/reports/sustainability_report.py  # Complete E2E workflow
```

---

## Core Concepts

### 1. Everything is Chainable

```python
# Sequential
workflow = step_a | step_b | step_c

# Parallel
workflow = Parallel([step_a, step_b, step_c])

# Combined: A -> (B & C) -> D
workflow = step_a | Parallel([step_b, step_c]) | step_d
```

### 2. L1 vs L2 Composition

```python
# L1: Compose components
sources = source1 | source2 | source3
agents = agent1 | agent2

# L2: Compose into layers
workflow = DataLayer(sources=sources) | IntelligenceLayer(agents=agents) | OutputLayer(generators=outputs)
```

### 3. Registry Pattern

```python
DataSourceRegistry.register('pdf', 'custom', MyPDFSource)
source = DataSourceRegistry.create('pdf', 'custom', path='./docs')
```

### 4. Provider Configuration

```python
from openbench.core import get_provider_service, ProviderConfig, ProviderType

service = get_provider_service()
service.configure(ProviderConfig(
    name="my-openai",
    provider_type=ProviderType.LLM,
    provider="openai",
    plugin_type="chat",
    credentials={"api_key": "sk-..."},  # Encrypted at rest
    is_default=True
))
llm = service.resolve(ProviderType.LLM)
```

### 5. Named Workflows with State

```python
workflow = Workflow(
    name="sustainability-report",
    chain=data_layer | intelligence_layer | output_layer,
    state_store=LocalStateStore(base_path="./workflow_state"),
    checkpoints=True
)
result = workflow.run({"project": "ESG Analysis"})
```

---

## Build Your Own

### 1. Create Custom Components

```python
from openbench.core import DataSource, RawData

class MyDataSource(DataSource):
    @property
    def source_type(self) -> str: return "custom"
    @property
    def source_id(self) -> str: return "my-source"
    def get_metadata(self): return {"name": "My Source"}
    def extract(self) -> RawData:
        return RawData(content="data", content_type="text", metadata={}, source=self)
    def validate(self) -> bool: return True
```

### 2. Compose and Execute

```python
workflow = DataLayer(sources=my_source) | IntelligenceLayer(agents=my_agent) | OutputLayer(generators=my_generator)
result = workflow.invoke({})
```

### 3. Register for Reuse

```python
DataSourceRegistry.register('custom', 'my-impl', MyDataSource)
source = DataSourceRegistry.create('custom', 'my-impl')
```

---

## Testing

```bash
python -m unittest discover tests -v
python -m unittest tests.test_abstractions -v  # Specific file
```

**Test coverage (955 Python, 193 TypeScript):**
- Core abstractions (16), Registry (45), Chainable (18)
- L2 layers (17), Workflow (15), Provider service (32)
- Config (20), Intelligence base (31)
- Chat engine (45), Chat session, A2UI builder, Content renderers
- TypeScript: A2UI components, data-binding, functions, store, transport

---

## Status

**Core SDK Complete:** Core abstractions, plugin registry, chainable composition, L2 layers, workflows, Provider Service, Config system, Agent interface, framework adapters, embeddings.

**Chat Layer Complete:** ChatEngine, A2UI v0.10 builder, content renderers (text, chart, form, file), SSE + REST transport, ChatLayer L2.

**Chat UI SDK Complete:** @openbench/chat-ui React SDK — 18 standard + 4 custom A2UI components, hooks, SSE transport, Zustand store, Notion-inspired design system.

---

## Common Patterns

```python
# Sequential
workflow = extract | transform | load

# Parallel
workflow = Parallel([process_a, process_b, process_c])

# DAG: A -> (B & C & D) -> E
workflow = step_a | Parallel([step_b, step_c, step_d]) | step_e

# Conditional
workflow = Conditional(
    condition=lambda x: x["confidence"] > 0.8,
    true_branch=fast_path,
    false_branch=detailed_path
)

# Advanced RAG (Query Rewriter + Multi-Hop + Hybrid Search)
from openbench.intelligence.base import BaseAgent
from openbench.data.stores.pinecone import PineconeStore

store = PineconeStore(index_name="knowledge", hybrid_search=True, vector_weight=0.7)
agent = BaseAgent(
    goal="Research thoroughly using the knowledge base",
    store=store,
    query_rewriter=True,   # LLM-based query enhancement
    multi_hop_rag=True,    # Agent-driven iterative retrieval
)
```

---

## Troubleshooting

```bash
# Import errors: reinstall
pip uninstall openbench && pip install -e .

# Debug test failures
python -m unittest tests.test_workflow.TestWorkflow.test_workflow_creation -v

# Clean state files
rm -rf workflow_state/
```

---

## Next Steps

- [API Reference](API.md)
- [Architecture](ARCHITECTURE.md)
- [Examples](../examples/)
- [Discord](https://discord.com/users/openbench.ai)
- [GitHub](https://github.com/ai-kitchen-inc/openbench)
