"""
Hybrid Search Demo - Vector + BM25 keyword scoring for better retrieval.

Demonstrates how HybridSearchMixin combines vector similarity with BM25
keyword scoring to improve search quality -- especially for exact term
matches that pure semantic search can miss.

Three modes:
    1. Standalone BM25: Use HybridSearchMixin directly
    2. PineconeStore: Enable hybrid_search=True on the store
    3. With BaseAgent: Full RAG pipeline with hybrid search

Usage:
    python examples/stores/hybrid_search_demo.py
    python examples/stores/hybrid_search_demo.py --demo 1
    python examples/stores/hybrid_search_demo.py --vector-weight 0.5

Requires:
    - Demo 1: No API keys needed (runs locally)
    - Demo 2+3: GOOGLE_API_KEY + PINECONE_API_KEY
"""

import argparse
import os
import sys

from openbench.data.stores.base import HybridSearchMixin

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_NAMESPACE = "knowledge-base"


def check_api_keys():
    """Check if required API keys are set for Pinecone demos."""
    missing = []
    if not os.getenv("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")
    if not os.getenv("PINECONE_API_KEY"):
        missing.append("PINECONE_API_KEY")

    if missing:
        print("  Skipped: Missing environment variables:")
        for key in missing:
            print(f"    - {key}")
        return False
    return True


def setup_provider(model: str):
    """Configure GeminiLLMProvider as the default LLM provider."""
    from openbench.core.providers import ProviderType, configure_provider
    from openbench.intelligence.llm_providers import GeminiLLMProvider  # noqa: F401

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
    namespace: str,
    hybrid: bool,
    vector_weight: float,
    index_name: str = "openbench",
    dimension: int | None = None,
):
    """Create PineconeStore with optional hybrid search."""
    from openbench.data.stores.pinecone import PineconeStore
    from openbench.intelligence.embeddings import GoogleEmbeddingProvider

    return PineconeStore(
        index_name=index_name,
        namespace=namespace,
        embedding_provider=GoogleEmbeddingProvider(
            model="gemini-embedding-001", dimension=dimension
        ),
        create_if_missing=True,
        hybrid_search=hybrid,
        vector_weight=vector_weight,
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
    print(f"  Tokens: {result.tokens_used}")
    print(f"  Cost: ${result.cost:.6f}")
    print(f"\n--- Agent Response ---\n{result.output}\n")


# --- Demo Functions ---


def demo_standalone_bm25():
    """Demo 1: Standalone BM25 + Hybrid Reranking.

    Shows how HybridSearchMixin works without any external services.
    Uses BM25 keyword scoring to rerank search results.
    """
    print_header("Demo 1: Standalone BM25 + Hybrid Reranking")

    # Simulate search results with vector scores
    items = [
        {"content": "Kubernetes orchestrates containerized applications across clusters"},
        {"content": "Python is widely used for machine learning and data science"},
        {"content": "Docker containers package applications with their dependencies"},
        {"content": "Python Flask framework for building REST API web services"},
        {"content": "Natural language processing with transformer neural networks"},
    ]
    vector_scores = [0.92, 0.88, 0.85, 0.82, 0.78]

    query = "Python REST API"

    print(f"\n  Query: {query}")
    print("\n  --- Original order (vector similarity only) ---")
    for i, (item, score) in enumerate(zip(items, vector_scores, strict=False)):
        print(f"    [{i + 1}] score={score:.2f}  {item['content'][:60]}...")

    # BM25 scores
    print("\n  --- BM25 keyword scores ---")
    query_terms = query.lower().split()
    for i, item in enumerate(items):
        bm25 = HybridSearchMixin.bm25_score(query_terms, item["content"])
        print(f"    [{i + 1}] bm25={bm25:.3f}  {item['content'][:60]}...")

    # Hybrid reranking (default: 0.7 vector + 0.3 keyword)
    reranked_items, reranked_scores = HybridSearchMixin.hybrid_rerank(
        items, vector_scores, query, vector_weight=0.7, keyword_weight=0.3
    )

    print("\n  --- Hybrid reranked (0.7 vector + 0.3 keyword) ---")
    for i, (item, score) in enumerate(zip(reranked_items, reranked_scores, strict=False)):
        print(f"    [{i + 1}] hybrid={score:.3f}  {item['content'][:60]}...")

    # Different weight balance
    reranked_items2, reranked_scores2 = HybridSearchMixin.hybrid_rerank(
        items, vector_scores, query, vector_weight=0.5, keyword_weight=0.5
    )

    print("\n  --- Hybrid reranked (0.5 vector + 0.5 keyword) ---")
    for i, (item, score) in enumerate(zip(reranked_items2, reranked_scores2, strict=False)):
        print(f"    [{i + 1}] hybrid={score:.3f}  {item['content'][:60]}...")


def demo_pinecone_hybrid(
    namespace: str,
    vector_weight: float,
    index_name: str = "openbench",
    dimension: int | None = None,
):
    """Demo 2: PineconeStore with hybrid search.

    Compares search results with and without hybrid search enabled.
    """
    print_header("Demo 2: PineconeStore Hybrid Search")

    if not check_api_keys():
        return

    from openbench.core.abstractions import Query

    query_text = "carbon emission reduction targets"
    print(f"\n  Query: {query_text}")

    # Without hybrid
    print("\n  --- Vector-only search ---")
    store_vector = create_pinecone_store(
        namespace,
        hybrid=False,
        vector_weight=0.7,
        index_name=index_name,
        dimension=dimension,
    )
    result_vector = store_vector.search(Query(text=query_text, limit=5))

    for i, (item, score) in enumerate(zip(result_vector.items, result_vector.scores, strict=False)):
        content = item.get("content", "")[:80]
        print(f"    [{i + 1}] score={score:.3f}  {content}...")

    # With hybrid
    print(f"\n  --- Hybrid search (vector_weight={vector_weight}) ---")
    store_hybrid = create_pinecone_store(
        namespace,
        hybrid=True,
        vector_weight=vector_weight,
        index_name=index_name,
        dimension=dimension,
    )
    result_hybrid = store_hybrid.search(Query(text=query_text, limit=5))

    for i, (item, score) in enumerate(zip(result_hybrid.items, result_hybrid.scores, strict=False)):
        content = item.get("content", "")[:80]
        print(f"    [{i + 1}] score={score:.3f}  {content}...")


def demo_agent_hybrid(
    model: str,
    namespace: str,
    vector_weight: float,
    index_name: str = "openbench",
    dimension: int | None = None,
):
    """Demo 3: BaseAgent with Hybrid Search PineconeStore.

    Full RAG pipeline: hybrid search improves retrieval quality,
    leading to better agent responses.
    """
    print_header("Demo 3: BaseAgent + Hybrid Search RAG")

    if not check_api_keys():
        return

    from openbench.core.abstractions import ExecutionContext
    from openbench.intelligence.base import BaseAgent

    setup_provider(model)

    print(f"\n  Model: {model}")
    print(f"  Hybrid Search: ENABLED (vector_weight={vector_weight})")

    store = create_pinecone_store(
        namespace,
        hybrid=True,
        vector_weight=vector_weight,
        index_name=index_name,
        dimension=dimension,
    )

    agent = BaseAgent(
        goal=(
            "Answer questions using retrieved context from documents. "
            "Be thorough and cite the specific data points you reference."
        ),
        model=model,
        temperature=0.3,
        store=store,
        retrieval_top_k=5,
        retrieval_threshold=0.5,
    )

    query = (
        "What specific carbon emission reduction targets has the company set, "
        "and what progress has been made?"
    )
    print(f"  Query: {query}\n")

    result = agent.execute(ExecutionContext(goal=query))
    print_result(result)


# --- Main ---


def main():
    parser = argparse.ArgumentParser(
        description="Hybrid Search Demo - Vector + BM25 for better retrieval",
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
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help=f"Pinecone namespace (default: {DEFAULT_NAMESPACE})",
    )
    parser.add_argument(
        "--vector-weight",
        type=float,
        default=0.7,
        help="Vector similarity weight 0-1 (default: 0.7, keyword gets 1-weight)",
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
    print("  OpenBench: Hybrid Search Demo")
    print("=" * 60)
    print("\n  Vector + BM25 keyword scoring")
    print(f"  Vector weight: {args.vector_weight}")
    print(f"  Keyword weight: {1 - args.vector_weight:.1f}")

    try:
        if args.demo in ("1", "all"):
            demo_standalone_bm25()

        if args.demo in ("2", "all"):
            demo_pinecone_hybrid(args.namespace, args.vector_weight, args.index, args.dimension)

        if args.demo in ("3", "all"):
            demo_agent_hybrid(
                args.model,
                args.namespace,
                args.vector_weight,
                args.index,
                args.dimension,
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
