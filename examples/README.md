# OpenBench Examples

This directory contains production-ready examples demonstrating OpenBench's composable abstractions and workflow patterns.

## Examples

### 1. Core Abstractions Demo (`core_abstractions_demo.py`)

Demonstrates the foundational Chainable abstractions and composition patterns:
- Custom DataSource, Agent, and OutputGenerator implementations
- Registry pattern for provider selection
- Sequential workflows (`A | B | C`)
- Parallel workflows (`A & B & C`)
- Conditional branching
- Router (multi-way routing)
- Complex DAG structures
- Stateful workflows with checkpointing
- Configuration-driven workflow creation

**Run it:**
```bash
python examples/core_abstractions_demo.py
```

### 2. L1/L2 Orchestration Demo (`orchestration_demo.py`)

Shows two-level composition: components (L1) into systems (L2):
- L1 component composition: `source1 | source2`
- L2 layer composition: `DataLayer | IntelligenceLayer | OutputLayer`
- Complex DAG workflows within layers
- End-to-end workflow execution
- `create_workflow()` helper for rapid prototyping

**Run it:**
```bash
python examples/orchestration_demo.py
```

### 3. Sustainability Report (`sustainability_report.py`)

Complete real-world example generating ESG/sustainability reports:
- Parallel data extraction from multiple sources (PDF & API & CSV)
- Sequential multi-agent processing (Research → Analysis → Content)
- Parallel output generation (PDF & PowerPoint)
- Named workflow with state management and checkpointing
- Complete end-to-end demonstration

**Use case:** Sustainability consultants, ESG analysts

**Run it:**
```bash
python examples/sustainability_report.py
```

### 4. Framework Adapters Demo (`framework_adapters_demo.py`)

Demonstrates OpenBench as a universal control plane for multiple AI frameworks:
- FrameworkAdapter: Minimal interface for integrating any framework
- LangChain, AG2, CrewAI, E2B adapter examples
- Mixed-framework workflows (combine agents from different frameworks)
- Zero migration cost - use existing agents as-is
- Custom adapter creation

**Key concept:** Bring your own agents from ANY framework without rewriting them.

**Run it:**
```bash
python examples/framework_adapters_demo.py
```

## Creating Your Own Workflow

Use these examples as templates:

1. Copy an example file
2. Implement custom DataSource, Agent, or OutputGenerator
3. Compose components using `|` (sequential) or `&` (parallel)
4. Wrap in Workflow for state management
5. Run and iterate

## Common Patterns

### Sequential Workflow

```python
from openbench.core import DataLayer, IntelligenceLayer, OutputLayer

# Compose layers sequentially: Data → Intelligence → Output
workflow = data_layer | intelligence_layer | output_layer

# Execute
result = workflow.invoke({"query": "analyze sustainability"})
```

### Parallel Processing

```python
from openbench.core import Parallel

# Extract from multiple sources concurrently
data_layer = DataLayer(
    sources=Parallel([pdf_source, api_source, csv_source])
)

# Generate multiple outputs concurrently
output_layer = OutputLayer(
    generators=pdf_generator & pptx_generator
)
```

### Named Workflow with Checkpointing

```python
from openbench.workflows import Workflow
from openbench.core import LocalStateStore

workflow = Workflow(
    name="my-workflow",
    chain=data_layer | intelligence_layer | output_layer,
    state_store=LocalStateStore(base_path="./workflow_state"),
    checkpoints=True
)

result = workflow.run({"project": "Analysis"})
```

## Need Help?

- [Getting Started Guide](../docs/GETTING_STARTED.md)
- [API Reference](../docs/API.md)
- [Architecture Overview](../docs/architecture.md)
- [GitHub Issues](https://github.com/ai-kitchen-inc/openbench/issues)
