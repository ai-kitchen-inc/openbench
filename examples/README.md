# OpenBench Examples

This directory contains working examples demonstrating OpenBench capabilities.

## Examples

### 1. Simple Workflow (`simple_workflow.py`)

A minimal example showing the three-layer architecture:
- Connect to data
- Create an agent
- Generate output

**Run it:**
```bash
python examples/simple_workflow.py
```

### 2. Sustainability Report (`sustainability_report.py`)

Generate comprehensive ESG/sustainability reports from multiple data sources:
- Multi-source data integration (PDFs, SQL, APIs)
- Multi-agent workflow (Research → Analysis → Content)
- Multiple output formats (PDF, PowerPoint, Dashboard)

**Use case:** Sustainability consultants, ESG analysts

**Run it:**
```bash
python examples/sustainability_report.py
```

### 3. Next Best Actions Analysis (`nba_analysis.py`)

Analyze customer data and generate actionable recommendations:
- Customer behavior analysis
- Statistical modeling
- Recommendation generation

**Use case:** Business analysts, CRM managers

**Run it:**
```bash
python examples/nba_analysis.py
```

## Creating Your Own Workflow

Use these examples as templates:

1. Copy an example file
2. Modify data sources
3. Adjust agent goals
4. Customize output formats
5. Run and iterate

## Common Patterns

### Multi-Agent Workflow

```python
from openbench import Workflow
from openbench.intelligence import ResearchAgent, AnalysisAgent, ContentAgent

workflow = Workflow(agents=[
    ResearchAgent(goal="Gather information"),
    AnalysisAgent(goal="Analyze data"),
    ContentAgent(goal="Create content")
])

result = workflow.execute(data_layer)
```

### Batch Export

```python
from openbench import OutputLayer

# Export to multiple formats
OutputLayer.batch_export(
    result,
    formats=["pdf", "pptx", "dashboard"],
    output_dir="outputs"
)
```

### Custom Agent

```python
from openbench import IntelligenceLayer

agent = IntelligenceLayer.create_agent(
    task="Your custom task",
    agent_type="research",  # or analysis, content, action, meta
    tools=["tool1", "tool2"],
    model="gpt-4"
)
```

## Need Help?

- [Documentation](../docs/README.md)
- [Discord Community](https://discord.com/users/openbench.ai)
- [GitHub Issues](https://github.com/ai-kitchen-inc/openbench/issues)
