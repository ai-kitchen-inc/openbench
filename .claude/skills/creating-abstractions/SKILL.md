---
name: creating-abstractions
description: Implementing DataSource, Agent, OutputGenerator and other OpenBench abstractions. Use when creating new data sources, agents, output generators, data stores, or framework adapters.
---

# Creating Abstractions

OpenBench uses abstract base classes for extensibility.

## DataSource

Extract data from any source:

```python
from openbench.core import DataSource, RawData

class MyDataSource(DataSource):
    def __init__(self, config: str):
        self.config = config

    @property
    def source_type(self) -> str:
        return "my-source"

    @property
    def source_id(self) -> str:
        return f"my-source:{self.config}"

    def get_metadata(self) -> dict:
        return {"type": self.source_type, "config": self.config}

    def extract(self) -> RawData:
        content = self._fetch_content()
        return RawData(
            content=content,
            content_type="text",  # or "structured", "binary"
            metadata=self.get_metadata(),
            source=self
        )

    def validate(self) -> bool:
        return True
```

## Agent

Execute AI tasks:

```python
from openbench.core import Agent, ExecutionContext, ExecutionResult

class MyAgent(Agent):
    def __init__(self, goal: str, model: str = "gemini-2.5-flash"):
        self.goal = goal
        self.model = model

    @property
    def agent_type(self) -> str:
        return "custom"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        output = self._process(context.input_data)
        return ExecutionResult(
            output=output,
            status="completed",
            metadata={"model": self.model},
            cost=0.05,
            tokens_used=500
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.05
```

## OutputGenerator

Generate output artifacts:

```python
from openbench.core import OutputGenerator, GeneratedOutput

class MyOutputGenerator(OutputGenerator):
    def __init__(self, template: str = "default"):
        self.template = template

    @property
    def output_format(self) -> str:
        return "custom"

    def generate(self, content, template=None, **options) -> GeneratedOutput:
        file_path = self._create_file(content, template or self.template)
        return GeneratedOutput(
            file_path=file_path,
            format=self.output_format,
            size_bytes=self._get_file_size(file_path),
            metadata={"template": template, **options}
        )

    def validate(self, content) -> bool:
        return content is not None
```

## DataStore

Store and retrieve data with vector search:

```python
from openbench.core import DataStore
from openbench.data.stores.base import EmbeddingMixin

class MyVectorStore(DataStore, EmbeddingMixin):
    def __init__(self, index_name: str, embedding_model: str = "text-embedding-3-small"):
        self.index_name = index_name
        self._embedding_model = embedding_model

    @property
    def store_type(self) -> str:
        return "my-vector-store"

    def index(self, data, **options) -> str:
        vector = self._embed(data.content)
        # Store vector and return ID
        return item_id

    def search(self, query: str, top_k: int = 5):
        query_vector = self._embed(query)
        # Search and return results
        return results

    def get(self, item_id: str):
        # Retrieve by ID
        pass

    def delete(self, item_id: str) -> bool:
        # Delete by ID
        return True
```

## FrameworkAdapter

Wrap external AI frameworks:

```python
from openbench.core import FrameworkAdapter

class MyFrameworkAdapter(FrameworkAdapter):
    def __init__(self, agent):
        self.agent = agent

    @property
    def framework_name(self) -> str:
        return "my-framework"

    def invoke(self, input, config=None):
        return self.agent.run(input)

    async def ainvoke(self, input, config=None):
        return await self.agent.arun(input)
```

## Registry Pattern

Register and create implementations:

```python
from openbench.core import DataSourceRegistry, AgentRegistry

# Register
DataSourceRegistry.register('custom', 'my-impl', MyDataSource)
AgentRegistry.register('custom', 'my-impl', MyAgent)

# Create (swappable!)
source = DataSourceRegistry.create('custom', 'my-impl', config="value")
agent = AgentRegistry.create('custom', 'my-impl', goal="analyze")
```

## Requirements

1. Always implement required abstract properties
2. Use type hints
3. Handle errors gracefully
4. Write tests for every implementation
5. Document with docstrings

For examples, see `src/openbench/data/sources/` and `src/openbench/intelligence/agents.py`
