"""
Dynamic Embedding Registration Demo

Demonstrates runtime registration of new embedding models and providers
without modifying source code.

No API keys required — uses mock provider for demonstration.

Usage:
    python examples/embeddings/dynamic_registration_demo.py

Three patterns:
    1. Register a new model to an existing provider
    2. Register a completely new provider with its own models
    3. Use registered models with resolve_embedding_provider()
"""

from openbench.core.abstractions import EmbeddingProvider
from openbench.core.config import list_embedding_models
from openbench.intelligence import (
    EMBEDDING_PROVIDERS,
    get_embedding_provider,
    register_model,
    register_provider,
    resolve_embedding_provider,
)


# ---------------------------------------------------------------------------
# Mock provider for demo (no API key needed)
# ---------------------------------------------------------------------------
class MockEmbeddingProvider(EmbeddingProvider):
    """Minimal embedding provider that returns deterministic vectors."""

    MODELS = {
        "mock-small": 384,
        "mock-large": 1024,
    }

    def __init__(self, model: str = "mock-small", **kwargs):
        self._model = model

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def default_model(self) -> str:
        return self._model

    def get_dimension(self, model: str | None = None) -> int:
        model = model or self._model
        if model in self.MODELS:
            return self.MODELS[model]
        raise ValueError(f"Unknown model: {model}")

    def embed(self, text: str, model: str | None = None) -> list[float]:
        dim = self.get_dimension(model)
        # Deterministic: hash text to produce repeatable vectors
        seed = hash(text) % 10000
        return [(seed + i) / 10000.0 for i in range(dim)]

    def embed_batch(
        self, texts: list[str], model: str | None = None, **kwargs
    ) -> list[list[float]]:
        return [self.embed(t, model) for t in texts]

    def list_models(self) -> dict[str, int]:
        return dict(self.MODELS)


# ---------------------------------------------------------------------------
# Demo 1: Register new model to existing provider
# ---------------------------------------------------------------------------
def demo_register_model():
    print("=" * 60)
    print("Demo 1: Register New Model to Existing Provider")
    print("=" * 60)

    print("\nBefore registration:")
    print(f"  OpenAI models: {list_embedding_models('openai')}")

    # Scenario: OpenAI releases text-embedding-4
    register_model("openai", "text-embedding-4", 2048)

    print("\nAfter register_model('openai', 'text-embedding-4', 2048):")
    print(f"  OpenAI models: {list_embedding_models('openai')}")

    # Now the provider recognizes it
    provider = get_embedding_provider("openai", model="text-embedding-4")
    print(f"\n  provider.get_dimension() = {provider.get_dimension()}")
    print("  (API call would work once OpenAI releases the model)")


# ---------------------------------------------------------------------------
# Demo 2: Register a completely new provider
# ---------------------------------------------------------------------------
def demo_register_provider():
    print("\n" + "=" * 60)
    print("Demo 2: Register New Provider")
    print("=" * 60)

    print("\nBefore registration:")
    print(f"  Available providers: {list(EMBEDDING_PROVIDERS.keys())}")

    # Register mock provider
    register_provider("mock", MockEmbeddingProvider)

    print("\nAfter register_provider('mock', MockEmbeddingProvider):")
    print(f"  Available providers: {list(EMBEDDING_PROVIDERS.keys())}")
    print(f"  Mock models: {list_embedding_models('mock')}")

    # Use the new provider
    provider = get_embedding_provider("mock", model="mock-large")
    print(f"\n  provider.provider_name = '{provider.provider_name}'")
    print(f"  provider.get_dimension() = {provider.get_dimension()}")

    # Generate embeddings
    embedding = provider.embed("Hello from the mock provider!")
    print(
        f"  embed('Hello...') -> [{embedding[0]:.4f}, {embedding[1]:.4f}, ...] ({len(embedding)} dims)"
    )


# ---------------------------------------------------------------------------
# Demo 3: Add models to custom provider + resolve_embedding_provider
# ---------------------------------------------------------------------------
def demo_resolve_with_registry():
    print("\n" + "=" * 60)
    print("Demo 3: Resolve Provider from Model Name")
    print("=" * 60)

    # Add another model to mock provider
    register_model("mock", "mock-xl", 2048)
    print("\nRegistered 'mock-xl' (2048 dims) to mock provider")

    # Global registry now knows about mock-xl
    all_models = list_embedding_models()
    print(f"\nAll registered models ({len(all_models)}):")
    for model, dim in sorted(all_models.items()):
        print(f"  {model}: {dim} dims")

    # resolve_embedding_provider auto-detects provider from model name
    provider = resolve_embedding_provider(model="mock-xl")
    print("\nresolve_embedding_provider(model='mock-xl'):")
    print(f"  -> {provider.__class__.__name__} (provider: '{provider.provider_name}')")
    print(f"  -> dimension: {provider.get_dimension()}")

    # Batch embed
    texts = ["First document", "Second document", "Third document"]
    embeddings = provider.embed_batch(texts)
    print(
        f"\n  embed_batch({len(texts)} texts) -> {len(embeddings)} vectors of {len(embeddings[0])} dims"
    )


# ---------------------------------------------------------------------------
# Demo 4: Error handling
# ---------------------------------------------------------------------------
def demo_error_handling():
    print("\n" + "=" * 60)
    print("Demo 4: Error Handling")
    print("=" * 60)

    # 1. Unknown provider
    print("\nregister_model('nonexistent', 'model', 768):")
    try:
        register_model("nonexistent", "model", 768)
    except ValueError as e:
        print(f"  ValueError: {e}")

    # 2. Invalid provider class
    print("\nregister_provider('bad', 'not a class'):")
    try:
        register_provider("bad", "not a class")
    except TypeError as e:
        print(f"  TypeError: {e}")

    # 3. Non-EmbeddingProvider class
    print("\nregister_provider('bad', dict):")
    try:
        register_provider("bad", dict)
    except TypeError as e:
        print(f"  TypeError: {e}")


# ---------------------------------------------------------------------------
# Cleanup: restore original state
# ---------------------------------------------------------------------------
def cleanup():
    """Remove demo registrations to avoid side effects."""
    # Remove text-embedding-4 from OpenAI
    from openbench.intelligence.embeddings import OpenAIEmbeddingProvider

    OpenAIEmbeddingProvider.MODELS.pop("text-embedding-4", None)

    # Remove mock provider
    EMBEDDING_PROVIDERS.pop("mock", None)

    # Remove mock-xl (already gone with mock provider removal)
    from openbench.core.config import invalidate_embedding_cache

    invalidate_embedding_cache()


if __name__ == "__main__":
    print("OpenBench Dynamic Embedding Registration Demo")
    print("No API keys required — uses mock provider")
    print()

    try:
        demo_register_model()
        demo_register_provider()
        demo_resolve_with_registry()
        demo_error_handling()
    finally:
        cleanup()

    print("\n" + "=" * 60)
    print("Demo Complete!")
    print("=" * 60)
