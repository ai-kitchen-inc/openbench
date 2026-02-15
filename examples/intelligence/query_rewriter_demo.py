"""
Query Rewriter Demo - LLM-based query enhancement for better RAG retrieval.

Demonstrates how QueryRewriter rewrites user queries into optimized search
queries for improved semantic search recall.

Two modes:
    1. Standalone: Use QueryRewriter directly
    2. With BaseAgent: Enable query_rewriter=True for automatic rewriting

Usage:
    python examples/intelligence/query_rewriter_demo.py
    python examples/intelligence/query_rewriter_demo.py --demo 1
    python examples/intelligence/query_rewriter_demo.py --model gemini-2.5-pro

Requires:
    - GOOGLE_API_KEY (required)
    - PINECONE_API_KEY (optional -- demo 2 gracefully skips if not set)
"""

import argparse
import os
import sys

from openbench.core.abstractions import ExecutionContext
from openbench.core.providers import ProviderType, configure_provider
from openbench.intelligence.base import BaseAgent, QueryRewriter
from openbench.intelligence.llm_providers import GeminiLLMProvider  # noqa: F401

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_NAMESPACE = "knowledge-base"


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


def create_pinecone_store(
    index_name: str = "openbench",
    namespace: str = DEFAULT_NAMESPACE,
    dimension: int | None = None,
):
    """Create PineconeStore if PINECONE_API_KEY is available, else None."""
    if not os.getenv("PINECONE_API_KEY"):
        return None

    try:
        from openbench.data.stores.pinecone import PineconeStore
        from openbench.intelligence.embeddings import GoogleEmbeddingProvider

        return PineconeStore(
            index_name=index_name,
            namespace=namespace,
            embedding_provider=GoogleEmbeddingProvider(
                model="gemini-embedding-001", dimension=dimension
            ),
            create_if_missing=True,
        )
    except Exception as e:
        print(f"  Could not create PineconeStore: {e}")
        return None


def print_header(title: str):
    """Print formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_result(result):
    """Print ExecutionResult details."""
    print(f"\n  Status: {result.status}")
    print(f"  Iterations: {result.metadata.get('iterations', 'N/A')}")
    print(f"  Tokens: {result.tokens_used}")
    print(f"  Cost: ${result.cost:.6f}")
    print(f"\n--- Agent Response ---\n{result.output}\n")


# --- Demo Functions ---


def demo_standalone(model: str):
    """Demo 1: Standalone QueryRewriter.

    Shows how QueryRewriter takes a user query and generates multiple
    optimized search queries for better semantic search recall.
    """
    print_header("Demo 1: Standalone QueryRewriter")

    from openbench.core.providers import get_provider_service

    service = get_provider_service()
    llm = service.resolve(ProviderType.LLM)

    rewriter = QueryRewriter(llm, model=model)

    queries = [
        "How does photosynthesis affect climate change?",
        "What are the best practices for securing microservices?",
        "Compare Python and Rust performance for data processing",
    ]

    for query in queries:
        print(f"\n  Original: {query}")
        rewritten = rewriter.rewrite(query)
        for i, rq in enumerate(rewritten, 1):
            print(f"    [{i}] {rq}")

    # With additional context
    print("\n  --- With context ---")
    query = "revenue trends"
    context = "Q4 2025 financial report for Acme Corp"
    print(f"  Original: {query}")
    print(f"  Context:  {context}")
    rewritten = rewriter.rewrite(query, context=context)
    for i, rq in enumerate(rewritten, 1):
        print(f"    [{i}] {rq}")


def demo_agent_with_rewriter(
    model: str,
    namespace: str = DEFAULT_NAMESPACE,
    index_name: str = "openbench",
    dimension: int | None = None,
):
    """Demo 2: BaseAgent with query_rewriter=True.

    BaseAgent automatically rewrites queries before searching the store,
    improving retrieval recall without changing application code.
    """
    print_header("Demo 2: BaseAgent + Query Rewriting")

    store = create_pinecone_store(index_name, namespace, dimension)
    if not store:
        print("\n  Skipped: PINECONE_API_KEY not set.")
        print("  Set it with: export PINECONE_API_KEY=your-key")
        return

    print(f"\n  Model: {model}")
    print("  Store: PineconeStore (auto-retrieve)")
    print("  Query Rewriter: ENABLED")

    # Without query rewriting (baseline)
    print("\n  --- Without Query Rewriting ---")
    agent_baseline = BaseAgent(
        goal="Answer questions using retrieved context from documents.",
        model=model,
        temperature=0.3,
        store=store,
        retrieval_top_k=5,
        retrieval_threshold=0.5,
        query_rewriter=False,
    )

    query = "What is the environmental impact of AI data centers on local communities?"
    print(f"  Query: {query}\n")
    result = agent_baseline.execute(ExecutionContext(goal=query))
    print_result(result)

    # With query rewriting
    print("  --- With Query Rewriting ---")
    agent_rewriter = BaseAgent(
        goal="Answer questions using retrieved context from documents.",
        model=model,
        temperature=0.3,
        store=store,
        retrieval_top_k=5,
        retrieval_threshold=0.5,
        query_rewriter=True,
    )

    print(f"  Query: {query}")
    print("  (query will be rewritten into multiple search queries)\n")
    result = agent_rewriter.execute(ExecutionContext(goal=query))
    print_result(result)


# --- Main ---

DEFAULT_QUERIES = {
    "1": None,  # Demo 1 uses predefined queries
    "2": "What is the environmental impact of AI data centers?",
}


def main():
    parser = argparse.ArgumentParser(
        description="Query Rewriter Demo - LLM-based query enhancement for RAG",
    )
    parser.add_argument(
        "--demo",
        choices=["1", "2", "all"],
        default="all",
        help="Which demo to run (default: all)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help=f"Pinecone namespace (default: {DEFAULT_NAMESPACE})",
    )
    parser.add_argument(
        "--index",
        default="openbench",
        help="Pinecone index name (default: openbench)",
    )
    parser.add_argument(
        "--dimension",
        type=int,
        default=None,
        help="Embedding dimension override (default: auto-detect from provider)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  OpenBench: Query Rewriter Demo")
    print("=" * 60)
    print(f"\n  Model: {args.model}")
    print(f"  GOOGLE_API_KEY: {'set' if os.getenv('GOOGLE_API_KEY') else 'NOT SET'}")
    print(f"  PINECONE_API_KEY: {'set' if os.getenv('PINECONE_API_KEY') else 'not set (optional)'}")

    check_api_key()
    setup_provider(args.model)

    try:
        if args.demo in ("1", "all"):
            demo_standalone(args.model)

        if args.demo in ("2", "all"):
            demo_agent_with_rewriter(args.model, args.namespace, args.index, args.dimension)

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
