"""
Multi-Hop RAG Demo - Agent-driven iterative knowledge retrieval.

Demonstrates how BaseAgent with multi_hop_rag=True gives the agent a
`retrieve_knowledge` tool so it can decide when and what to search during
its reasoning loop -- enabling multi-step research over a knowledge base.

Two modes:
    1. Auto-RAG (baseline): Single-pass retrieval at start
    2. Multi-Hop RAG: Agent calls retrieve_knowledge during reasoning

Usage:
    python examples/intelligence/multi_hop_rag_demo.py
    python examples/intelligence/multi_hop_rag_demo.py --demo 2
    python examples/intelligence/multi_hop_rag_demo.py --model gemini-2.5-pro

Requires:
    - GOOGLE_API_KEY (required)
    - PINECONE_API_KEY (required for all demos)
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
):
    """Create PineconeStore with Google embeddings."""
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


def demo_auto_rag(
    model: str,
    query: str,
    namespace: str,
    index_name: str = "openbench",
    dimension: int | None = None,
):
    """Demo 1: Baseline Auto-RAG.

    Standard single-pass retrieval: context is fetched once before the
    agent starts reasoning. Good for simple questions, but limited for
    complex multi-step research.
    """
    print_header("Demo 1: Auto-RAG (Baseline Single-Pass)")

    store = create_pinecone_store(index_name, namespace, dimension)

    print(f"\n  Model: {model}")
    print("  Mode: Auto-RAG (single retrieval at start)")
    print("  Multi-Hop: DISABLED")
    print(f"  Query: {query}")

    agent = BaseAgent(
        goal=(
            "Answer questions using the retrieved context from documents. "
            "Synthesize information clearly and cite sources."
        ),
        model=model,
        temperature=0.3,
        max_iterations=3,
        store=store,
        retrieval_top_k=5,
        retrieval_threshold=0.5,
    )

    print(f"  Tools: {list(agent.tools._tools.keys()) or ['(none)']}")
    print("\n  Executing agent...\n")

    result = agent.execute(ExecutionContext(goal=query))
    print_result(result)


def demo_multi_hop(
    model: str,
    query: str,
    namespace: str,
    index_name: str = "openbench",
    dimension: int | None = None,
):
    """Demo 2: Multi-Hop RAG.

    The agent receives a `retrieve_knowledge` tool and decides when and
    what to search during its reasoning loop. This enables iterative
    research -- the agent can refine queries based on initial findings.
    """
    print_header("Demo 2: Multi-Hop RAG (Agent-Driven Retrieval)")

    store = create_pinecone_store(index_name, namespace, dimension)

    print(f"\n  Model: {model}")
    print("  Mode: Multi-Hop RAG")
    print("  Auto-retrieve at start: DISABLED")
    print("  Tool: retrieve_knowledge (agent decides when to call)")
    print(f"  Query: {query}")

    agent = BaseAgent(
        goal=(
            "Research questions thoroughly using the knowledge base. "
            "Use the retrieve_knowledge tool to search for relevant information. "
            "You can call it multiple times with different queries:\n"
            "  - Start with a broad query to understand the topic\n"
            "  - Follow up with specific queries based on what you find\n"
            "  - Cross-reference findings across different searches\n"
            "Synthesize all findings into a comprehensive answer."
        ),
        model=model,
        temperature=0.3,
        max_iterations=6,
        store=store,
        retrieval_top_k=5,
        retrieval_threshold=0.5,
        multi_hop_rag=True,
    )

    print(f"  Registered tools: {list(agent.tools._tools.keys())}")
    print("\n  Executing agent (multi-hop reasoning)...\n")

    result = agent.execute(ExecutionContext(goal=query))
    print_result(result)


# --- Main ---

DEFAULT_QUERIES = {
    "1": "What are the company's key sustainability initiatives?",
    "2": (
        "What is the company's carbon footprint, what reduction targets have been set, "
        "and what specific actions are being taken to achieve them?"
    ),
}


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Hop RAG Demo - Agent-driven iterative retrieval",
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
        "--query",
        "-q",
        default=None,
        help="Custom query (overrides default for selected demo)",
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
    print("  OpenBench: Multi-Hop RAG Demo")
    print("=" * 60)
    print(f"\n  Model: {args.model}")
    print(f"  GOOGLE_API_KEY: {'set' if os.getenv('GOOGLE_API_KEY') else 'NOT SET'}")
    print(f"  PINECONE_API_KEY: {'set' if os.getenv('PINECONE_API_KEY') else 'NOT SET'}")

    check_api_keys()
    setup_provider(args.model)

    try:
        if args.demo in ("1", "all"):
            demo_auto_rag(
                args.model,
                args.query or DEFAULT_QUERIES["1"],
                args.namespace,
                args.index,
                args.dimension,
            )

        if args.demo in ("2", "all"):
            demo_multi_hop(
                args.model,
                args.query or DEFAULT_QUERIES["2"],
                args.namespace,
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
