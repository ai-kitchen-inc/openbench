"""
Embedding providers for OpenBench.

Provides implementation-agnostic embedding generation with auto-detection
of dimensions and model capabilities.
"""

from __future__ import annotations

import os

from openbench.core.abstractions import EmbeddingProvider
from openbench.core.config import EMBEDDING_MODELS, invalidate_embedding_cache
from openbench.core.constants import DEFAULT_EMBED_BATCH_SIZE


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    OpenAI embedding provider.

    Official supported models (community contributions welcome!):
    - text-embedding-3-small (1536 dimensions)
    - text-embedding-3-large (3072 dimensions)
    - text-embedding-ada-002 (1536 dimensions, legacy)

    Custom models also supported - specify dimension manually.

    Example:
        >>> provider = OpenAIEmbeddingProvider()
        >>> embedding = provider.embed("Hello, world!")
        >>> len(embedding)
        1536

        >>> # Use official model
        >>> provider = OpenAIEmbeddingProvider(model="text-embedding-3-large")
        >>> provider.get_dimension()
        3072

        >>> # Use custom/new model with explicit dimension
        >>> provider = OpenAIEmbeddingProvider(
        ...     model="text-embedding-4",
        ...     dimension=2048
        ... )
    """

    MODELS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        dimension: int | None = None,
    ):
        """
        Initialize OpenAI embedding provider.

        Args:
            model: Embedding model to use.
            api_key: OpenAI API key. Falls back to OPENAI_API_KEY env var.
            dimension: Vector dimension override for custom/new models.
        """
        self._model = model
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._custom_dimension = dimension
        self._client = None

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return self._model

    def get_dimension(self, model: str | None = None) -> int:
        model = model or self._model

        # 1. Custom dimension override
        if self._custom_dimension is not None:
            return self._custom_dimension

        # 2. Known/official models
        if model in self.MODELS:
            return self.MODELS[model]

        # 3. Unknown model - guide user
        raise ValueError(
            f"Unknown model '{model}'. Options:\n"
            f"  1. Use official models: {list(self.MODELS.keys())}\n"
            f"  2. Specify dimension: OpenAIEmbeddingProvider(model='{model}', dimension=<dim>)\n"
            f"  3. Contribute: Add model to MODELS dict via PR"
        )

    def _get_client(self):
        """Get or create OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError:
                raise ImportError(
                    "openai package required. Install with: pip install openai"
                ) from None

            if not self._api_key:
                raise ValueError(
                    "OpenAI API key required. Set OPENAI_API_KEY environment variable "
                    "or pass api_key to constructor."
                )

            self._client = OpenAI(api_key=self._api_key)

        return self._client

    def embed(self, text: str, model: str | None = None) -> list[float]:
        model = model or self._model
        client = self._get_client()

        kwargs = {"input": text, "model": model}
        # Dimension shortening (text-embedding-3-small/large support this)
        if self._custom_dimension is not None:
            kwargs["dimensions"] = int(self._custom_dimension)

        response = client.embeddings.create(**kwargs)

        return response.data[0].embedding

    def embed_batch(
        self, texts: list[str], model: str | None = None, batch_size: int = DEFAULT_EMBED_BATCH_SIZE
    ) -> list[list[float]]:
        model = model or self._model
        client = self._get_client()

        embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            kwargs = {"input": batch, "model": model}
            if self._custom_dimension is not None:
                kwargs["dimensions"] = int(self._custom_dimension)

            response = client.embeddings.create(**kwargs)
            # Sort by index to maintain order
            sorted_data = sorted(response.data, key=lambda x: x.index)
            embeddings.extend([d.embedding for d in sorted_data])

        return embeddings

    def list_models(self) -> dict[str, int]:
        return dict(self.MODELS)


class GoogleEmbeddingProvider(EmbeddingProvider):
    """
    Google embedding provider using Generative AI API.

    Official supported models (community contributions welcome!):
    - gemini-embedding-001 (3072 dimensions, default — supports MRL dimension scaling)
    - textembedding-gecko@003 (768 dimensions, legacy)
    - textembedding-gecko-multilingual@001 (768 dimensions, legacy)

    Custom models also supported - specify dimension manually.

    Note: text-embedding-004 was shut down January 14, 2026.
    Use gemini-embedding-001 instead.

    Example:
        >>> provider = GoogleEmbeddingProvider()
        >>> embedding = provider.embed("Hello, world!")
        >>> len(embedding)
        3072

        >>> # Use with custom dimension (MRL scaling)
        >>> provider = GoogleEmbeddingProvider(
        ...     model="gemini-embedding-001",
        ...     dimension=768
        ... )
    """

    MODELS = {
        "gemini-embedding-001": 3072,
        "textembedding-gecko@003": 768,
        "textembedding-gecko-multilingual@001": 768,
    }

    def __init__(
        self,
        model: str = "gemini-embedding-001",
        api_key: str | None = None,
        dimension: int | None = None,
    ):
        """
        Initialize Google embedding provider.

        Args:
            model: Embedding model to use.
            api_key: Google API key. Falls back to GOOGLE_API_KEY env var.
            dimension: Vector dimension override for custom/new models.
        """
        self._model = model
        self._api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self._custom_dimension = dimension
        self._configured = False

    @property
    def provider_name(self) -> str:
        return "google"

    @property
    def default_model(self) -> str:
        return self._model

    def get_dimension(self, model: str | None = None) -> int:
        model = model or self._model

        # 1. Custom dimension override
        if self._custom_dimension is not None:
            return self._custom_dimension

        # 2. Known/official models
        if model in self.MODELS:
            return self.MODELS[model]

        # 3. Unknown model - guide user
        raise ValueError(
            f"Unknown model '{model}'. Options:\n"
            f"  1. Use official models: {list(self.MODELS.keys())}\n"
            f"  2. Specify dimension: GoogleEmbeddingProvider(model='{model}', dimension=<dim>)\n"
            f"  3. Contribute: Add model to MODELS dict via PR"
        )

    def _configure(self):
        """Configure Google Generative AI."""
        if self._configured:
            return

        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "google-generativeai package required. "
                "Install with: pip install google-generativeai"
            ) from None

        if not self._api_key:
            raise ValueError(
                "Google API key required. Set GOOGLE_API_KEY environment variable "
                "or pass api_key to constructor."
            )

        genai.configure(api_key=self._api_key)
        self._configured = True

    def embed(self, text: str, model: str | None = None) -> list[float]:
        self._configure()
        import google.generativeai as genai

        model = model or self._model

        kwargs = {
            "model": f"models/{model}",
            "content": text,
            "task_type": "retrieval_document",
        }
        # MRL dimension scaling (gemini-embedding-001 supports this)
        if self._custom_dimension is not None:
            kwargs["output_dimensionality"] = int(self._custom_dimension)

        result = genai.embed_content(**kwargs)

        return result["embedding"]

    def embed_batch(
        self, texts: list[str], model: str | None = None, batch_size: int = DEFAULT_EMBED_BATCH_SIZE
    ) -> list[list[float]]:
        self._configure()
        import google.generativeai as genai

        model = model or self._model
        embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            kwargs = {
                "model": f"models/{model}",
                "content": batch,
                "task_type": "retrieval_document",
            }
            if self._custom_dimension is not None:
                kwargs["output_dimensionality"] = int(self._custom_dimension)

            result = genai.embed_content(**kwargs)
            embeddings.extend(result["embedding"])

        return embeddings

    def list_models(self) -> dict[str, int]:
        return dict(self.MODELS)


# Provider registry for dynamic resolution
EMBEDDING_PROVIDERS: dict[str, type[EmbeddingProvider]] = {
    "openai": OpenAIEmbeddingProvider,
    "google": GoogleEmbeddingProvider,
}


def register_model(provider: str, model: str, dimension: int) -> None:
    """Register a new embedding model at runtime.

    Adds the model to the provider's MODELS dict and invalidates
    the global EMBEDDING_MODELS cache so it picks up the change.

    Args:
        provider: Provider name ('openai', 'google', or custom).
        model: Model name (e.g., 'gemini-embedding-002').
        dimension: Vector dimension for this model.

    Raises:
        ValueError: If provider is not registered.

    Example:
        >>> register_model("google", "gemini-embedding-002", 3072)
        >>> provider = GoogleEmbeddingProvider(model="gemini-embedding-002")
        >>> provider.get_dimension()
        3072
    """
    if provider not in EMBEDDING_PROVIDERS:
        raise ValueError(
            f"Unknown provider '{provider}'. "
            f"Register it first with register_provider(). "
            f"Available: {list(EMBEDDING_PROVIDERS.keys())}"
        )

    provider_class = EMBEDDING_PROVIDERS[provider]
    if not hasattr(provider_class, "MODELS"):
        provider_class.MODELS = {}

    provider_class.MODELS[model] = dimension
    invalidate_embedding_cache()


def register_provider(name: str, provider_class: type[EmbeddingProvider]) -> None:
    """Register a new embedding provider at runtime.

    Args:
        name: Provider name (e.g., 'cohere', 'voyage').
        provider_class: Provider class (must inherit EmbeddingProvider).

    Raises:
        TypeError: If provider_class is not an EmbeddingProvider subclass.

    Example:
        >>> class CohereEmbeddingProvider(EmbeddingProvider):
        ...     MODELS = {"embed-v4": 1024}
        ...     ...
        >>> register_provider("cohere", CohereEmbeddingProvider)
        >>> provider = get_embedding_provider("cohere")
    """
    if not (isinstance(provider_class, type) and issubclass(provider_class, EmbeddingProvider)):
        raise TypeError(
            f"provider_class must be an EmbeddingProvider subclass, got {type(provider_class)}"
        )

    EMBEDDING_PROVIDERS[name] = provider_class
    invalidate_embedding_cache()


def get_embedding_provider(provider: str, model: str | None = None, **kwargs) -> EmbeddingProvider:
    """
    Get an embedding provider by name.

    Args:
        provider: Provider name ('openai', 'google').
        model: Model to use (optional, uses provider default).
        **kwargs: Additional provider-specific arguments.

    Returns:
        EmbeddingProvider instance.

    Raises:
        ValueError: If provider is unknown.
    """
    if provider not in EMBEDDING_PROVIDERS:
        raise ValueError(
            f"Unknown embedding provider: {provider}. Available: {list(EMBEDDING_PROVIDERS.keys())}"
        )

    provider_class = EMBEDDING_PROVIDERS[provider]

    if model:
        return provider_class(model=model, **kwargs)  # type: ignore[call-arg]
    return provider_class(**kwargs)


def resolve_embedding_provider(
    model: str | None = None, provider: str | None = None, **kwargs
) -> EmbeddingProvider:
    """
    Resolve an embedding provider from model or provider name.

    Priority:
    1. If provider specified, use that provider
    2. If model specified, look up provider from EMBEDDING_MODELS
    3. Fall back to OpenAI with default model

    Args:
        model: Embedding model name.
        provider: Provider name.
        **kwargs: Additional provider-specific arguments.

    Returns:
        EmbeddingProvider instance.
    """
    # If provider specified, use it
    if provider:
        return get_embedding_provider(provider, model=model, **kwargs)

    # If model specified, look up provider
    if model and model in EMBEDDING_MODELS:
        provider_name = EMBEDDING_MODELS[model]["provider"]
        return get_embedding_provider(provider_name, model=model, **kwargs)

    # Default to OpenAI
    return OpenAIEmbeddingProvider(model=model or "text-embedding-3-small", **kwargs)
