"""
Agentic Research Demo - BaseAgent with RAG + Web Search

Three agentic approaches to research with BaseAgent's reasoning loop:

    1. Auto-RAG + Tool: BaseAgent(store=...) auto-retrieves + search_web tool
    2. Tool-based: Agent decides when to call search_web / search_knowledge_base
    3. Combined: Auto-RAG + both search tools (most complete)

Usage:
    python agentic_research_demo.py                     # all demos
    python agentic_research_demo.py --demo 2            # tool-based only
    python agentic_research_demo.py --demo 2 --query "acme revenue 2024"
    python agentic_research_demo.py --model gemini-2.5-pro

Requires:
    - GOOGLE_API_KEY (required)
    - PINECONE_API_KEY (optional -- demos gracefully skip if not set)
    - pip install google-genai pinecone
"""

import argparse
import os
import sys
from typing import Any

from openbench.core.abstractions import ExecutionContext, Query
from openbench.core.providers import ProviderType, configure_provider
from openbench.data.sources import GroundedSearchSource
from openbench.intelligence.base import BaseAgent
from openbench.intelligence.llm_providers import GeminiLLMProvider  # noqa: F401

# --- Constants ---

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_NAMESPACE = "knowledge-base"


# --- Tool Schemas ---

SEARCH_WEB_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "Search the web for current information using AI-grounded search. "
            "Returns a synthesized answer with citations. Use for real-time data, "
            "news, or topics not covered by the knowledge base."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find information about",
                },
            },
            "required": ["query"],
        },
    },
}

SEARCH_KB_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": (
            "Search the internal knowledge base (vector database) for relevant documents. "
            "Use for company-specific data, indexed reports, and internal documents."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find relevant documents",
                },
                "namespace": {
                    "type": "string",
                    "description": (f"Knowledge base namespace (default: {DEFAULT_NAMESPACE})"),
                },
            },
            "required": ["query"],
        },
    },
}


# --- Helpers ---


def create_pinecone_store(namespace: str = DEFAULT_NAMESPACE, dimension: int | None = None):
    """Create PineconeStore if PINECONE_API_KEY is available, else None."""
    if not os.getenv("PINECONE_API_KEY"):
        return None

    try:
        from openbench.data.stores.pinecone import PineconeStore
        from openbench.intelligence.embeddings import GoogleEmbeddingProvider

        return PineconeStore(
            index_name="openbench",
            namespace=namespace,
            embedding_provider=GoogleEmbeddingProvider(
                model="gemini-embedding-001", dimension=dimension
            ),
            create_if_missing=False,
        )
    except Exception as e:
        print(f"  Could not create PineconeStore: {e}")
        return None


# --- Tool Functions ---


def search_web(query: str) -> str:
    """Search the web using Gemini grounded search."""
    try:
        source = GroundedSearchSource(query=query, provider="gemini")
        result = source.extract()
        return result.content
    except Exception as e:
        return f"Web search failed: {e}"


def search_knowledge_base(query: str, namespace: str = DEFAULT_NAMESPACE) -> str:
    """Search the internal knowledge base via PineconeStore."""
    store = create_pinecone_store(namespace)
    if not store:
        return "Knowledge base not available (PINECONE_API_KEY not set)"

    try:
        result = store.search(Query(text=query, limit=5))

        docs = []
        for i, item in enumerate(result.items):
            score = result.scores[i] if result.scores else 0
            if score >= 0.7:
                content = item.get("content", "")[:1000]
                source = item.get("metadata", {}).get("source", "unknown")
                docs.append(f"[{i + 1}] (score: {score:.2f}, source: {source})\n{content}")

        return "\n---\n".join(docs) if docs else "No relevant documents found."

    except Exception as e:
        return f"Knowledge base search failed: {e}"


def check_api_key():
    """Exit if GOOGLE_API_KEY is not set."""
    if not os.getenv("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY environment variable is required.")
        print("\nSet it with:")
        print("  export GOOGLE_API_KEY=your-api-key")
        sys.exit(1)


def setup_provider(model: str):
    """Configure GeminiLLMProvider as the default LLM provider."""
    configure_provider(
        name="gemini-default",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": os.getenv("GOOGLE_API_KEY")},
        settings={"model": model},
        is_default=True,
    )


def print_header(title: str):
    """Print formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_result(result):
    """Print ExecutionResult details."""
    print(f"\n  Status: {result.status}")
    print(f"  Iterations: {result.metadata.get('iterations', 'N/A')}")
    print(f"  Tools used: {result.metadata.get('tools_used', [])}")
    print(f"  Tokens: {result.tokens_used}")
    print(f"  Cost: ${result.cost:.6f}")
    print(f"\n--- Agent Response ---\n{result.output}\n")


# --- Demo Functions ---


def demo_builtin_store(
    model: str, query: str, namespace: str = DEFAULT_NAMESPACE, dimension: int | None = None
):
    """Demo 1: Built-in Store + Web Tool.

    BaseAgent(store=PineconeStore) auto-retrieves RAG context before execute().
    The agent also has search_web tool for additional information.
    Requires: PINECONE_API_KEY
    """
    print_header("Demo 1: Built-in Store + Web Search Tool")

    store = create_pinecone_store(namespace, dimension=dimension)
    if not store:
        print("\n  Skipped: PINECONE_API_KEY not set.")
        print("  Set it with: export PINECONE_API_KEY=your-key")
        return

    print(f"\n  Model: {model}")
    print(f"  Store: PineconeStore(namespace={namespace}) -- auto-retrieve")
    print("  Tool: search_web -- agent decides when to use")
    print(f"  Query: {query}")

    agent = BaseAgent(
        goal=(
            "Answer questions using the retrieved context from internal documents. "
            "You also have a search_web tool -- use it to find additional context, "
            "verify information, or get more current data beyond what the documents provide. "
            "Always cite your sources (internal documents vs web)."
        ),
        model=model,
        temperature=0.3,
        max_iterations=5,
        store=store,
        retrieval_top_k=5,
        retrieval_threshold=0.7,
    )

    agent.tools.register("search_web", search_web, schema=SEARCH_WEB_SCHEMA)

    print(f"  Registered tools: {list(agent.tools._tools.keys())}")
    print("\n  Executing agent...\n")
    result = agent.execute(ExecutionContext(goal=query))
    print_result(result)


def demo_tool_based(model: str, query: str):
    """Demo 2: Tool-based -- agent decides when to search.

    Agent has search_web and search_knowledge_base tools.
    The reasoning loop decides which tools to call based on the query.
    Requires: GOOGLE_API_KEY (PINECONE_API_KEY optional for KB tool)
    """
    print_header("Demo 2: Tool-Based (Agent Decides)")

    has_pinecone = bool(os.getenv("PINECONE_API_KEY"))
    print(f"\n  Model: {model}")
    print("  Tools: search_web, search_knowledge_base")
    print(f"  Pinecone: {'available' if has_pinecone else 'not set (tool will return error)'}")
    print(f"  Query: {query}")

    agent = BaseAgent(
        goal=(
            "Research questions using available tools. "
            "Use search_knowledge_base for internal/company data. "
            "Use search_web for current events and general information. "
            "Synthesize findings into a clear answer."
        ),
        model=model,
        temperature=0.3,
        max_iterations=5,
    )

    agent.tools.register("search_web", search_web, schema=SEARCH_WEB_SCHEMA)
    agent.tools.register("search_knowledge_base", search_knowledge_base, schema=SEARCH_KB_SCHEMA)

    print(f"  Registered tools: {list(agent.tools._tools.keys())}")
    print("\n  Executing agent (reasoning loop)...\n")
    result = agent.execute(ExecutionContext(goal=query))
    print_result(result)


def demo_combined(
    model: str, query: str, namespace: str = DEFAULT_NAMESPACE, dimension: int | None = None
):
    """Demo 3: Combined -- built-in store + both search tools.

    BaseAgent(store=...) for automatic RAG context, plus search_web and
    search_knowledge_base tools for agent-driven research.
    Requires: PINECONE_API_KEY + GOOGLE_API_KEY
    """
    print_header("Demo 3: Combined (Auto-RAG + Both Search Tools)")

    store = create_pinecone_store(namespace, dimension=dimension)
    if not store:
        print("\n  Skipped: PINECONE_API_KEY not set.")
        print("  Set it with: export PINECONE_API_KEY=your-key")
        return

    print(f"\n  Model: {model}")
    print("  Store: PineconeStore (auto-retrieve)")
    print("  Tools: search_web, search_knowledge_base (agent decides)")
    print(f"  Query: {query}")

    agent = BaseAgent(
        goal=(
            "You are a research assistant with access to internal documents and web search. "
            "You will receive some context from internal documents automatically. "
            "IMPORTANT: Always also use search_web to find current web information "
            "to enrich and verify the internal document data. "
            "You can also use search_knowledge_base to search for more specific internal data. "
            "Synthesize ALL sources (internal documents + web) into a comprehensive answer. "
            "Cite sources: [Internal] for documents, [Web] for web search results."
        ),
        model=model,
        temperature=0.3,
        max_iterations=5,
        store=store,
        retrieval_top_k=5,
        retrieval_threshold=0.7,
    )

    agent.tools.register("search_web", search_web, schema=SEARCH_WEB_SCHEMA)
    agent.tools.register("search_knowledge_base", search_knowledge_base, schema=SEARCH_KB_SCHEMA)

    print(f"  Registered tools: {list(agent.tools._tools.keys())}")
    print("\n  Executing agent...\n")
    result = agent.execute(ExecutionContext(goal=query))
    print_result(result)


# --- Main ---

DEFAULT_QUERIES = {
    "1": "What are the sustainability metrics and ESG performance data from the indexed reports?",
    "2": "What are the latest AI agent trends in 2026?",
    "3": "What are the latest developments in AI agents? Compare internal data with current web trends.",
}


def main():
    parser = argparse.ArgumentParser(
        description="Agentic Research Demo - BaseAgent with RAG + Web Search",
    )
    parser.add_argument(
        "--demo",
        choices=["1", "2", "3", "all"],
        default="all",
        help="Which demo to run (default: all)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--query",
        "-q",
        default=None,
        help="Custom query (default: demo-specific query)",
    )
    parser.add_argument(
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help=f"Pinecone namespace (default: {DEFAULT_NAMESPACE})",
    )
    parser.add_argument(
        "--dimension",
        type=int,
        default=None,
        help="Embedding dimension override (default: provider native, e.g. 3072 for gemini-embedding-001)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  OpenBench: Agentic Research Demo")
    print("=" * 60)
    print("\n  BaseAgent reasoning loop + RAG + Web Search")
    print(f"  Model: {args.model}")
    print(f"  GOOGLE_API_KEY: {'set' if os.getenv('GOOGLE_API_KEY') else 'NOT SET'}")
    print(f"  PINECONE_API_KEY: {'set' if os.getenv('PINECONE_API_KEY') else 'not set (optional)'}")

    check_api_key()
    setup_provider(args.model)

    try:
        if args.demo in ("1", "all"):
            demo_builtin_store(
                args.model, args.query or DEFAULT_QUERIES["1"], args.namespace, args.dimension
            )

        if args.demo in ("2", "all"):
            demo_tool_based(args.model, args.query or DEFAULT_QUERIES["2"])

        if args.demo in ("3", "all"):
            demo_combined(
                args.model, args.query or DEFAULT_QUERIES["3"], args.namespace, args.dimension
            )

        print(f"\n{'=' * 60}")
        print("  Done!")
        print(f"{'=' * 60}")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
