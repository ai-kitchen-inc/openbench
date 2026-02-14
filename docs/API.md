# OpenBench API Reference

Complete technical reference for all OpenBench abstractions and APIs.

**Last Updated**: 2026-02-14

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

### Provider Service & Configuration

| Component | Purpose | Status |
|-----------|---------|--------|
| `ProviderService` | Centralized provider configuration | ✅ Implemented |
| `ProviderConfig` | Provider configuration dataclass | ✅ Implemented |
| `ProviderType` | Provider type enum (LLM, VECTOR, etc.) | ✅ Implemented |
| `CredentialEncryption` | Encrypt credentials at rest | ✅ Implemented |
| `Config` | Single source of truth for config | ✅ Implemented |
| `ModelInfo` | LLM model metadata registry | ✅ Implemented |

---

## Core Abstractions

### Chainable

Foundation of all OpenBench components.

```python
from abc import ABC, abstractmethod
from typing import Any, Optional

class Chainable(ABC):
    """Base interface for all chainable components."""

    @abstractmethod
    def invoke(self, input: Any, config: Optional["RunnableConfig"] = None) -> Any:
        """Execute this component."""
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

Interface for extracting data from any source.

```python
from abc import ABC, abstractmethod
from typing import Dict, Any
from datetime import datetime

class DataSource(ABC, Chainable):
    """Interface for any data source (PDF, YouTube, APIs, etc.)."""

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Type identifier (e.g., 'pdf', 'youtube', 'api')"""
        pass

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Unique identifier for this source"""
        pass

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """Return metadata dict (title, author, size, etc.)"""
        pass

    @abstractmethod
    def extract(self) -> "RawData":
        """Extract and return RawData from the source"""
        pass

    @abstractmethod
    def validate(self) -> bool:
        """Validate source is accessible"""
        pass

    def invoke(self, input: Any, config=None) -> "RawData":
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

Interface for storing and searching data.

```python
class DataStore(ABC):
    """Interface for data storage (Vector DBs, SQL, Search Engines)."""

    @property
    @abstractmethod
    def store_type(self) -> str:
        """Type: 'vector', 'sql', 'search'"""
        pass

    @abstractmethod
    def index(self, data: RawData, **options) -> str:
        """Index data, return unique ID"""
        pass

    @abstractmethod
    def search(self, query: "Query") -> "SearchResult":
        """Search and return matched items"""
        pass

    @abstractmethod
    def get(self, item_id: str) -> Optional[Any]:
        """Retrieve item by ID"""
        pass

    @abstractmethod
    def delete(self, item_id: str) -> bool:
        """Delete item"""
        pass

    @abstractmethod
    def update(self, item_id: str, data: Any) -> bool:
        """Update item"""
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

Interface for AI agents.

```python
class Agent(ABC):
    """Interface for AI agents (Research, Analysis, Content)."""

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Type: 'research', 'analysis', 'content'"""
        pass

    @abstractmethod
    def execute(self, context: "ExecutionContext") -> "ExecutionResult":
        """Execute task and return result.

        BaseAgent and SimpleAgent accept an optional on_chunk callback
        for progressive token streaming:

            result = agent.execute(context, on_chunk=lambda delta: print(delta, end=''))
        """
        pass

    @abstractmethod
    def estimate_cost(self, context: "ExecutionContext") -> float:
        """Estimate cost in USD"""
        pass

    def invoke(self, input: Any, config=None) -> "ExecutionResult":
        """Chainable invoke method - handles various input types."""
        # Handle ExecutionContext directly
        if isinstance(input, ExecutionContext):
            return self.execute(input)

        # Handle dict with goal key
        if isinstance(input, dict) and "goal" in input:
            context = ExecutionContext(
                goal=input["goal"],
                data=input.get("data"),
                tools=input.get("tools"),
                memory=input.get("memory"),
                constraints=input.get("constraints")
            )
            return self.execute(context)

        # Fallback: use input as goal
        context = ExecutionContext(goal=str(input), data=input)
        return self.execute(context)
```

**ExecutionContext:**
```python
class ExecutionContext:
    """Execution context for agents."""

    def __init__(
        self,
        goal: str,
        data: Optional[Any] = None,
        tools: Optional[List["Tool"]] = None,
        memory: Optional[Any] = None,
        constraints: Optional[Dict[str, Any]] = None
    ):
        self.goal = goal
        self.data = data
        self.tools = tools or []
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

Interface for LLM providers.

```python
class LLMProvider(ABC):
    """Interface for LLM providers (OpenAI, Anthropic, local)."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider name: 'openai', 'anthropic', etc."""
        pass

    @abstractmethod
    def generate(self, prompt: str, model: str, **params) -> "LLMResponse":
        """Generate text from prompt"""
        pass

    def generate_stream(self, prompt: str, model: str, **params) -> "Iterator[LLMResponse]":
        """Stream text chunks progressively (token-by-token).

        Each yielded LLMResponse contains a partial text delta in .text field.
        The final response includes complete token counts.
        Default implementation falls back to generate() as a single chunk.
        """
        yield self.generate(prompt, model, **params)

    @abstractmethod
    def embed(self, text: str, model: Optional[str] = None) -> List[float]:
        """Generate embedding vector"""
        pass
```

---

## Output Layer

### OutputGenerator

Interface for output generation.

```python
class OutputGenerator(ABC, Chainable):
    """Interface for output generation (PDF, PowerPoint, Audio)."""

    @property
    @abstractmethod
    def output_format(self) -> str:
        """Format: 'pdf', 'pptx', 'audio', etc."""
        pass

    @abstractmethod
    def generate(self, content: Any, template: Optional[str] = None, **options) -> "GeneratedOutput":
        """Generate output and return GeneratedOutput"""
        pass

    @abstractmethod
    def validate(self, content: Any) -> bool:
        """Validate content can be rendered"""
        pass

    def invoke(self, input: Any, config=None) -> "GeneratedOutput":
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
    """Sequential execution."""

    def __init__(self, steps: List[Chainable]):
        self.steps = steps

    def invoke(self, input: Any, config=None) -> Any:
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
    """Concurrent execution."""

    def __init__(self, branches: List[Chainable]):
        self.branches = branches

    def invoke(self, input: Any, config=None) -> List[Any]:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(branch.invoke, input, config) for branch in self.branches]
            return [f.result() for f in futures]
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

    def __init__(self, condition: Callable[[Any], bool], true_branch: Chainable, false_branch: Optional[Chainable] = None):
        self.condition = condition
        self.true_branch = true_branch
        self.false_branch = false_branch

    def invoke(self, input: Any, config=None) -> Any:
        if self.condition(input):
            return self.true_branch.invoke(input, config)
        if self.false_branch:
            return self.false_branch.invoke(input, config)
        return input
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
    """Multi-way routing."""

    def __init__(self, routes: Dict[str, Chainable], router: Callable[[Any], str], default: Optional[Chainable] = None):
        self.routes = routes
        self.router = router
        self.default = default

    def invoke(self, input: Any, config=None) -> Any:
        route_key = self.router(input)
        branch = self.routes.get(route_key) or self.default
        if not branch:
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
    """L2 layer: orchestrates data sources and stores."""

    def __init__(self, sources: Union[Chainable, List[Chainable]], stores: Optional[List[DataStore]] = None):
        self.sources = sources if isinstance(sources, Chainable) else Chain(sources)
        self.stores = stores or []

    def invoke(self, input: Any, config=None) -> Dict[str, Any]:
        raw_data = self.sources.invoke(input, config)
        indexed_ids = []
        for store in self.stores:
            items = raw_data if isinstance(raw_data, list) else [raw_data]
            for data in items:
                indexed_ids.append(store.index(data))
        return {"raw_data": raw_data, "indexed_ids": indexed_ids, "metadata": {"layer": "data", "num_indexed": len(indexed_ids)}}
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
    """L2 layer: orchestrates AI agents."""

    def __init__(self, agents: Union[Chainable, List[Chainable]]):
        self.agents = agents if isinstance(agents, Chainable) else Chain(agents)

    def invoke(self, input: Any, config=None) -> Dict[str, Any]:
        output = self.agents.invoke(input, config)
        return {"intelligence_output": output, "metadata": {"layer": "intelligence"}}
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
    """L2 layer: orchestrates output generators."""

    def __init__(self, generators: Union[Chainable, List[Chainable]]):
        self.generators = generators if isinstance(generators, Chainable) else Chain(generators)

    def invoke(self, input: Any, config=None) -> Dict[str, Any]:
        outputs = self.generators.invoke(input, config)
        if not isinstance(outputs, list):
            outputs = [outputs]
        return {"generated_outputs": outputs, "metadata": {"layer": "output", "num_outputs": len(outputs)}}
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

All abstractions use registries for implementation selection.

### DataSourceRegistry

```python
class DataSourceRegistry:
    """Factory for DataSource implementations."""
    _registry: Dict[str, Dict[str, Type[DataSource]]] = {}

    @classmethod
    def register(cls, source_type: str, provider: str, implementation: Type[DataSource]):
        if source_type not in cls._registry:
            cls._registry[source_type] = {}
        cls._registry[source_type][provider] = implementation

    @classmethod
    def create(cls, source_type: str, provider: str, **config) -> DataSource:
        return cls._registry[source_type][provider](**config)
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
    """Named workflow with automatic state management and checkpointing."""

    def __init__(self, name: str, chain: Chainable, state_store: Optional[StateStore] = None, checkpoints: bool = True, metadata: Optional[Dict[str, Any]] = None):
        self.name = name
        self.chain = chain
        self.state_store = state_store or LocalStateStore()
        self.checkpoints = checkpoints
        self.metadata = metadata or {}

    def run(self, input: Dict[str, Any]) -> Any:
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

```python
class WorkflowStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class WorkflowState:
    """Workflow execution state."""
    def __init__(self, workflow_id: str, initial_input: Any, metadata: Optional[Dict[str, Any]] = None):
        self.workflow_id = workflow_id
        self.initial_input = initial_input
        self.metadata = metadata or {}
        self.status = WorkflowStatus.PENDING
        self.step_outputs: Dict[str, Any] = {}
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
```

### StateStore

```python
class StateStore(ABC):
    """Interface for state storage."""

    @abstractmethod
    def save(self, state: WorkflowState) -> bool: pass

    @abstractmethod
    def load(self, workflow_id: str) -> Optional[WorkflowState]: pass

    @abstractmethod
    def delete(self, workflow_id: str) -> bool: pass
```

### LocalStateStore

File-based state storage (default).

```python
class LocalStateStore(StateStore):
    def __init__(self, base_path: str = "./workflow_state"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(exist_ok=True)

    def save(self, state: WorkflowState) -> bool:
        with open(self.base_path / f"{state.workflow_id}.json", 'w') as f:
            json.dump(state.to_dict(), f, indent=2)
        return True

    def load(self, workflow_id: str) -> Optional[WorkflowState]:
        path = self.base_path / f"{workflow_id}.json"
        if not path.exists():
            return None
        with open(path, 'r') as f:
            return WorkflowState.from_dict(json.load(f))
```

---

## Provider Service

Centralized provider configuration with credential encryption.

```python
from openbench.core import (
    ProviderService,
    ProviderConfig,
    ProviderType,
    get_provider_service,
    configure_provider,
    resolve_provider,
)

# Get global service (singleton)
service = get_provider_service()

# Configure a provider
service.configure(ProviderConfig(
    name="my-openai",
    provider_type=ProviderType.LLM,
    provider="openai",
    plugin_type="chat",
    credentials={"api_key": "sk-..."},
    settings={"temperature": 0.7},
    is_default=True
))

# Get default provider for a type
config = service.get_default(ProviderType.LLM)

# Resolve to actual instance via PluginRegistry
llm = service.resolve(ProviderType.LLM)

# Or use convenience functions
configure_provider(
    name="my-anthropic",
    provider_type=ProviderType.LLM,
    provider="anthropic",
    plugin_type="chat",
    credentials={"api_key": "sk-ant-..."}
)

llm = resolve_provider(ProviderType.LLM, "my-anthropic")
```

### ProviderConfig

```python
@dataclass
class ProviderConfig:
    name: str                    # Unique identifier
    provider_type: ProviderType  # LLM, VECTOR, STORAGE, etc.
    provider: str                # e.g., "openai", "pinecone"
    plugin_type: str             # e.g., "chat", "vector"
    credentials: Dict[str, Any]  # API keys (encrypted at rest)
    settings: Dict[str, Any]     # Provider-specific settings
    is_default: bool = False
    enabled: bool = True
```

### ProviderType

```python
class ProviderType(Enum):
    LLM = "llm"
    EMBEDDING = "embedding"
    VECTOR = "vector"
    STORAGE = "storage"
    VOICE = "voice"
```

### Credential Encryption

Credentials are encrypted at rest using Fernet symmetric encryption.

```python
from openbench.core import get_credential_encryption

encryption = get_credential_encryption()
encrypted = encryption.encrypt("my-secret-key")
decrypted = encryption.decrypt(encrypted)
```

**Security:**
- Fernet encryption from `cryptography` library
- Key at `~/.openbench/.credentials_key` (0o600 permissions)
- Encrypted values prefixed with `enc:v1:`
- Graceful fallback if `cryptography` not installed

```bash
pip install openbench[security]  # Enable encryption
```

---

## Configuration

Single source of truth for application configuration.

```python
from openbench.core import get_config, ModelInfo

config = get_config()
config.get("llm.default_model", "gpt-4o")
config.set("llm.temperature", 0.7)

# Register and query models
config.register_model(ModelInfo(name="gpt-4o", provider="openai", context_window=128000, ...))
config.get_model("gpt-4o")
config.list_models(provider="openai")
```

### ModelInfo

```python
@dataclass
class ModelInfo:
    name: str
    provider: str
    context_window: int
    max_output_tokens: int
    supports_vision: bool
    supports_tools: bool
    cost_per_1k_input: float
    cost_per_1k_output: float
    aliases: List[str]
```

---

## Helper Functions

### create_workflow

```python
def create_workflow(
    data_sources: Optional[Union[Chainable, List[Chainable]]] = None,
    data_stores: Optional[List[DataStore]] = None,
    agents: Optional[Union[Chainable, List[Chainable]]] = None,
    generators: Optional[Union[Chainable, List[Chainable]]] = None
) -> Chainable:
    """Create a complete workflow from components."""
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

```python
workflow = create_workflow(
    data_sources=[source1, source2],
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
