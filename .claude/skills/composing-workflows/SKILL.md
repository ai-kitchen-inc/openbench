---
name: composing-workflows
description: Creating and composing OpenBench workflows with L1/L2 patterns, DAG structures, and chainable operators
---

# Composing Workflows Skill

This skill is auto-invoked when working with workflow composition, DAG patterns, or L1/L2 orchestration.

## Triggers

- Creating workflows with `|` or `&` operators
- Building DAG (Directed Acyclic Graph) structures
- Working with Chain, Parallel, Conditional, Router
- L1 component composition
- L2 layer composition
- Using FrameworkAdapters in workflows
- State management and checkpointing

## Core Patterns

### Sequential Composition (Pipe Operator)

```python
# A → B → C
workflow = step_a | step_b | step_c

# Equivalent to:
workflow = Chain([step_a, step_b, step_c])
```

### Parallel Composition (And Operator)

```python
# [A, B, C] run concurrently
workflow = step_a & step_b & step_c

# Equivalent to:
workflow = Parallel([step_a, step_b, step_c])
```

### Complex DAG

```python
# A → (B & C) → D
#     ↙     ↘
# A → B       C → D
#     ↘     ↗
workflow = step_a | Parallel([step_b, step_c]) | step_d
```

### Conditional Branching

```python
from openbench.core import Conditional

workflow = Conditional(
    condition=lambda x: x.get("type") == "research",
    true_branch=research_agent,
    false_branch=analysis_agent
)
```

### Multi-way Routing

```python
from openbench.core import Router

workflow = Router(
    route_fn=lambda x: x.get("format", "pdf"),
    routes={
        "pdf": pdf_generator,
        "pptx": pptx_generator,
        "html": html_generator,
    },
    default=pdf_generator
)
```

## Using Framework Adapters

OpenBench is a universal control plane - bring agents from ANY framework:

```python
from openbench.core import DataLayer, IntelligenceLayer, OutputLayer
from openbench.adapters import GoogleADKAdapter, LangChainAdapter
from openbench.data.sources import PDFSource
from openbench.output.generators import PDFGenerator

# Wrap existing Google Gemini
google_adapter = GoogleADKAdapter(
    model="gemini-1.5-pro",
    system_instruction="You are a document analyst."
)

# Or wrap your LangChain agent
langchain_adapter = LangChainAdapter(my_langchain_agent)

# Use in workflow - same pattern regardless of framework
workflow = (
    DataLayer(sources=PDFSource("doc.pdf"))
    | IntelligenceLayer(agents=google_adapter)
    | OutputLayer(generators=PDFGenerator())
)

result = workflow.invoke({"goal": "Summarize this document"})
```

### Mixed Framework Workflows

Combine agents from different frameworks in one workflow:

```python
from openbench.adapters import GoogleADKAdapter, LangChainAdapter, CrewAIAdapter

# Research with Google Gemini, Analysis with LangChain, Content with CrewAI
workflow = (
    DataLayer(sources=sources)
    | IntelligenceLayer(agents=(
        GoogleADKAdapter(model="gemini-pro")      # Research
        | LangChainAdapter(analysis_agent)         # Analysis
        | CrewAIAdapter(content_crew)              # Content
    ))
    | OutputLayer(generators=pdf_gen)
)
```

## L1 vs L2 Composition

### L1: Component-Level

Compose individual components within a layer:

```python
# Data sources: extract from multiple sources
sources = pdf_source | api_source | csv_source

# Or parallel extraction:
sources = Parallel([pdf_source, api_source, csv_source])

# Agents: sequential processing pipeline
agents = research_agent | analysis_agent | content_agent

# Outputs: generate multiple formats in parallel
outputs = pdf_gen & pptx_gen & audio_gen
```

### L2: System-Level

Compose entire layers:

```python
from openbench.core import DataLayer, IntelligenceLayer, OutputLayer

# Create layers with L1 workflows inside
data_layer = DataLayer(sources=sources, stores=[vector_store])
intelligence_layer = IntelligenceLayer(agents=agents)
output_layer = OutputLayer(generators=outputs)

# Compose layers into E2E pipeline
pipeline = data_layer | intelligence_layer | output_layer
```

## Workflow with State

```python
from openbench.workflows import Workflow
from openbench.core import LocalStateStore

workflow = Workflow(
    name="my-workflow",
    chain=pipeline,
    state_store=LocalStateStore(base_path="./state"),
    checkpoints=True,
    metadata={"project": "Q1 2026"}
)

# Execute
result = workflow.run(input_data)

# Resume from checkpoint
result = workflow.resume(workflow_id="abc123")

# Check status
state = workflow.status(workflow_id="abc123")
```

## Best Practices

1. **Use L1 for component composition** - Keep related components together
2. **Use L2 for system composition** - Separate concerns by layer
3. **Enable checkpointing for long workflows** - Allows resume on failure
4. **Use Parallel for independent operations** - Improves performance
5. **Use Conditional for branching logic** - Cleaner than if/else
6. **Use Router for multi-way routing** - Better than nested conditionals

## Common Patterns

### Data Ingestion Pattern
```python
# Parallel ingestion, then merge
sources = Parallel([pdf_source, api_source, csv_source])
data_layer = DataLayer(sources=sources, stores=[vector_store])
```

### Sequential Agent Pipeline
```python
# Research → Analysis → Content
agents = Chain([
    ResearchAgent(depth="comprehensive"),
    AnalysisAgent(methods=["statistical", "trend"]),
    ContentAgent(style="executive")
])
```

### Parallel Output Generation
```python
# Generate all formats simultaneously
outputs = Parallel([
    PDFGenerator(template="report"),
    PPTXGenerator(template="executive"),
    AudioGenerator(voice="natural")
])
```

### Complete E2E Workflow
```python
workflow = Workflow(
    name="complete-analysis",
    chain=(
        DataLayer(sources=Parallel([s1, s2, s3]), stores=[store])
        | IntelligenceLayer(agents=a1 | a2 | a3)
        | OutputLayer(generators=g1 & g2)
    ),
    checkpoints=True
)
```
