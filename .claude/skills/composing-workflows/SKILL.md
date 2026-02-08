---
name: composing-workflows
description: Creating and composing OpenBench workflows with L1/L2 patterns, DAG structures, and chainable operators. Use when building workflows with | or & operators, creating DAG patterns, or working with DataLayer/IntelligenceLayer/OutputLayer composition.
---

# Composing Workflows

OpenBench uses chainable operators for workflow composition.

## Core Operators

```python
# Sequential: A -> B -> C
workflow = step_a | step_b | step_c

# Parallel: [A, B, C] run concurrently
workflow = step_a & step_b & step_c

# Complex DAG: A -> (B & C) -> D
workflow = step_a | Parallel([step_b, step_c]) | step_d
```

## L1 vs L2 Composition

**L1 (Component-Level):** Compose within a layer
```python
sources = pdf_source | api_source | csv_source
agents = research_agent | analysis_agent | content_agent
outputs = pdf_gen & pptx_gen & audio_gen
```

**L2 (System-Level):** Compose entire layers
```python
from openbench.core import DataLayer, IntelligenceLayer, OutputLayer

pipeline = (
    DataLayer(sources=sources, stores=[vector_store])
    | IntelligenceLayer(agents=agents)
    | OutputLayer(generators=outputs)
)
```

## Framework Adapters

Wrap external agents (LangChain, CrewAI, Google ADK):

```python
from openbench.adapters import GoogleADKAdapter

google_adapter = GoogleADKAdapter(
    model="gemini-2.5-flash",  # Use 2.5+ models
    system_instruction="You are a document analyst."
)

workflow = (
    DataLayer(sources=PDFSource("doc.pdf"))
    | IntelligenceLayer(agents=google_adapter)
    | OutputLayer(generators=PDFGenerator())
)
```

## Conditional & Router

```python
from openbench.core import Conditional, Router

# Binary branching
workflow = Conditional(
    condition=lambda x: x.get("type") == "research",
    true_branch=research_agent,
    false_branch=analysis_agent
)

# Multi-way routing
workflow = Router(
    route_fn=lambda x: x.get("format", "pdf"),
    routes={"pdf": pdf_gen, "pptx": pptx_gen, "html": html_gen},
    default=pdf_gen
)
```

## Workflow with State

```python
from openbench.workflows import Workflow

workflow = Workflow(
    name="my-workflow",
    chain=pipeline,
    checkpoints=True,
    metadata={"project": "Q1 2026"}
)

result = workflow.run(input_data)
```

## Anti-Patterns

**DO NOT:**
- Use `Parallel.invoke()` expecting true concurrency - it runs sequentially. Use `ainvoke()` for true parallelism
- Create deeply nested chains without checkpoints - use `Workflow` with `checkpoints=True` for long pipelines
- Put business logic in Lambda - use proper Agent or DataSource instead
- Mix L1 and L2 in the same chain level - keep layers separate
- Assume Parallel output order matches input order when using `ainvoke()` - use `invoke()` if order matters

## Cross-References

- **Intelligence Layer**: Agents used in `IntelligenceLayer` → see `intelligence-layer` skill
- **Data Layer**: DataSources and stores used in `DataLayer` → see `data-layer` skill
- **Output Layer**: Generators used in `OutputLayer` → see `output-layer` skill
- **Adapters**: External framework agents used via adapters → see `adapters` skill
- **Creating Abstractions**: Custom Chainable implementations → see `creating-abstractions` skill

## Best Practices

1. Use L1 for component composition within a layer
2. Use L2 for system composition across layers
3. Enable checkpointing for long workflows
4. Use Parallel for independent operations
5. Use Conditional for binary branching, Router for multi-way

For detailed examples, see `examples/core/orchestration_demo.py`
