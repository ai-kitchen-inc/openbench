# OpenBench API Reference

Complete technical reference for all OpenBench abstractions and APIs.

**Last Updated**: 2026-01-24

---

## Quick Reference

### Core Abstractions

| Abstraction | Purpose | Status |
|-------------|---------|--------|
| `DataSource` | Extract data from any source | ✅ Implemented |
| `DataStore` | Store and index data | ✅ Implemented |
| `Agent` | Execute AI tasks | ✅ Implemented |
| `LLMProvider` | Provide LLM capabilities | ✅ Implemented |
| `OutputGenerator` | Generate outputs | ✅ Implemented |
| `Tool` | Agent tools/capabilities | ✅ Implemented |

### Composition Primitives

| Primitive | Purpose | Syntax | Status |
|-----------|---------|--------|--------|
| `Chainable` | Base interface for all components | `class X(Chainable)` | ✅ Implemented |
| `Chain` | Sequential composition | `a \| b \| c` | ✅ Implemented |
| `Parallel` | Parallel composition | `Parallel([a, b, c])` | ✅ Implemented |
| `Conditional` | Conditional branching | `Conditional(condition, true, false)` | ✅ Implemented |
| `Router` | Multi-way routing | `Router(routes, router_fn)` | ✅ Implemented |

### L2 System Layers

| Layer | Purpose | Status |
|-------|---------|--------|
| `DataLayer` | Orchestrate data sources/stores | ✅ Implemented |
| `IntelligenceLayer` | Orchestrate AI agents | ✅ Implemented |
| `OutputLayer` | Orchestrate output generation | ✅ Implemented |

### Registries

| Registry | Purpose | Status |
|----------|---------|--------|
| `DataSourceRegistry` | Register/create DataSource implementations | ✅ Implemented |
| `DataStoreRegistry` | Register/create DataStore implementations | ✅ Implemented |
| `AgentRegistry` | Register/create Agent implementations | ✅ Implemented |
| `LLMProviderRegistry` | Register/create LLM providers | ✅ Implemented |
| `OutputGeneratorRegistry` | Register/create output generators | ✅ Implemented |
| `ToolRegistry` | Register/create tools | ✅ Implemented |

### Workflow & State

| Component | Purpose | Status |
|-----------|---------|--------|
| `Workflow` | Named, stateful workflows | ✅ Implemented |
| `WorkflowState` | Workflow execution state | ✅ Implemented |
| `StateStore` | Persist workflow state | ✅ Implemented |
| `LocalStateStore` | File-based state storage | ✅ Implemented |

---

## Design Principles

1. **Implementation Independence**: Abstractions never expose implementation details
2. **Composition Over Configuration**: Build workflows by composing components
3. **Registry Pattern**: All implementations registered and created via factories
4. **Chainable Everything**: Every component implements Chainable interface
5. **Type Safety**: Strong typing with clear contracts

---

## Core Abstractions

### Chainable

The foundation of all OpenBench components.

```python
from abc import ABC, abstractmethod
from typing import Any, Optional

class Chainable(ABC):
    """
    Base interface for all chainable components.

    Compatible with LangChain's Runnable interface.
    """

    @abstractmethod
    def invoke(
        self,
        input: Any,
        config: Optional["RunnableConfig"] = None
    ) -> Any:
        """
        Execute this chainable component.

        Args:
            input: Input data
            config: Optional runtime configuration

        Returns:
            Output data
        """
        pass

    def __or__(self, other: "Chainable") -> "Chain":
        """Pipe operator: self | other"""
        return Chain([self, other])

    def __and__(self, other: "Chainable") -> "Parallel":
        """And operator: self & other (parallel)"""
        return Parallel([self, other])
```

**Usage:**
```python
# Sequential
workflow = step_a | step_b | step_c

# Parallel
workflow = step_a & step_b & step_c

# Execute
result = workflow.invoke(input_data)
```

---

## Data Layer

### DataSource

Abstract interface for extracting data from any source.

```python
from abc import ABC, abstractmethod
from typing import Dict, Any
from datetime import datetime

class DataSource(ABC, Chainable):
    """
    Abstract interface for any data source.

    Implementations: PDF, YouTube, Google Docs, APIs, etc.
    """

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Type identifier (e.g., 'pdf', 'youtube', 'api')"""
        pass

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Unique identifier for this data source"""
        pass

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """
        Get metadata about the data source.

        Returns:
            Dict with keys: title, author, created_at, size, etc.
        """
        pass

    @abstractmethod
    def extract(self) -> "RawData":
        """
        Extract raw data from the source.

        Returns:
            RawData object containing extracted content
        """
        pass

    @abstractmethod
    def validate(self) -> bool:
        """Validate that the data source is accessible"""
        pass

    def invoke(self, input: Any, config=None) -> "RawData":
        """Chainable interface - calls extract()"""
        return self.extract()
```

**RawData:**
```python
class RawData:
    """Container for extracted raw data."""

    def __init__(
        self,
        content: Any,
        content_type: str,  # 'text', 'binary', 'structured'
        metadata: Dict[str, Any],
        source: DataSource
    ):
        self.content = content
        self.content_type = content_type
        self.metadata = metadata
        self.source = source
        self.extracted_at = datetime.now()
```

**Example Implementation:**
```python
class PDFDataSource(DataSource):
    def __init__(self, path: str):
        self.path = path

    @property
    def source_type(self) -> str:
        return "pdf"

    @property
    def source_id(self) -> str:
        return f"pdf:{self.path}"

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "size": os.path.getsize(self.path)
        }

    def extract(self) -> RawData:
        # Extract PDF content
        content = extract_pdf_text(self.path)
        return RawData(content, "text", {}, self)

    def validate(self) -> bool:
        return os.path.exists(self.path)
```

### DataStore

Abstract interface for storing and searching data.

```python
from abc import ABC, abstractmethod
from typing import Optional, List, Any

class DataStore(ABC):
    """
    Abstract interface for data storage.

    Implementations: Vector DBs, SQL, Search Engines, etc.
    """

    @property
    @abstractmethod
    def store_type(self) -> str:
        """Type of store ('vector', 'sql', 'search')"""
        pass

    @abstractmethod
    def index(self, data: RawData, **options) -> str:
        """
        Index/store data.

        Args:
            data: RawData to index
            **options: Implementation-specific options

        Returns:
            Unique ID of indexed data
        """
        pass

    @abstractmethod
    def search(self, query: "Query") -> "SearchResult":
        """
        Search the data store.

        Args:
            query: Query object

        Returns:
            SearchResult with matched items
        """
        pass

    @abstractmethod
    def get(self, item_id: str) -> Optional[Any]:
        """Retrieve specific item by ID"""
        pass

    @abstractmethod
    def delete(self, item_id: str) -> bool:
        """Delete item from store"""
        pass

    @abstractmethod
    def update(self, item_id: str, data: Any) -> bool:
        """Update existing item"""
        pass
```

**Query:**
```python
class Query:
    """Implementation-independent query."""

    def __init__(
        self,
        text: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        offset: int = 0
    ):
        self.text = text
        self.filters = filters or {}
        self.limit = limit
        self.offset = offset
```

**SearchResult:**
```python
class SearchResult:
    """Implementation-independent search result."""

    def __init__(
        self,
        items: List[Any],
        total: int,
        scores: Optional[List[float]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.items = items
        self.total = total
        self.scores = scores or []
        self.metadata = metadata or {}
```

---

## Intelligence Layer

### Agent

Abstract interface for AI agents.

```python
from abc import ABC, abstractmethod
from typing import Any, Dict

class Agent(ABC, Chainable):
    """
    Abstract interface for AI agents.

    Implementations: Research, Analysis, Content, etc.
    """

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Type of agent ('research', 'analysis', 'content')"""
        pass

    @abstractmethod
    def execute(self, context: "ExecutionContext") -> "ExecutionResult":
        """
        Execute the agent's task.

        Args:
            context: Execution context with data and config

        Returns:
            ExecutionResult with agent output
        """
        pass

    @abstractmethod
    def estimate_cost(self, context: "ExecutionContext") -> float:
        """Estimate cost of execution in USD"""
        pass

    def invoke(self, input: Any, config=None) -> "ExecutionResult":
        """Chainable interface - calls execute()"""
        context = ExecutionContext(
            goal=input.get("goal", ""),
            data_layer=input.get("data_layer"),
            tools=[],
            memory=None
        )
        return self.execute(context)
```

**ExecutionContext:**
```python
class ExecutionContext:
    """Execution context for agents."""

    def __init__(
        self,
        goal: str,
        data_layer: Any,
        tools: List["Tool"],
        memory: Optional["Memory"] = None,
        constraints: Optional[Dict[str, Any]] = None
    ):
        self.goal = goal
        self.data_layer = data_layer
        self.tools = tools
        self.memory = memory
        self.constraints = constraints or {}
```

**ExecutionResult:**
```python
class ExecutionResult:
    """Result from agent execution."""

    def __init__(
        self,
        output: Any,
        status: str,
        metadata: Dict[str, Any],
        cost: float,
        tokens_used: Optional[int] = None
    ):
        self.output = output
        self.status = status
        self.metadata = metadata
        self.cost = cost
        self.tokens_used = tokens_used
```

### LLMProvider

Abstract interface for LLM providers.

```python
from abc import ABC, abstractmethod
from typing import List, Optional

class LLMProvider(ABC):
    """
    Abstract interface for LLM providers.

    Implementations: OpenAI, Anthropic, local models, etc.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider name ('openai', 'anthropic', etc.)"""
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        model: str,
        **params
    ) -> "LLMResponse":
        """
        Generate text from prompt.

        Args:
            prompt: Input prompt
            model: Model identifier
            **params: Model-specific parameters

        Returns:
            LLMResponse with generated text
        """
        pass

    @abstractmethod
    def embed(
        self,
        text: str,
        model: Optional[str] = None
    ) -> List[float]:
        """Generate embedding vector"""
        pass
```

---

## Output Layer

### OutputGenerator

Abstract interface for output generation.

```python
from abc import ABC, abstractmethod
from typing import Any, Optional, Dict
from datetime import datetime

class OutputGenerator(ABC, Chainable):
    """
    Abstract interface for output generation.

    Implementations: PDF, PowerPoint, Audio, Dashboard, etc.
    """

    @property
    @abstractmethod
    def output_format(self) -> str:
        """Output format ('pdf', 'pptx', 'audio', etc.)"""
        pass

    @abstractmethod
    def generate(
        self,
        content: Any,
        template: Optional[str] = None,
        **options
    ) -> "GeneratedOutput":
        """
        Generate output.

        Args:
            content: Content to render
            template: Template to use
            **options: Format-specific options

        Returns:
            GeneratedOutput with file path
        """
        pass

    @abstractmethod
    def validate(self, content: Any) -> bool:
        """Validate content can be rendered"""
        pass

    def invoke(self, input: Any, config=None) -> "GeneratedOutput":
        """Chainable interface - calls generate()"""
        return self.generate(input)
```

**GeneratedOutput:**
```python
class GeneratedOutput:
    """Generated output metadata."""

    def __init__(
        self,
        file_path: str,
        format: str,
        size_bytes: int,
        metadata: Dict[str, Any]
    ):
        self.file_path = file_path
        self.format = format
        self.size_bytes = size_bytes
        self.metadata = metadata
        self.generated_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON storage"""
        return {
            "file_path": self.file_path,
            "format": self.format,
            "size_bytes": self.size_bytes,
            "metadata": self.metadata,
            "generated_at": self.generated_at.isoformat()
        }
```

---

## Composition Primitives

### Chain (Sequential)

Execute steps sequentially: A → B → C

```python
class Chain(Chainable):
    """Sequential chain of chainables."""

    def __init__(self, steps: List[Chainable]):
        self.steps = steps

    def invoke(self, input: Any, config=None) -> Any:
        """Execute steps sequentially"""
        current = input
        for step in self.steps:
            current = step.invoke(current, config)
        return current
```

**Usage:**
```python
# Using pipe operator
chain = step_a | step_b | step_c

# Or explicit
chain = Chain([step_a, step_b, step_c])

result = chain.invoke(input_data)
```

### Parallel

Execute steps concurrently: [A, B, C]

```python
class Parallel(Chainable):
    """Parallel execution of chainables."""

    def __init__(self, branches: List[Chainable]):
        self.branches = branches

    def invoke(self, input: Any, config=None) -> List[Any]:
        """Execute branches in parallel (using threads)"""
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(branch.invoke, input, config)
                for branch in self.branches
            ]
            results = [f.result() for f in futures]

        return results
```

**Usage:**
```python
# Explicit
parallel = Parallel([step_a, step_b, step_c])

# Using & operator
parallel = step_a & step_b & step_c

results = parallel.invoke(input_data)  # Returns list
```

### Conditional

Conditional branching based on input.

```python
from typing import Callable

class Conditional(Chainable):
    """Conditional branching."""

    def __init__(
        self,
        condition: Callable[[Any], bool],
        true_branch: Chainable,
        false_branch: Optional[Chainable] = None
    ):
        self.condition = condition
        self.true_branch = true_branch
        self.false_branch = false_branch

    def invoke(self, input: Any, config=None) -> Any:
        """Execute based on condition"""
        if self.condition(input):
            return self.true_branch.invoke(input, config)
        elif self.false_branch:
            return self.false_branch.invoke(input, config)
        else:
            return input  # Pass through
```

**Usage:**
```python
conditional = Conditional(
    condition=lambda x: x["confidence"] > 0.8,
    true_branch=fast_path,
    false_branch=detailed_path
)

result = conditional.invoke(data)
```

### Router

Multi-way routing based on input.

```python
class Router(Chainable):
    """Route to different branches based on input."""

    def __init__(
        self,
        routes: Dict[str, Chainable],
        router: Callable[[Any], str],
        default: Optional[Chainable] = None
    ):
        self.routes = routes
        self.router = router
        self.default = default

    def invoke(self, input: Any, config=None) -> Any:
        """Route to appropriate branch"""
        route_key = self.router(input)

        if route_key in self.routes:
            branch = self.routes[route_key]
        elif self.default:
            branch = self.default
        else:
            raise ValueError(f"No route: {route_key}")

        return branch.invoke(input, config)
```

**Usage:**
```python
router = Router(
    routes={
        "pdf": pdf_workflow,
        "video": video_workflow,
        "text": text_workflow
    },
    router=lambda x: x["type"]
)

result = router.invoke({"type": "pdf", ...})
```

---

## L2 System Layers

### DataLayer

Orchestrates data sources and stores.

```python
from typing import List, Union, Optional

class DataLayer(Chainable):
    """
    L2 layer for data orchestration.

    Composes L1 data sources and stores.
    """

    def __init__(
        self,
        sources: Union[Chainable, List[Chainable]],
        stores: Optional[List[DataStore]] = None
    ):
        self.sources = sources if isinstance(sources, Chainable) else Chain(sources)
        self.stores = stores or []

    def invoke(self, input: Any, config=None) -> Dict[str, Any]:
        """
        Execute data layer workflow.

        1. Extract from sources
        2. Index in stores
        3. Return aggregated data
        """
        # Extract from sources
        raw_data = self.sources.invoke(input, config)

        # Index in all stores
        indexed_ids = []
        for store in self.stores:
            if isinstance(raw_data, list):
                for data in raw_data:
                    item_id = store.index(data)
                    indexed_ids.append(item_id)
            else:
                item_id = store.index(raw_data)
                indexed_ids.append(item_id)

        return {
            "raw_data": raw_data,
            "indexed_ids": indexed_ids,
            "metadata": {
                "layer": "data",
                "num_indexed": len(indexed_ids)
            }
        }
```

**Usage:**
```python
# With L1 composition
sources = source1 | source2 | source3
data_layer = DataLayer(sources=sources, stores=[vector_store])

# Execute
result = data_layer.invoke({})
```

### IntelligenceLayer

Orchestrates AI agents.

```python
class IntelligenceLayer(Chainable):
    """
    L2 layer for intelligence orchestration.

    Composes L1 agents.
    """

    def __init__(self, agents: Union[Chainable, List[Chainable]]):
        self.agents = agents if isinstance(agents, Chainable) else Chain(agents)

    def invoke(self, input: Any, config=None) -> Dict[str, Any]:
        """
        Execute intelligence layer workflow.

        Runs agent workflow and returns results.
        """
        # Execute agents
        intelligence_output = self.agents.invoke(input, config)

        return {
            "intelligence_output": intelligence_output,
            "metadata": {
                "layer": "intelligence"
            }
        }
```

**Usage:**
```python
# With L1 composition
agents = agent1 | agent2 | agent3
intelligence_layer = IntelligenceLayer(agents=agents)

# Execute
result = intelligence_layer.invoke(data)
```

### OutputLayer

Orchestrates output generation.

```python
class OutputLayer(Chainable):
    """
    L2 layer for output orchestration.

    Composes L1 output generators.
    """

    def __init__(self, generators: Union[Chainable, List[Chainable]]):
        self.generators = generators if isinstance(generators, Chainable) else Chain(generators)

    def invoke(self, input: Any, config=None) -> Dict[str, Any]:
        """
        Execute output layer workflow.

        Generates outputs and returns metadata.
        """
        # Generate outputs
        generated_outputs = self.generators.invoke(input, config)

        # Normalize to list
        if not isinstance(generated_outputs, list):
            generated_outputs = [generated_outputs]

        return {
            "generated_outputs": generated_outputs,
            "metadata": {
                "layer": "output",
                "num_outputs": len(generated_outputs)
            }
        }
```

**Usage:**
```python
# With L1 composition (parallel)
outputs = Parallel([pdf_gen, pptx_gen])
output_layer = OutputLayer(generators=outputs)

# Execute
result = output_layer.invoke(content)
```

### End-to-End Composition

```python
# L1: Compose components
sources = source1 | source2 | source3
agents = agent1 | agent2
outputs = Parallel([pdf, pptx])

# L2: Compose into layers
data_layer = DataLayer(sources=sources, stores=[vector_store])
intelligence_layer = IntelligenceLayer(agents=agents)
output_layer = OutputLayer(generators=outputs)

# Compose layers into E2E workflow
workflow = data_layer | intelligence_layer | output_layer

# Execute
result = workflow.invoke({"query": "analyze sustainability"})
```

---

## Registry Pattern

All abstractions use the Registry pattern for implementation selection.

### DataSourceRegistry

```python
class DataSourceRegistry:
    """Factory for DataSource implementations."""

    _registry: Dict[str, Dict[str, Type[DataSource]]] = {}

    @classmethod
    def register(
        cls,
        source_type: str,
        provider: str,
        implementation: Type[DataSource]
    ):
        """Register a DataSource implementation."""
        if source_type not in cls._registry:
            cls._registry[source_type] = {}
        cls._registry[source_type][provider] = implementation

    @classmethod
    def create(
        cls,
        source_type: str,
        provider: str,
        **config
    ) -> DataSource:
        """Create a DataSource instance."""
        implementation = cls._registry[source_type][provider]
        return implementation(**config)
```

**Usage:**
```python
# Register
DataSourceRegistry.register('pdf', 'custom', MyPDFSource)

# Create
source = DataSourceRegistry.create('pdf', 'custom', path='./docs')
```

### Other Registries

All follow the same pattern:
- `DataStoreRegistry` - For DataStore implementations
- `AgentRegistry` - For Agent implementations
- `LLMProviderRegistry` - For LLM providers
- `OutputGeneratorRegistry` - For output generators
- `ToolRegistry` - For tools

---

## Workflow & State Management

### Workflow

Named, stateful workflows with checkpointing.

```python
from typing import Optional, Dict, Any

class Workflow(StatefulChainable):
    """
    Named workflow with automatic state management.

    Thin wrapper around StatefulChainable with:
    - Named workflows
    - Automatic checkpointing
    - State persistence
    """

    def __init__(
        self,
        name: str,
        chain: Chainable,
        state_store: Optional[StateStore] = None,
        checkpoints: bool = True,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.name = name
        self.chain = chain
        self.state_store = state_store or LocalStateStore()
        self.checkpoints = checkpoints
        self.metadata = metadata or {}

    def run(self, input: Dict[str, Any]) -> Any:
        """
        Execute workflow with state management.

        Args:
            input: Input data

        Returns:
            Workflow output
        """
        return self.invoke(input, workflow_id=self.name)
```

**Usage:**
```python
from openbench.workflows import Workflow
from openbench.core import LocalStateStore

workflow = Workflow(
    name="my-workflow",
    chain=data_layer | intelligence_layer | output_layer,
    state_store=LocalStateStore(base_path="./workflow_state"),
    checkpoints=True
)

result = workflow.run({"query": "analyze data"})
```

### WorkflowState

Persistent state for workflows.

```python
from enum import Enum
from datetime import datetime

class WorkflowStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class WorkflowState:
    """Workflow execution state."""

    def __init__(
        self,
        workflow_id: str,
        initial_input: Any,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.workflow_id = workflow_id
        self.initial_input = initial_input
        self.metadata = metadata or {}

        # State
        self.status = WorkflowStatus.PENDING
        self.step_outputs: Dict[str, Any] = {}
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
```

### StateStore

Abstract interface for storing workflow state.

```python
class StateStore(ABC):
    """Abstract interface for state storage."""

    @abstractmethod
    def save(self, state: WorkflowState) -> bool:
        """Save workflow state"""
        pass

    @abstractmethod
    def load(self, workflow_id: str) -> Optional[WorkflowState]:
        """Load workflow state by ID"""
        pass

    @abstractmethod
    def delete(self, workflow_id: str) -> bool:
        """Delete workflow state"""
        pass
```

### LocalStateStore

File-based state storage (default implementation).

```python
class LocalStateStore(StateStore):
    """File-based state storage."""

    def __init__(self, base_path: str = "./workflow_state"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(exist_ok=True)

    def save(self, state: WorkflowState) -> bool:
        """Save state to JSON file"""
        file_path = self.base_path / f"{state.workflow_id}.json"
        with open(file_path, 'w') as f:
            json.dump(state.to_dict(), f, indent=2)
        return True

    def load(self, workflow_id: str) -> Optional[WorkflowState]:
        """Load state from JSON file"""
        file_path = self.base_path / f"{workflow_id}.json"
        if not file_path.exists():
            return None

        with open(file_path, 'r') as f:
            data = json.load(f)

        return WorkflowState.from_dict(data)
```

---

## Helper Functions

### create_workflow

Convenience function for creating L2 workflows.

```python
def create_workflow(
    data_sources: Optional[Union[Chainable, List[Chainable]]] = None,
    data_stores: Optional[List[DataStore]] = None,
    agents: Optional[Union[Chainable, List[Chainable]]] = None,
    generators: Optional[Union[Chainable, List[Chainable]]] = None
) -> Chainable:
    """
    Create a complete workflow from components.

    Automatically composes layers and chains them.
    """
    layers = []

    if data_sources:
        layers.append(DataLayer(sources=data_sources, stores=data_stores or []))

    if agents:
        layers.append(IntelligenceLayer(agents=agents))

    if generators:
        layers.append(OutputLayer(generators=generators))

    if not layers:
        raise ValueError("Must provide at least one layer")

    return Chain(layers)
```

**Usage:**
```python
from openbench.core import create_workflow

workflow = create_workflow(
    data_sources=[source1, source2],
    data_stores=[vector_store],
    agents=[agent1, agent2],
    generators=[pdf_gen, pptx_gen]
)

result = workflow.invoke({})
```

---

## Complete Example

```python
from openbench.core import (
    DataSource, RawData,
    Agent, ExecutionContext, ExecutionResult,
    OutputGenerator, GeneratedOutput,
    DataLayer, IntelligenceLayer, OutputLayer,
    DataSourceRegistry, AgentRegistry, OutputGeneratorRegistry
)
from openbench.workflows import Workflow

# 1. Define custom implementations
class MyDataSource(DataSource):
    @property
    def source_type(self) -> str:
        return "custom"

    @property
    def source_id(self) -> str:
        return "my-source"

    def get_metadata(self):
        return {}

    def extract(self) -> RawData:
        return RawData("data", "text", {}, self)

    def validate(self) -> bool:
        return True

class MyAgent(Agent):
    @property
    def agent_type(self) -> str:
        return "custom"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(
            output={"result": "analysis complete"},
            status="completed",
            metadata={},
            cost=0.0
        )

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0

class MyGenerator(OutputGenerator):
    @property
    def output_format(self) -> str:
        return "pdf"

    def generate(self, content, template=None, **options) -> GeneratedOutput:
        return GeneratedOutput(
            file_path="/tmp/output.pdf",
            format="pdf",
            size_bytes=1024,
            metadata={}
        )

    def validate(self, content) -> bool:
        return True

# 2. Register implementations
DataSourceRegistry.register('custom', 'my-impl', MyDataSource)
AgentRegistry.register('custom', 'my-impl', MyAgent)
OutputGeneratorRegistry.register('pdf', 'my-impl', MyGenerator)

# 3. Create components
source = DataSourceRegistry.create('custom', 'my-impl')
agent = AgentRegistry.create('custom', 'my-impl')
generator = OutputGeneratorRegistry.create('pdf', 'my-impl')

# 4. Compose workflow
workflow = Workflow(
    name="complete-example",
    chain=(
        DataLayer(sources=source)
        | IntelligenceLayer(agents=agent)
        | OutputLayer(generators=generator)
    )
)

# 5. Execute
result = workflow.run({"query": "analyze data"})

print(f"Generated: {result['generated_outputs'][0].file_path}")
```

---

## Next Steps

- **Get Started**: [docs/GETTING_STARTED.md](GETTING_STARTED.md)
- **Understand Architecture**: [docs/ARCHITECTURE.md](ARCHITECTURE.md)
- **See Examples**: Run the examples in `examples/`
- **Join Community**: [Discord](https://discord.com/users/openbench.ai)

---

**Complete API reference for OpenBench abstractions and composition.**
