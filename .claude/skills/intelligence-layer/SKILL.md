---
name: intelligence-layer
description: Working with OpenBench intelligence layer - BaseAgent, LLM providers, tool execution, memory, and RAG patterns. Use when creating agents, configuring LLM providers, adding tools, or building RAG-augmented agents.
---

# Intelligence Layer

OpenBench intelligence layer provides framework-agnostic agents with tool use, memory, and RAG.

## Key Files

- `src/openbench/intelligence/base.py` - BaseAgent, SimpleAgent, StructuredOutputAgent, ToolExecutor, AgentMemory, QueryRewriter
- `src/openbench/intelligence/agents.py` - Pre-built agents (Research, Analysis, Content, Action, Meta)
- `src/openbench/intelligence/llm_providers.py` - GeminiLLMProvider
- `src/openbench/intelligence/layer.py` - AgentFactory
- `src/openbench/intelligence/embeddings.py` - Embedding providers
- `src/openbench/intelligence/planning.py` - TaskPlanner, TaskPlan (task decomposition)
- `src/openbench/intelligence/memory.py` - PersistentMemory, SQLiteMemoryStore (persistent conversation)

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

## Task Planning

Optional LLM-based task decomposition before execution. Breaks complex goals into step-by-step plans:

```python
from openbench.intelligence.base import BaseAgent

# Enable planning phase before execution
agent = BaseAgent(
    goal="Analyze Q4 revenue trends and create summary",
    tools=[search_tool, calculate_tool],
    enable_planning=True,  # Decompose goal into steps
)

result = agent.execute(context)
# Agent first plans: ["Search Q4 data", "Calculate trends", "Summarize"]
# Then executes each step in the reasoning loop
```

Standalone usage:

```python
from openbench.intelligence.planning import TaskPlanner, TaskPlan

planner = TaskPlanner(llm_provider, model="gemini-2.5-flash")
plan = planner.plan("Analyze revenue trends", available_tools=["search", "calculate"])
# plan.steps -> ["Search for Q4 revenue data", "Calculate growth trends", ...]
# plan.estimated_tools -> ["search", "calculate"]
# plan.reasoning -> "Need to gather data first, then analyze..."
```

When `enable_planning=True`:
- `TaskPlanner.plan()` is called before the reasoning loop
- Plan steps are injected into agent memory as a system message
- Falls back to single-step plan if planning fails
- Uses low temperature (0.3) for consistent plans

## Persistent Memory

Cross-session conversation persistence using SQLite:

```python
from openbench.intelligence.memory import SQLiteMemoryStore, PersistentMemory

# Create store (file-backed)
store = SQLiteMemoryStore(db_path="memory.db")

# Use with BaseAgent
agent = BaseAgent(
    goal="Answer questions",
    memory_store=store,       # Enables persistence
    session_id="chat-123",    # Links to session
)

# Or use PersistentMemory directly
memory = PersistentMemory(store=store, session_id="chat-123")
memory.add_user("Hello")          # Auto-persisted to SQLite
memory.add_assistant("Hi there!") # Auto-persisted

# Later, in a new process:
memory2 = PersistentMemory(store=store, session_id="chat-123")
memory2.get_messages()  # Contains "Hello" and "Hi there!" from before

# Search across all sessions
results = memory2.search_history("revenue")

# Clear session (memory + store)
memory2.clear()
```

`MemoryStore` is abstract — implement for Redis, PostgreSQL, etc:

```python
from openbench.intelligence.memory import MemoryStore

class RedisMemoryStore(MemoryStore):
    def save(self, session_id, messages): ...
    def load(self, session_id): ...
    def search(self, query, limit=5): ...
    def list_sessions(self): ...
    def delete_session(self, session_id): ...
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

# Execute multiple tools in parallel
results = executor.execute_parallel([
    {"name": "search", "id": "call_1", "arguments": {"query": "revenue"}},
    {"name": "calculate", "id": "call_2", "arguments": {"x": 6, "y": 7}},
], timeout=30)
# Returns: [{"call": {...}, "result": ..., "error": None}, ...]
```

### Parallel Tool Execution

Enable concurrent tool execution in BaseAgent:

```python
agent = BaseAgent(
    goal="Research and analyze",
    tools=[search_tool, calculate_tool, fetch_tool],
    parallel_tool_execution=True,  # Run tools concurrently
)
```

When `parallel_tool_execution=True` and the LLM returns multiple tool calls in one iteration:
- Tools execute concurrently via `ThreadPoolExecutor`
- Results are returned in original order
- One tool failure doesn't block others
- Single tool calls still run sequentially (no overhead)

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

## Advanced RAG Features

Three features that compose at different levels for maximum retrieval quality.

### Query Rewriter

LLM-based query enhancement that rewrites user queries into 1-3 optimized search queries for better semantic recall:

```python
from openbench.intelligence.base import BaseAgent, QueryRewriter

# With BaseAgent (automatic)
agent = BaseAgent(
    goal="Answer questions",
    store=store,
    query_rewriter=True,  # Rewrites queries before searching
)

# Standalone usage
from openbench.core.providers import get_provider_service, ProviderType
llm = get_provider_service().resolve(ProviderType.LLM)
rewriter = QueryRewriter(llm, model="gemini-2.5-flash")
queries = rewriter.rewrite("revenue trends")  # -> ["revenue growth rate", "financial performance", ...]
```

### Multi-Hop RAG

Agent-driven iterative retrieval. The agent receives a `retrieve_knowledge` tool and decides when and what to search during its reasoning loop:

```python
agent = BaseAgent(
    goal="Research complex topics using the knowledge base. "
         "Use retrieve_knowledge tool to search for information.",
    store=store,
    multi_hop_rag=True,   # Registers retrieve_knowledge tool, skips auto-retrieval
    max_iterations=6,
)

# Agent reasoning loop:
# 1. Agent decides to call retrieve_knowledge("topic A")
# 2. Reads results, realizes it needs more info
# 3. Calls retrieve_knowledge("topic B")  <- multi-hop
# 4. Synthesizes all findings into final answer
```

### Combined "Golden Stack"

All three features working together (query_rewriter + multi_hop_rag + hybrid search):

```python
from openbench.data.stores.pinecone import PineconeStore

# Store level: hybrid search
store = PineconeStore(
    index_name="knowledge",
    hybrid_search=True,       # BM25 + vector reranking
    vector_weight=0.7,
)

# Agent level: query rewriter + multi-hop
agent = BaseAgent(
    goal="Research questions thoroughly",
    store=store,
    query_rewriter=True,      # Rewrite each query into 1-3 variants
    multi_hop_rag=True,       # Agent controls when to search
)
```

Internal flow when agent calls `retrieve_knowledge(query)`:
1. `_rag_tool_retrieve()` -> `_retrieve_context()`
2. `QueryRewriter.rewrite()` -> 1-3 optimized queries
3. Each query -> `store.search()` -> vector similarity + Hybrid Search re-rank
4. Deduplicated results returned to agent

For examples, see:
- `examples/intelligence/query_rewriter_demo.py`
- `examples/intelligence/multi_hop_rag_demo.py`
- `examples/intelligence/combined_rag_demo.py` (Golden Stack)

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

For examples, see `examples/intelligence/`:
- `query_rewriter_demo.py` - Query rewriting for better retrieval
- `multi_hop_rag_demo.py` - Agent-driven iterative retrieval
- `combined_rag_demo.py` - Golden Stack (all RAG features)
- `planning_demo.py` - Task decomposition before execution
- `persistent_memory_demo.py` - SQLite-backed cross-session memory
- `parallel_tools_demo.py` - Concurrent tool execution

Also see `examples/workflows/research/` for complete research agent workflows.
