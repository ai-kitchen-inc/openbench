# Quickstart

This quickstart uses the repository checkout and examples that are already included with OpenBench.

## 1. Install OpenBench

```bash
python -m pip install -e ".[all]"
```

## 2. Run A No-Key Example

Several examples use local mock components and do not require API keys:

```bash
python examples/core/core_abstractions_demo.py
python examples/core/orchestration_demo.py
python examples/adapters/framework_adapters_demo.py
```

## 3. Compose A Workflow

OpenBench components are chainable. Sequential composition uses `|`; parallel composition uses `&`.

```python
from openbench.core import Lambda, Parallel

load = Lambda(lambda _: {"topic": "OpenBench"}, name="load")
research = Lambda(lambda data: f"Research notes for {data['topic']}", name="research")
summarize = Lambda(lambda text: {"summary": text.upper()}, name="summarize")

workflow = load | research | summarize
result = workflow.invoke(None)
print(result)
```

## 4. Use Layers For Larger Workflows

The L2 layer classes orchestrate groups of sources, agents, and output generators:

```python
from openbench import DataLayer, IntelligenceLayer, OutputLayer

workflow = (
    DataLayer(sources=[source])
    | IntelligenceLayer(agents=[agent])
    | OutputLayer(generators=[generator])
)
result = workflow.invoke({"goal": "Create a report"})
```

Use the concrete source, agent, and generator classes that match your application and installed extras.

## 5. Run A Demo Application

The `openbench demo` command discovers demo projects under `examples/`.

```bash
openbench demo list
openbench demo run general-chat
```

Some demos require environment variables such as `GOOGLE_API_KEY` or frontend dependencies.
