"""
Combined RAG Demo -- The "Golden Stack".

All three Phase 1 retrieval features working together for maximum quality.
Each feature operates at a different level, composing without conflict:

    Store level:  Hybrid Search  (BM25 keyword + vector similarity reranking)
    Agent level:  Query Rewriter (rewrites queries into 1-3 optimized variants)
    Agent level:  Multi-Hop RAG  (agent decides when and what to search)

Integrated Workflow
-------------------
Example: "What is the difference in cloud division revenue between Q3 and Q4 reports?"

    Agent calls retrieve_knowledge("cloud revenue Q3 vs Q4")
    |
    |-- _rag_tool_retrieve(query)
    |     |
    |     +-- _retrieve_context(query)
    |           |
    |           +-- QueryRewriter.rewrite()
    |           |     -> "cloud division revenue Q3"
    |           |     -> "cloud division revenue Q4"
    |           |     -> "quarterly cloud earnings report"
    |           |
    |           +-- for each rewritten query:
    |                 +-- store.search()
    |                       +-- vector similarity search
    |                       +-- Hybrid Search re-rank (BM25 keywords: Q3, Q4, cloud)
    |
    Agent reads Q3 results, realizes Q4 data is in a different document
    |
    |-- Agent calls retrieve_knowledge("Q4 financial report cloud")   <- Multi-Hop
    |     +-- (same flow: rewrite -> hybrid search)
    |
    Agent now has both Q3 and Q4 data
    |
    +-- Calculates the difference and returns the final answer

Usage:
    python examples/intelligence/combined_rag_demo.py
    python examples/intelligence/combined_rag_demo.py --model gemini-2.5-pro
    python examples/intelligence/combined_rag_demo.py --vector-weight 0.5
    python examples/intelligence/combined_rag_demo.py -q "your custom query"

Requires:
    - GOOGLE_API_KEY (required)
    - PINECONE_API_KEY (required)
"""

import argparse
import os
import sys

from openbench.core.abstractions import ExecutionContext
from openbench.core.providers import ProviderType, configure_provider
from openbench.intelligence.base import BaseAgent
from openbench.intelligence.llm_providers import GeminiLLMProvider  # noqa: F401

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_NAMESPACE = "knowledge-base"


def check_api_keys():
    """Exit if required API keys are not set."""
    missing = []
    if not os.getenv("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")
    if not os.getenv("PINECONE_API_KEY"):
        missing.append("PINECONE_API_KEY")

    if missing:
        print("Error: Missing environment variables:")
        for key in missing:
            print(f"  - {key}")
        print()
        print("Set them with:")
        print("  export GOOGLE_API_KEY=your-google-api-key")
        print("  export PINECONE_API_KEY=your-pinecone-api-key")
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
    hybrid_search: bool = False,
    vector_weight: float = 0.7,
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
        hybrid_search=hybrid_search,
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
    print(f"  Tools used: {result.metadata.get('tools_used', [])}")
    print(f"  Tokens: {result.tokens_used}")
    print(f"  Cost: ${result.cost:.6f}")
    print(f"\n--- Agent Response ---\n{result.output}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Combined RAG Demo - Query Rewriter + Multi-Hop + Hybrid Search",
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
        help="Custom query (overrides default)",
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
    parser.add_argument(
        "--vector-weight",
        type=float,
        default=0.7,
        help="Vector similarity weight 0-1 (default: 0.7, keyword gets 1-weight)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  OpenBench: Combined RAG Demo")
    print("=" * 60)
    print("\n  All Phase 1 features combined:")
    print("    - Query Rewriter (agent level)")
    print("    - Multi-Hop RAG (agent level)")
    print(f"    - Hybrid Search (store level, vector_weight={args.vector_weight})")
    print(f"\n  Model: {args.model}")
    print(f"  GOOGLE_API_KEY: {'set' if os.getenv('GOOGLE_API_KEY') else 'NOT SET'}")
    print(f"  PINECONE_API_KEY: {'set' if os.getenv('PINECONE_API_KEY') else 'NOT SET'}")

    check_api_keys()
    setup_provider(args.model)

    query = args.query or (
        "What is the company's carbon footprint, what reduction targets have been set, "
        "and what specific actions are being taken to achieve them?"
    )

    try:
        print_header("Combined: Query Rewriter + Multi-Hop RAG + Hybrid Search")

        # Store with hybrid search enabled
        store = create_pinecone_store(
            index_name=args.index,
            namespace=args.namespace,
            dimension=args.dimension,
            hybrid_search=True,
            vector_weight=args.vector_weight,
        )

        # Agent with query rewriter + multi-hop RAG
        agent = BaseAgent(
            goal=(
                "Research questions thoroughly using the knowledge base. "
                "Use the retrieve_knowledge tool to search for information. "
                "You can call it multiple times with different queries:\n"
                "  - Start with a broad query to understand the topic\n"
                "  - Follow up with specific queries based on what you find\n"
                "  - Cross-reference findings across different searches\n"
                "Synthesize all findings into a comprehensive answer."
            ),
            model=args.model,
            temperature=0.3,
            max_iterations=6,
            store=store,
            retrieval_top_k=5,
            retrieval_threshold=0.5,
            query_rewriter=True,
            multi_hop_rag=True,
        )

        print(f"\n  Model: {args.model}")
        print(f"  Hybrid Search: ENABLED (vector_weight={args.vector_weight})")
        print("  Query Rewriter: ENABLED")
        print("  Multi-Hop RAG: ENABLED")
        print(f"  Registered tools: {list(agent.tools._tools.keys())}")
        print(f"  Query: {query}")
        print("\n  Executing agent...\n")

        result = agent.execute(ExecutionContext(goal=query))
        print_result(result)

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
