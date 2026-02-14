---
name: intelligence-layer
description: Working with OpenBench intelligence layer - BaseAgent, LLM providers, tool execution, memory, and RAG patterns. Use when creating agents, configuring LLM providers, adding tools, or building RAG-augmented agents.
---

# Intelligence Layer

OpenBench intelligence layer provides framework-agnostic agents with tool use, memory, and RAG.

## Key Files

- `src/openbench/intelligence/base.py` - BaseAgent, SimpleAgent, StructuredOutputAgent, ToolExecutor, AgentMemory
- `src/openbench/intelligence/agents.py` - Pre-built agents (Research, Analysis, Content, Action, Meta)
- `src/openbench/intelligence/llm_providers.py` - GeminiLLMProvider
- `src/openbench/intelligence/layer.py` - AgentFactory
- `src/openbench/intelligence/embeddings.py` - Embedding providers

## BaseAgent

Framework-agnostic agent with reasoning loop, tools, and memory:

```python
from openbench.intelligence.base import BaseAgent
from openbench.core.abstractions import Tool

agent = BaseAgent(
    goal="Analyze sales data",
    tools=[search_tool, calculate_tool],
    model="gemini-2.5-flash",
    temperature=0.7,
    max_iterations=10,
    system_prompt="You are a data analyst.",  # Optional override
    store=vector_store,  # Optional: enables RAG
    retrieval_top_k=5,
    retrieval_threshold=0.0,
)

result = agent.execute(context)  # Returns ExecutionResult

# Execute with progressive token streaming
def on_token(delta: str) -> None:
    print(delta, end='', flush=True)

result = agent.execute(context, on_chunk=on_token)
```

## Progressive Token Streaming

Both `BaseAgent` and `SimpleAgent` support real-time token streaming via the `on_chunk` callback:

```python
def on_token(delta: str) -> None:
    print(delta, end='', flush=True)

agent = BaseAgent(goal="Analyze sales data", model="gemini-2.5-flash")
result = agent.execute(context, on_chunk=on_token)
```

When `on_chunk` is provided:
- `LLMProvider.generate_stream()` is used instead of `generate()`
- Text deltas are yielded progressively as they arrive from the LLM
- `on_chunk(delta)` is called for each text delta
- Final `ExecutionResult.output` contains the complete accumulated text
- If the provider doesn't implement `generate_stream()`, it falls back to `generate()` (single chunk)

This is used by the AG-UI transport (`AGUIHandler`) to stream `TEXT_MESSAGE_CONTENT` events via SSE.

## Pre-built Agent Types

All extend BaseAgent with specialized system prompts:

```python
from openbench.intelligence.agents import (
    ResearchAgent,   # goal, sources, depth
    AnalysisAgent,   # goal, methods
    ContentAgent,    # goal, style, max_length
    ActionAgent,     # goal, available_actions
    MetaAgent,       # goal (orchestrates other agents)
)

research = ResearchAgent(goal="Market analysis", sources=["web"], depth="deep")
analysis = AnalysisAgent(goal="Trend detection", methods=["statistical"])
```

## SimpleAgent & StructuredOutputAgent

```python
from openbench.intelligence.base import SimpleAgent, StructuredOutputAgent

# No tool loop - single LLM call
simple = SimpleAgent(goal="Summarize this text")

# Returns parsed JSON matching schema
structured = StructuredOutputAgent(
    goal="Extract entities",
    output_schema={"type": "object", "properties": {"entities": {"type": "array"}}}
)
```

## ToolExecutor

Register and execute tools:

```python
from openbench.intelligence.base import ToolExecutor
from openbench.core.abstractions import Tool

executor = ToolExecutor()

# Register OpenBench Tool
executor.register("search", my_search_tool)

# Register plain callable
executor.register("calculate", lambda x, y: x + y, description="Add numbers")

# Register multiple
executor.register_from_list([tool1, tool2, my_function])

# Execute
result = executor.execute("search", query="revenue")
schemas = executor.get_schemas()  # For LLM tool declarations
```

## AgentMemory

Conversation memory with system message preservation:

```python
from openbench.intelligence.base import AgentMemory, MessageRole

memory = AgentMemory(max_messages=100)
memory.add_system("You are a helpful assistant.")
memory.add_user("What is the revenue?")
memory.add_assistant("The revenue is $1M.")
memory.add_tool_result(tool_call_id="call_1", name="search", result='{"answer": "$1M"}')

messages = memory.get_messages()  # LLM-compatible format
memory.clear()  # Keeps system message
```

## LLM Providers

Configure via ProviderService:

```python
from openbench.core.providers import configure_provider, ProviderType

configure_provider(
    name="gemini",
    provider_type=ProviderType.LLM,
    provider="gemini",
    plugin_type="chat",
    credentials={"api_key": "your-key"},
    is_default=True,
)

# BaseAgent resolves automatically via ProviderService
agent = BaseAgent(goal="Analyze", model="gemini-2.5-flash")
```

### LLMProvider Streaming

`LLMProvider` has two generation methods:

```python
class LLMProvider(ABC):
    def generate(self, prompt, model, **params) -> LLMResponse:
        """Single blocking response."""

    def generate_stream(self, prompt, model, **params) -> Iterator[LLMResponse]:
        """Progressive streaming (for on_chunk support).
        Default: falls back to generate() as single chunk."""
        yield self.generate(prompt, model, **params)
```

`GeminiLLMProvider` implements `generate_stream()` using `generate_content_stream()` API. Each chunk yields a partial `LLMResponse` with delta text. Token usage comes from the final chunk.

## RAG (Retrieval-Augmented Generation)

Pass a DataStore to BaseAgent for automatic context retrieval:

```python
from openbench.intelligence.base import BaseAgent
from openbench.data.stores import PineconeStore

store = PineconeStore(index_name="knowledge", embedding_model="text-embedding-3-small")

agent = BaseAgent(
    goal="Answer questions about documents",
    store=store,
    retrieval_top_k=5,
    retrieval_threshold=0.3,
)

# Agent automatically:
# 1. Retrieves relevant chunks from store
# 2. Augments ExecutionContext with RAG context
# 3. Formats retrieved sources in the user message
```

## Anti-Patterns

**DO NOT:**
- Invent LLMProvider methods - read `src/openbench/core/abstractions.py` for the interface (`generate()`, `generate_stream()`, `provider_name`)
- Call `agent._get_llm()` directly - use `agent.execute(context)` which handles the full loop
- Assume tool call response format - different LLMs return different formats, `_parse_tool_calls()` handles this
- Skip `ProviderService` - don't instantiate `GeminiLLMProvider` directly in agents, use `configure_provider()` + `service.resolve()`
- Forget `max_iterations` - without it, tool loops can run indefinitely

## Cross-References

- **Data Layer**: `DataStore` used for RAG retrieval → see `data-layer` skill
- **Composing Workflows**: Agents are `Chainable`, usable with `|` `&` → see `composing-workflows` skill
- **Adapters**: External agents (LangChain, CrewAI) wrapped as adapters → see `adapters` skill
- **Testing**: Mock `LLMProvider` and `ToolExecutor` in tests → see `testing-openbench` skill

For examples, see `examples/intelligence/` and `examples/workflows/research/`
