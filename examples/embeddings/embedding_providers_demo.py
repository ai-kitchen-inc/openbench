"""
Embedding Providers Demo - Real Case

Demonstrates embedding generation with Google provider.
Requires: GOOGLE_API_KEY environment variable

Usage:
    export GOOGLE_API_KEY=your-api-key
    python examples/embeddings/embedding_providers_demo.py
"""

import os
import sys

from openbench.intelligence import GoogleEmbeddingProvider


def check_api_key():
    """Check if API key is set."""
    if not os.getenv("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY environment variable not set")
        print()
        print("Set it with:")
        print("  export GOOGLE_API_KEY=your-api-key")
        sys.exit(1)


def demo_single_embedding():
    """Generate embedding for a single text."""
    print("=" * 60)
    print("Demo 1: Single Text Embedding")
    print("=" * 60)

    provider = GoogleEmbeddingProvider(model="text-embedding-004")

    text = "OpenBench is a workflow orchestrator for AI agents."
    print(f"\nText: {text}")

    embedding = provider.embed(text)

    print(f"Model: {provider.default_model}")
    print(f"Dimension: {len(embedding)}")
    print(f"First 5 values: {embedding[:5]}")


def demo_batch_embedding():
    """Generate embeddings for multiple texts."""
    print("\n" + "=" * 60)
    print("Demo 2: Batch Embedding")
    print("=" * 60)

    provider = GoogleEmbeddingProvider(model="text-embedding-004")

    texts = [
        "Machine learning automates analytical model building.",
        "Deep learning uses neural networks with many layers.",
        "Natural language processing enables computers to understand text.",
    ]

    print(f"\nTexts ({len(texts)} items):")
    for i, text in enumerate(texts, 1):
        print(f"  {i}. {text[:50]}...")

    embeddings = provider.embed_batch(texts)

    print(f"\nGenerated {len(embeddings)} embeddings")
    print(f"Each embedding has {len(embeddings[0])} dimensions")


def demo_semantic_similarity():
    """Demonstrate semantic similarity using embeddings."""
    print("\n" + "=" * 60)
    print("Demo 3: Semantic Similarity")
    print("=" * 60)

    provider = GoogleEmbeddingProvider(model="text-embedding-004")

    # Reference text
    query = "How to train a machine learning model?"

    # Candidate texts
    candidates = [
        "Steps to build and train ML models effectively.",  # Similar
        "The weather forecast for tomorrow is sunny.",      # Not similar
        "Training neural networks requires labeled data.",  # Similar
        "Best restaurants in Jakarta.",                     # Not similar
    ]

    print(f"\nQuery: {query}")
    print("\nCandidates:")

    # Get embeddings
    query_embedding = provider.embed(query)
    candidate_embeddings = provider.embed_batch(candidates)

    # Calculate cosine similarity
    def cosine_similarity(a, b):
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        return dot_product / (norm_a * norm_b)

    # Rank by similarity
    results = []
    for text, embedding in zip(candidates, candidate_embeddings):
        score = cosine_similarity(query_embedding, embedding)
        results.append((score, text))

    results.sort(reverse=True)

    for score, text in results:
        print(f"  {score:.4f} - {text}")


def demo_custom_model():
    """Using custom model with explicit dimension."""
    print("\n" + "=" * 60)
    print("Demo 4: Custom Model (Future-Proofing)")
    print("=" * 60)

    print("\nScenario: Google releases new model 'text-embedding-005'")
    print()

    # This allows using unreleased models
    provider = GoogleEmbeddingProvider(
        model="text-embedding-005",
        dimension=1024  # Specify dimension for unknown model
    )

    print(f"  provider = GoogleEmbeddingProvider(")
    print(f"      model='text-embedding-005',")
    print(f"      dimension=1024")
    print(f"  )")
    print(f"\n  Model: {provider.default_model}")
    print(f"  Dimension: {provider.get_dimension()}")
    print("\n  Note: API call will fail until model is released by Google")


if __name__ == "__main__":
    print("OpenBench Embedding Providers - Real Case Demo")
    print("Provider: Google")
    print()

    check_api_key()

    demo_single_embedding()
    demo_batch_embedding()
    demo_semantic_similarity()
    demo_custom_model()

    print("\n" + "=" * 60)
    print("Demo Complete!")
    print("=" * 60)
