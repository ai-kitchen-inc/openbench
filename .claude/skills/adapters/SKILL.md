---
name: adapters
description: Creating and using OpenBench framework adapters for LangChain, CrewAI, AG2, E2B, and Google ADK. Use when wrapping external AI frameworks, creating new adapters, or integrating third-party agents into workflows.
---

# Framework Adapters

OpenBench adapters wrap external AI frameworks to work in OpenBench workflows.

## Key Files

- `src/openbench/adapters/langchain.py` - LangChainAdapter
- `src/openbench/adapters/crewai.py` - CrewAIAdapter
- `src/openbench/adapters/ag2.py` - AG2Adapter
- `src/openbench/adapters/e2b.py` - E2BAdapter
- `src/openbench/adapters/google_adk.py` - GoogleADKAdapter

## Adapter Pattern

All adapters extend `FrameworkAdapter` with the same interface:

```python
from openbench.core import FrameworkAdapter

class MyAdapter(FrameworkAdapter):
    @property
    def framework_name(self) -> str:
        return "my-framework"  # Required

    def __init__(self, agent: Any):
        self.agent = agent

    def invoke(self, input: Any, config: Optional[Any] = None) -> Any:
        return self.agent.run(input)  # Required

    async def ainvoke(self, input: Any, config: Optional[Any] = None) -> Any:
        return await self.agent.arun(input)  # Optional
```

## Existing Adapters

### LangChainAdapter
Wraps any LangChain Runnable (agents, chains, LCEL):

```python
from openbench.adapters.langchain import LangChainAdapter

adapter = LangChainAdapter(runnable=my_langchain_agent)
# Supports both invoke() and ainvoke()
```

### CrewAIAdapter
Wraps CrewAI Crew, calls `crew.kickoff()`:

```python
from openbench.adapters.crewai import CrewAIAdapter

adapter = CrewAIAdapter(crew=my_crew)
# Input normalized to dict for kickoff(inputs=...)
```

### AG2Adapter
Wraps AG2/AutoGen agents via UserProxyAgent:

```python
from openbench.adapters.ag2 import AG2Adapter

adapter = AG2Adapter(agent=my_ag2_agent)
# Lazy imports AG2, creates UserProxyAgent, extracts last message
```

### E2BAdapter
Runs custom Python code in sandboxed E2B environments:

```python
from openbench.adapters.e2b import E2BAdapter

adapter = E2BAdapter(
    code='result = {"sum": sum(input_data["values"])}',
    packages=["pandas"],
    template="python-data-science",
)
# Input available as `input_data`, output must be assigned to `result`
```

### GoogleADKAdapter
Two modes - model (direct Gemini) or agent (wrap ADK agent):

```python
from openbench.adapters.google_adk import GoogleADKAdapter

# Model mode
adapter = GoogleADKAdapter(
    model="gemini-2.5-flash",
    system_instruction="You are a document analyst.",
)

# Agent mode
adapter = GoogleADKAdapter(agent=my_adk_agent)
```

## Using in Workflows

```python
from openbench.core import DataLayer, IntelligenceLayer, OutputLayer

workflow = (
    DataLayer(sources=pdf_source)
    | IntelligenceLayer(agents=LangChainAdapter(my_agent))
    | OutputLayer(generators=pdf_gen)
)
result = workflow.invoke({"query": "analyze report"})
```

## Creating a New Adapter

Follow this checklist:

1. Create file in `src/openbench/adapters/my_adapter.py`
2. Extend `FrameworkAdapter` from `openbench.core`
3. Implement `framework_name` property (returns string)
4. Implement `invoke(self, input, config=None)` method
5. Use lazy imports for the external framework with helpful error messages
6. Normalize input to dict if the framework requires it
7. Add `async def ainvoke()` if the framework supports async
8. Add tests in `tests/test_my_adapter.py`

## Anti-Patterns

**DO NOT:**
- Import external frameworks at module level - use lazy imports with try/except ImportError
- Assume input format - normalize input (check `isinstance(input, dict)`)
- Skip `framework_name` property - it's required by the abstract class
- Create adapters that duplicate built-in agents - use `BaseAgent` for simple LLM tasks
- Add business logic in adapters - they should be thin wrappers only

## Cross-References

- **Composing Workflows**: Adapters are `Chainable`, usable with `|` `&` → see `composing-workflows` skill
- **Intelligence Layer**: For built-in agents, use `BaseAgent` instead → see `intelligence-layer` skill
- **Creating Abstractions**: `FrameworkAdapter` base class details → see `creating-abstractions` skill

For examples, see `examples/adapters/framework_adapters_demo.py`
