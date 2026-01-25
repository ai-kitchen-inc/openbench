---
name: creating-abstractions
description: Implementing DataSource, Agent, OutputGenerator and other OpenBench abstractions
---

# Creating Abstractions Skill

This skill is auto-invoked when implementing new components that extend OpenBench's abstract base classes.

## Triggers

- Implementing DataSource subclasses
- Implementing Agent subclasses
- Implementing OutputGenerator subclasses
- Implementing DataStore subclasses
- Implementing LLMProvider subclasses
- Working with the Registry pattern

## Abstract Base Classes

### DataSource

Extract data from any source:

```python
from abc import abstractmethod
from typing import Any, Dict
from openbench.core import DataSource, RawData

class MyDataSource(DataSource):
    """Custom data source implementation."""

    def __init__(self, config_param: str):
        self.config_param = config_param

    @property
    def source_type(self) -> str:
        """Unique identifier for this source type."""
        return "my-source"

    @property
    def source_id(self) -> str:
        """Unique identifier for this instance."""
        return f"my-source:{self.config_param}"

    def get_metadata(self) -> Dict[str, Any]:
        """Return source metadata."""
        return {
            "type": self.source_type,
            "config": self.config_param
        }

    def extract(self) -> RawData:
        """Extract data from source."""
        content = self._fetch_content()
        return RawData(
            content=content,
            content_type="text",  # or "structured", "binary"
            metadata=self.get_metadata(),
            source=self
        )

    def validate(self) -> bool:
        """Validate source is accessible."""
        return True  # Implement actual validation

    def _fetch_content(self) -> Any:
        """Internal method to fetch content."""
        # Implement your extraction logic
        pass
```

### Agent

Execute AI tasks:

```python
from openbench.core import Agent, ExecutionContext, ExecutionResult

class MyAgent(Agent):
    """Custom agent implementation."""

    def __init__(self, goal: str, model: str = "gpt-4"):
        self.goal = goal
        self.model = model

    @property
    def agent_type(self) -> str:
        """Type of agent: research, analysis, content, action, meta."""
        return "custom"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """Execute the agent's task."""
        # Access context
        goal = context.goal
        input_data = context.input_data
        history = context.history

        # Process
        output = self._process(input_data)

        return ExecutionResult(
            output=output,
            status="completed",  # or "failed", "partial"
            metadata={"model": self.model},
            cost=0.05,  # Estimated cost in USD
            tokens_used=500
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        """Estimate execution cost."""
        return 0.05  # Implement actual estimation

    def _process(self, input_data: Any) -> Dict[str, Any]:
        """Internal processing logic."""
        # Implement your AI logic
        pass
```

### OutputGenerator

Generate output artifacts:

```python
from openbench.core import OutputGenerator, GeneratedOutput

class MyOutputGenerator(OutputGenerator):
    """Custom output generator."""

    def __init__(self, template: str = "default"):
        self.template = template

    @property
    def output_format(self) -> str:
        """Output format: pdf, pptx, audio, html, json, etc."""
        return "custom"

    def generate(
        self,
        content: Any,
        template: str = None,
        **options
    ) -> GeneratedOutput:
        """Generate output from content."""
        template = template or self.template

        # Generate output
        file_path = self._create_file(content, template, options)

        return GeneratedOutput(
            file_path=file_path,
            format=self.output_format,
            size_bytes=self._get_file_size(file_path),
            metadata={"template": template, **options}
        )

    def validate(self, content: Any) -> bool:
        """Validate content can be generated."""
        return content is not None

    def _create_file(self, content, template, options) -> str:
        """Internal file creation logic."""
        # Implement your generation logic
        pass
```

### DataStore

Store and index data:

```python
from openbench.core import DataStore, RawData, Query, SearchResult

class MyDataStore(DataStore):
    """Custom data store implementation."""

    @property
    def store_type(self) -> str:
        return "my-store"

    def index(self, data: RawData, **options) -> str:
        """Index data and return ID."""
        pass

    def search(self, query: Query) -> SearchResult:
        """Search indexed data."""
        pass

    def get(self, item_id: str) -> Any:
        """Get item by ID."""
        pass

    def delete(self, item_id: str) -> bool:
        """Delete item by ID."""
        pass

    def update(self, item_id: str, data: Any) -> bool:
        """Update item by ID."""
        pass
```

## Registry Pattern

Register and create implementations:

```python
from openbench.core import (
    DataSourceRegistry,
    AgentRegistry,
    OutputGeneratorRegistry
)

# Register implementations
DataSourceRegistry.register('custom', 'my-impl', MyDataSource)
AgentRegistry.register('custom', 'my-impl', MyAgent)
OutputGeneratorRegistry.register('custom', 'my-impl', MyOutputGenerator)

# Create instances (swappable!)
source = DataSourceRegistry.create('custom', 'my-impl', config_param="value")
agent = AgentRegistry.create('custom', 'my-impl', goal="analyze data")
generator = OutputGeneratorRegistry.create('custom', 'my-impl', template="report")
```

## Best Practices

### 1. Always Implement Required Properties

```python
@property
def source_type(self) -> str:  # Required
    return "my-type"
```

### 2. Use Type Hints

```python
def extract(self) -> RawData:  # Return type specified
    ...
```

### 3. Handle Errors Gracefully

```python
def extract(self) -> RawData:
    try:
        content = self._fetch()
    except Exception as e:
        return RawData(
            content=None,
            content_type="error",
            metadata={"error": str(e)},
            source=self
        )
    return RawData(...)
```

### 4. Write Tests for Every Implementation

```python
class TestMyDataSource(unittest.TestCase):
    def test_source_type(self):
        source = MyDataSource("config")
        self.assertEqual(source.source_type, "my-source")

    def test_extract(self):
        source = MyDataSource("config")
        result = source.extract()
        self.assertIsNotNone(result.content)

    def test_validate(self):
        source = MyDataSource("config")
        self.assertTrue(source.validate())
```

### 5. Document Your Implementation

```python
class MyDataSource(DataSource):
    """
    Extract data from My Service.

    This source connects to My Service API and extracts
    structured data for processing.

    Args:
        api_key: API key for authentication
        endpoint: API endpoint URL

    Example:
        >>> source = MyDataSource(api_key="xxx", endpoint="https://...")
        >>> data = source.extract()
        >>> print(data.content)
    """
```

## Common Patterns

### Configurable Source

```python
class ConfigurableSource(DataSource):
    def __init__(self, **config):
        self.config = config

    @property
    def source_id(self) -> str:
        return f"{self.source_type}:{self.config.get('id', 'default')}"
```

### LLM-Powered Agent

```python
class LLMAgent(Agent):
    def __init__(self, goal: str, provider: LLMProvider):
        self.goal = goal
        self.provider = provider

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        response = self.provider.complete(
            prompt=self._build_prompt(context),
            max_tokens=1000
        )
        return ExecutionResult(
            output=response.content,
            status="completed",
            cost=response.cost,
            tokens_used=response.tokens_used
        )
```

### Template-Based Generator

```python
class TemplateGenerator(OutputGenerator):
    def __init__(self, templates_dir: str):
        self.templates_dir = templates_dir

    def generate(self, content, template=None, **options):
        template_path = Path(self.templates_dir) / f"{template}.jinja2"
        rendered = self._render_template(template_path, content)
        return GeneratedOutput(...)
```
