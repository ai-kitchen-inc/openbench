"""
Query Japfa Namespace Demo

Queries the existing 'japfa' namespace in the 'lca-checker' Pinecone index
using PineconeStore + GoogleEmbeddingProvider.

Requires:
    export PINECONE_API_KEY=your-key
    export GOOGLE_API_KEY=your-key
    pip install -e "../../.[vector,google]"

Usage:
    python examples/lca-checker/query_japfa_demo.py
    python examples/lca-checker/query_japfa_demo.py "your custom query here"
"""

import os
import sys

from openbench.core.abstractions import Query
from openbench.data.stores import PineconeStore
from openbench.intelligence import GoogleEmbeddingProvider

INDEX_NAME = os.getenv("PINECONE_INDEX", "openbench")
NAMESPACE = "japfa"


def check_keys():
    missing = []
    if not os.getenv("PINECONE_API_KEY"):
        missing.append("PINECONE_API_KEY")
    if not os.getenv("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")
    if missing:
        print(f"Missing env vars: {', '.join(missing)}")
        sys.exit(1)


def build_store() -> PineconeStore:
    """Build PineconeStore pointing to japfa namespace."""
    provider = GoogleEmbeddingProvider(model="gemini-embedding-001", dimension=768)
    return PineconeStore(
        index_name=INDEX_NAME,
        namespace=NAMESPACE,
        embedding_provider=provider,
        create_if_missing=False,  # namespace already exists
    )


def show_index_stats(store: PineconeStore):
    """Print index statistics including japfa namespace vector count."""
    stats = store.describe_index()
    print(f"Index: {stats['index_name']}")
    print(f"Dimension: {stats['dimension']}")
    print(f"Total vectors: {stats['total_vector_count']}")
    print("Namespaces:")
    for ns, data in stats["namespaces"].items():
        marker = " <-- target" if ns == NAMESPACE else ""
        print(f"  {ns}: {data['vector_count']} vectors{marker}")
    print()


def search(store: PineconeStore, query_text: str, limit: int = 5, filters: dict | None = None):
    """Run semantic search and print results."""
    print(f'Query: "{query_text}"')
    if filters:
        print(f"Filter: {filters}")
    print("-" * 60)

    query = Query(text=query_text, limit=limit, filters=filters)
    results = store.search(query)

    if not results.items:
        print("  No results found.\n")
        return results

    for i, (item, score) in enumerate(zip(results.items, results.scores, strict=False), 1):
        meta = item.get("metadata", {})
        content = meta.get("content", "")[:200]
        # Show key metadata fields
        meta_display = {k: v for k, v in meta.items() if k not in ("content", "content_hash")}
        print(f"\n  {i}. [score: {score:.4f}]")
        if meta_display:
            for k, v in list(meta_display.items())[:6]:
                val = str(v)[:80]
                print(f"     {k}: {val}")
        if content:
            print(f"     content: {content}...")

    print(f"\nTotal: {results.total} results\n")
    return results


def main():
    check_keys()

    print("=" * 60)
    print(f"Querying Pinecone: index={INDEX_NAME}, namespace={NAMESPACE}")
    print("=" * 60)
    print()

    store = build_store()
    show_index_stats(store)

    # Custom query from CLI argument
    if len(sys.argv) > 1:
        search(store, " ".join(sys.argv[1:]))
        return

    # Default demo queries
    demo_queries = [
        "environmental impact assessment",
        "carbon emission reduction",
        "sustainability report",
        "waste management",
        "energy consumption",
    ]

    for q in demo_queries:
        search(store, q)

    # Example: filtered search (uncomment and adjust field name as needed)
    # search(store, "emission factor", filters={"source_type": "report"})


if __name__ == "__main__":
    main()
