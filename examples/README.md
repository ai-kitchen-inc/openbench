# OpenBench Examples

This directory contains production-ready examples demonstrating OpenBench's composable abstractions and workflow patterns.

## Directory Structure

```
examples/
├── core/                    # Core concepts and abstractions
│   ├── core_abstractions_demo.py
│   └── orchestration_demo.py
├── adapters/                # Framework adapter examples
│   └── framework_adapters_demo.py
├── workflows/               # Complete end-to-end workflows
│   ├── pdf_google_adk_workflow.py
│   └── sustainability_report.py
└── README.md
```

## Core Examples (`core/`)

### 1. Core Abstractions Demo (`core/core_abstractions_demo.py`)

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
python examples/core/core_abstractions_demo.py
```

### 2. L1/L2 Orchestration Demo (`core/orchestration_demo.py`)

Shows two-level composition: components (L1) into systems (L2):
- L1 component composition: `source1 | source2`
- L2 layer composition: `DataLayer | IntelligenceLayer | OutputLayer`
- Complex DAG workflows within layers
- End-to-end workflow execution
- `create_workflow()` helper for rapid prototyping

**Run it:**
```bash
python examples/core/orchestration_demo.py
```

## Adapter Examples (`adapters/`)

### 3. Framework Adapters Demo (`adapters/framework_adapters_demo.py`)

Demonstrates OpenBench as a universal control plane for multiple AI frameworks:
- FrameworkAdapter: Minimal interface for integrating any framework
- LangChain, AG2, CrewAI, E2B adapter examples
- Mixed-framework workflows (combine agents from different frameworks)
- Zero migration cost - use existing agents as-is
- Custom adapter creation

**Key concept:** Bring your own agents from ANY framework without rewriting them.

**Run it:**
```bash
python examples/adapters/framework_adapters_demo.py
```

## Workflow Examples (`workflows/`)

### 4. PDF → Google ADK → PDF Workflow (`workflows/pdf_google_adk_workflow.py`)

Complete end-to-end workflow demonstrating:
- PDF text extraction with PDFSource
- AI processing with Google Gemini via GoogleADKAdapter
- PDF/Markdown output generation
- Three-layer architecture in action

**Requirements:**
```bash
pip install openbench[google,output]
export GOOGLE_API_KEY=your-api-key  # Get from https://aistudio.google.com/apikey
```

**Run it:**
```bash
# Basic PDF to PDF workflow
python examples/workflows/pdf_google_adk_workflow.py input.pdf output.pdf

# With custom goal
python examples/workflows/pdf_google_adk_workflow.py input.pdf output.pdf --goal "Summarize key points"

# Output to Markdown
python examples/workflows/pdf_google_adk_workflow.py input.pdf output.md --format markdown

# Named workflow with checkpointing
python examples/workflows/pdf_google_adk_workflow.py input.pdf output.pdf --workflow named
```

### 5. Sustainability Report (`workflows/sustainability_report.py`)

Complete real-world example generating ESG/sustainability reports:
- Parallel data extraction from multiple sources (PDF & API & CSV)
- Sequential multi-agent processing (Research → Analysis → Content)
- Parallel output generation (PDF & PowerPoint)
- Named workflow with state management and checkpointing
- Complete end-to-end demonstration

**Use case:** Sustainability consultants, ESG analysts

**Run it:**
```bash
python examples/workflows/sustainability_report.py
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
