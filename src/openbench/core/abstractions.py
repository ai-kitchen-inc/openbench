"""
Core abstract interfaces for OpenBench.

All implementations must inherit from these abstract base classes.
This ensures implementation independence and pluggability.

All core abstractions are Chainable, enabling L1 component-level composition.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from openbench.core.chainable import Chainable, RunnableConfig


# ============================================================================
# Data Layer Abstractions
# ============================================================================

class DataSource(ABC):
    """
    Abstract interface for any data source.

    Implementation-agnostic: Could be YouTube, PDF, URL, Google Docs, etc.

    DataSource is Chainable (L1): Can be composed with other DataSources.
    """

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Type identifier (e.g., 'youtube', 'pdf', 'url', 'google_doc')."""
        pass

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Unique identifier for this data source."""
        pass

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """
        Get metadata about the data source.

        Returns:
            Dict with keys like: title, author, created_at, size, etc.
        """
        pass

    @abstractmethod
    def extract(self) -> "RawData":
        """
        Extract raw data from the source.

        Returns:
            RawData object containing the extracted content
        """
        pass

    @abstractmethod
    def validate(self) -> bool:
        """Validate that the data source is accessible and valid."""
        pass

    def invoke(self, input: Any = None, config: Optional[Any] = None) -> "RawData":
        """
        Chainable invoke method.

        Enables DataSource to be used in workflows with pipe operator.
        Default implementation calls extract(), ignoring input.

        Override to handle input from previous source in chain.

        Args:
            input: Input from previous chainable (optional)
            config: Execution configuration (optional)

        Returns:
            RawData from this source
        """
        return self.extract()


class RawData:
    """
    Container for extracted raw data before processing.

    Implementation-agnostic representation of data.
    """

    def __init__(
        self,
        content: Any,
        content_type: str,
        metadata: Dict[str, Any],
        source: Optional[DataSource] = None
    ):
        self.content = content
        self.content_type = content_type  # 'text', 'binary', 'structured'
        self.metadata = metadata
        self.source = source
        self.extracted_at = datetime.now()


class Query:
    """
    Implementation-independent query representation.

    Different DataStore implementations translate this to their native query format.
    """

    def __init__(
        self,
        text: Optional[str] = None,
        vector: Optional[List[float]] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        offset: int = 0,
        sort: Optional[List[tuple]] = None
    ):
        self.text = text
        self.vector = vector
        self.filters = filters or {}
        self.limit = limit
        self.offset = offset
        self.sort = sort or []


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


class DataStore(ABC):
    """
    Abstract interface for data storage and retrieval.

    Implementation-agnostic: Could be VectorDB, SQL, Search Index, etc.
    """

    @property
    @abstractmethod
    def store_type(self) -> str:
        """Type of store ('vector', 'sql', 'search', 'graph', 'kv')."""
        pass

    @abstractmethod
    def index(self, data: RawData, **options) -> str:
        """
        Index/store data.

        Args:
            data: RawData to index
            **options: Implementation-specific indexing options

        Returns:
            Unique ID of the indexed data
        """
        pass

    @abstractmethod
    def search(self, query: Query) -> SearchResult:
        """
        Search the data store.

        Args:
            query: Query object (implementation-independent)

        Returns:
            SearchResult with matched items
        """
        pass

    @abstractmethod
    def get(self, item_id: str) -> Optional[Any]:
        """Retrieve a specific item by ID."""
        pass

    @abstractmethod
    def delete(self, item_id: str) -> bool:
        """Delete an item from the store."""
        pass

    @abstractmethod
    def update(self, item_id: str, data: Any) -> bool:
        """Update an existing item."""
        pass


# ============================================================================
# Intelligence Layer Abstractions
# ============================================================================

class ExecutionContext:
    """Implementation-independent execution context for agents."""

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


class ExecutionResult:
    """Implementation-independent execution result from agents."""

    def __init__(
        self,
        output: Any,
        status: str,
        metadata: Dict[str, Any],
        cost: float = 0.0,
        tokens_used: Optional[int] = None
    ):
        self.output = output
        self.status = status
        self.metadata = metadata
        self.cost = cost
        self.tokens_used = tokens_used


class Agent(ABC):
    """
    Abstract interface for any AI agent.

    Implementation-agnostic: Could use OpenAI, Anthropic, local models, etc.

    Agent is Chainable (L1): Can be composed with other Agents.
    """

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Type of agent ('research', 'analysis', 'content', etc.)."""
        pass

    @abstractmethod
    def execute(self, context: ExecutionContext) -> ExecutionResult:
        """
        Execute the agent's task.

        Args:
            context: Execution context with data and configuration

        Returns:
            ExecutionResult with agent's output
        """
        pass

    @abstractmethod
    def estimate_cost(self, context: ExecutionContext) -> float:
        """Estimate cost of execution in USD."""
        pass

    def invoke(self, input: Any, config: Optional[Any] = None) -> ExecutionResult:
        """
        Chainable invoke method.

        Enables Agent to be used in workflows with pipe operator.
        Wraps input in ExecutionContext and calls execute().

        Args:
            input: Input data (can be ExecutionContext or dict/any)
            config: Execution configuration (optional)

        Returns:
            ExecutionResult from agent execution
        """
        # If input is already ExecutionContext, use it
        if isinstance(input, ExecutionContext):
            context = input
        # If input is a dict with 'goal' and 'data', convert to ExecutionContext
        elif isinstance(input, dict) and 'goal' in input:
            context = ExecutionContext(
                goal=input['goal'],
                data=input.get('data'),
                tools=input.get('tools'),
                memory=input.get('memory'),
                constraints=input.get('constraints')
            )
        # Otherwise, wrap input as data
        else:
            context = ExecutionContext(
                goal=getattr(self, 'goal', f'Execute {self.agent_type} task'),
                data=input
            )

        return self.execute(context)


class LLMResponse:
    """Implementation-independent LLM response."""

    def __init__(
        self,
        text: str,
        model: str,
        tokens_used: int,
        cost: float,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.text = text
        self.model = model
        self.tokens_used = tokens_used
        self.cost = cost
        self.metadata = metadata or {}


class LLMProvider(ABC):
    """
    Abstract interface for LLM providers.

    Implementation-agnostic: Could be OpenAI, Anthropic, local models, etc.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider name ('openai', 'anthropic', 'huggingface', etc.)."""
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        model: str,
        **params
    ) -> LLMResponse:
        """
        Generate text from prompt.

        Args:
            prompt: Input prompt
            model: Model identifier
            **params: Model-specific parameters (temperature, max_tokens, etc.)

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
        """Generate embedding vector for text."""
        pass


class Tool(ABC):
    """
    Abstract interface for agent tools.

    Implementation-agnostic: Could be functions, APIs, MCP servers, etc.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """What the tool does."""
        pass

    @abstractmethod
    def execute(self, **params) -> Any:
        """
        Execute the tool.

        Args:
            **params: Tool-specific parameters

        Returns:
            Tool execution result
        """
        pass

    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """Get tool's input schema."""
        pass


# ============================================================================
# Output Layer Abstractions
# ============================================================================

class GeneratedOutput:
    """Implementation-independent generated output."""

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
        """Convert to dictionary for serialization."""
        return {
            "file_path": self.file_path,
            "format": self.format,
            "size_bytes": self.size_bytes,
            "metadata": self.metadata,
            "generated_at": self.generated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GeneratedOutput":
        """Create from dictionary."""
        obj = cls(
            file_path=data["file_path"],
            format=data["format"],
            size_bytes=data["size_bytes"],
            metadata=data["metadata"]
        )
        if "generated_at" in data:
            obj.generated_at = datetime.fromisoformat(data["generated_at"])
        return obj


class OutputGenerator(ABC):
    """
    Abstract interface for output generation.

    Implementation-agnostic: Could use different libraries for PDF, PPTX, etc.

    OutputGenerator is Chainable (L1): Can be composed with other OutputGenerators.
    """

    @property
    @abstractmethod
    def output_format(self) -> str:
        """Output format ('pdf', 'pptx', 'html', 'audio', etc.)."""
        pass

    @abstractmethod
    def generate(
        self,
        content: Any,
        template: Optional[str] = None,
        **options
    ) -> GeneratedOutput:
        """
        Generate output.

        Args:
            content: Content to render
            template: Template to use
            **options: Format-specific options

        Returns:
            GeneratedOutput with file path and metadata
        """
        pass

    @abstractmethod
    def validate(self, content: Any) -> bool:
        """Validate that content can be rendered in this format."""
        pass

    def invoke(self, input: Any, config: Optional[Any] = None) -> GeneratedOutput:
        """
        Chainable invoke method.

        Enables OutputGenerator to be used in workflows with pipe operator.
        Default implementation calls generate() with input as content.

        Args:
            input: Content to generate output from
            config: Execution configuration (optional)

        Returns:
            GeneratedOutput
        """
        template = None
        options = {}

        # Extract template and options from config if provided
        if config and isinstance(config, dict):
            template = config.get('template')
            options = {k: v for k, v in config.items() if k != 'template'}

        return self.generate(content=input, template=template, **options)
