"""
Pinecone Store Demo - Real Case

Demonstrates vector storage and semantic search with PineconeStore.
Requires:
    - PINECONE_API_KEY environment variable
    - GOOGLE_API_KEY environment variable

Usage:
    export PINECONE_API_KEY=your-pinecone-api-key
    export GOOGLE_API_KEY=your-google-api-key
    python examples/stores/pinecone_store_demo.py
"""

import os
import sys
import time

from openbench.core.abstractions import RawData
from openbench.data.stores import PineconeStore
from openbench.data.stores.base import ChunkingConfig
from openbench.intelligence import GoogleEmbeddingProvider


def check_api_keys():
    """Check if required API keys are set."""
    missing = []
    if not os.getenv("PINECONE_API_KEY"):
        missing.append("PINECONE_API_KEY")
    if not os.getenv("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")

    if missing:
        print("Error: Missing environment variables:")
        for key in missing:
            print(f"  - {key}")
        print()
        print("Set them with:")
        print("  export PINECONE_API_KEY=your-pinecone-api-key")
        print("  export GOOGLE_API_KEY=your-google-api-key")
        sys.exit(1)


def create_sample_documents():
    """Create sample documents for indexing."""
    documents = [
        {
            "title": "Introduction to Machine Learning",
            "content": """
            Machine learning is a subset of artificial intelligence that enables
            computers to learn from data without being explicitly programmed.
            There are three main types: supervised learning, unsupervised learning,
            and reinforcement learning. Supervised learning uses labeled data to
            train models, while unsupervised learning finds patterns in unlabeled data.
            """,
            "category": "ai",
            "author": "Dr. Smith",
        },
        {
            "title": "Deep Learning Fundamentals",
            "content": """
            Deep learning is a subset of machine learning based on artificial neural
            networks with multiple layers. These networks can learn complex patterns
            in data through backpropagation. Popular architectures include CNNs for
            image processing and RNNs/Transformers for sequential data like text.
            """,
            "category": "ai",
            "author": "Dr. Johnson",
        },
        {
            "title": "Natural Language Processing",
            "content": """
            Natural Language Processing (NLP) enables computers to understand,
            interpret, and generate human language. Key tasks include sentiment
            analysis, named entity recognition, machine translation, and question
            answering. Modern NLP heavily relies on transformer models like BERT
            and GPT.
            """,
            "category": "ai",
            "author": "Dr. Lee",
        },
        {
            "title": "Cloud Computing Overview",
            "content": """
            Cloud computing delivers computing services over the internet, including
            servers, storage, databases, networking, and software. Major providers
            include AWS, Google Cloud, and Azure. Benefits include scalability,
            cost-efficiency, and reduced IT maintenance.
            """,
            "category": "infrastructure",
            "author": "Dr. Williams",
        },
        {
            "title": "Database Systems",
            "content": """
            Database systems organize and store data for efficient retrieval.
            Relational databases use SQL and tables with relationships. NoSQL
            databases offer flexibility for unstructured data. Vector databases
            are optimized for similarity search with embeddings.
            """,
            "category": "infrastructure",
            "author": "Dr. Brown",
        },
    ]
    return documents


def demo_initialize_store():
    """Initialize PineconeStore with Google embeddings."""
    print("=" * 60)
    print("Demo 1: Initialize PineconeStore")
    print("=" * 60)

    # Create embedding provider
    embedding_provider = GoogleEmbeddingProvider(model="text-embedding-004")
    print(f"\nEmbedding Provider: {embedding_provider.provider_name}")
    print(f"Model: {embedding_provider.default_model}")
    print(f"Dimension: {embedding_provider.get_dimension()}")

    index_name = "openbench"

    # Initialize store with auto-detected dimension
    store = PineconeStore(
        index_name=index_name,
        embedding_provider=embedding_provider,
        namespace="demo-namespace",
        create_if_missing=True,
    )

    print(f"\nPinecone Index: {index_name}")
    print(f"Namespace: {store.namespace}")
    print(f"Store Type: {store.store_type}")

    return store


def demo_index_documents(store):
    """Index documents into PineconeStore."""
    print("\n" + "=" * 60)
    print("Demo 2: Index Documents")
    print("=" * 60)

    documents = create_sample_documents()
    print(f"\nIndexing {len(documents)} documents...")

    indexed_ids = []
    for doc in documents:
        # Create RawData from document
        raw_data = RawData(
            content=doc["content"].strip(),
            content_type="text",
            metadata={
                "title": doc["title"],
                "category": doc["category"],
                "author": doc["author"],
            },
            source=None,
        )

        # Index the document
        source_id = store.index(raw_data)
        indexed_ids.append(source_id)
        print(f"  Indexed: {doc['title']}")

    print(f"\nTotal indexed: {len(indexed_ids)} documents")

    # Wait for indexing to complete
    print("\nWaiting for vectors to be available...")
    time.sleep(3)

    # Show index stats
    stats = store.describe_index()
    print("\nIndex Statistics:")
    print(f"  Dimension: {stats['dimension']}")
    print(f"  Total vectors: {stats['total_vector_count']}")
    print(f"  Namespaces: {list(stats['namespaces'].keys())}")


def demo_semantic_search(store):
    """Demonstrate semantic search."""
    print("\n" + "=" * 60)
    print("Demo 3: Semantic Search")
    print("=" * 60)

    from openbench.core.abstractions import Query

    queries = [
        "How do neural networks learn?",
        "What is the difference between SQL and NoSQL?",
        "Explain transformer models for text",
    ]

    for query_text in queries:
        print(f'\nQuery: "{query_text}"')
        print("-" * 40)

        query = Query(text=query_text, limit=3)
        results = store.search(query)

        print(f"Found {results.total} results:")
        for i, (item, score) in enumerate(zip(results.items, results.scores, strict=False), 1):
            title = item["metadata"].get("title", "Unknown")
            category = item["metadata"].get("category", "N/A")
            print(f"  {i}. [{score:.4f}] {title} ({category})")


def demo_filtered_search(store):
    """Demonstrate search with metadata filters."""
    print("\n" + "=" * 60)
    print("Demo 4: Filtered Search")
    print("=" * 60)

    from openbench.core.abstractions import Query

    print("\nSearch: 'learning' with filter category='ai'")
    print("-" * 40)

    query = Query(
        text="learning",
        limit=5,
        filters={"category": "ai"},
    )
    results = store.search(query)

    print(f"Found {results.total} results (AI category only):")
    for i, (item, score) in enumerate(zip(results.items, results.scores, strict=False), 1):
        title = item["metadata"].get("title", "Unknown")
        author = item["metadata"].get("author", "N/A")
        print(f"  {i}. [{score:.4f}] {title} by {author}")


def demo_crud_operations(store):
    """Demonstrate CRUD operations."""
    print("\n" + "=" * 60)
    print("Demo 5: CRUD Operations")
    print("=" * 60)

    # Create a new document
    print("\n[CREATE] Adding new document...")
    new_doc = RawData(
        content="Kubernetes orchestrates containerized applications across clusters.",
        content_type="text",
        metadata={
            "title": "Kubernetes Overview",
            "category": "devops",
            "author": "Dr. Chen",
        },
        source=None,
    )
    source_id = store.index(new_doc)
    print(f"  Created document with source_id: {source_id}")

    time.sleep(2)  # Wait for indexing

    # Search for the new document
    from openbench.core.abstractions import Query

    query = Query(text="container orchestration", limit=1)
    results = store.search(query)

    if results.items:
        item = results.items[0]
        item_id = item["id"]
        print(f"\n[READ] Found item: {item_id}")
        print(f"  Title: {item['metadata'].get('title')}")
        print(f"  Score: {results.scores[0]:.4f}")

        # Update the document
        print("\n[UPDATE] Updating metadata...")
        success = store.update(item_id, {"version": "2.0", "reviewed": True})
        print(f"  Update successful: {success}")

        # Read updated item
        updated = store.get(item_id)
        if updated:
            print(
                f"  New metadata: version={updated['metadata'].get('version')}, "
                f"reviewed={updated['metadata'].get('reviewed')}"
            )

        # Delete the document
        print("\n[DELETE] Removing item...")
        deleted = store.delete(item_id)
        print(f"  Delete successful: {deleted}")


def demo_chunking_config(store):
    """Demonstrate custom chunking configuration."""
    print("\n" + "=" * 60)
    print("Demo 6: Custom Chunking")
    print("=" * 60)

    # Create a longer document

    # Create store with custom chunking
    GoogleEmbeddingProvider(model="text-embedding-004")

    custom_config = ChunkingConfig(
        strategy="sentence",
        chunk_size=200,  # Smaller chunks
        overlap=50,  # Some overlap
    )

    print("\nChunking Config:")
    print(f"  Strategy: {custom_config.strategy}")
    print(f"  Chunk Size: {custom_config.chunk_size}")
    print(f"  Overlap: {custom_config.overlap}")

    # Note: In real usage, you'd create a new store with the config
    # store = PineconeStore(..., chunking_config=custom_config)

    print("\n  Chunking with custom config would split the document into")
    print("  smaller, overlapping chunks for better retrieval precision.")


if __name__ == "__main__":
    print("OpenBench PineconeStore - Real Case Demo")
    print("Provider: Pinecone + Google Embeddings")
    print()

    check_api_keys()

    try:
        store = demo_initialize_store()
        demo_index_documents(store)
        # demo_semantic_search(store)
        # demo_filtered_search(store)
        # demo_crud_operations(store)
        # demo_chunking_config(store)

        print("\n" + "=" * 60)
        print("Demo Complete!")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user.")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback

        traceback.print_exc()
