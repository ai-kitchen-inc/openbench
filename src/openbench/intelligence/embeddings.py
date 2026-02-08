"""
Embedding providers for OpenBench.

Provides implementation-agnostic embedding generation with auto-detection
of dimensions and model capabilities.
"""

import os

from openbench.core.abstractions import EmbeddingProvider
from openbench.core.config import EMBEDDING_MODELS


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

        response = client.embeddings.create(
            input=text,
            model=model,
        )

        return response.data[0].embedding

    def embed_batch(
        self, texts: list[str], model: str | None = None, batch_size: int = 100
    ) -> list[list[float]]:
        model = model or self._model
        client = self._get_client()

        embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = client.embeddings.create(
                input=batch,
                model=model,
            )
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
    - text-embedding-004 (768 dimensions)
    - textembedding-gecko@003 (768 dimensions)
    - textembedding-gecko-multilingual@001 (768 dimensions)

    Custom models also supported - specify dimension manually.

    Example:
        >>> provider = GoogleEmbeddingProvider()
        >>> embedding = provider.embed("Hello, world!")
        >>> len(embedding)
        768

        >>> # Use custom/new model with explicit dimension
        >>> provider = GoogleEmbeddingProvider(
        ...     model="text-embedding-005",
        ...     dimension=1024
        ... )
    """

    MODELS = {
        "text-embedding-004": 768,
        "textembedding-gecko@003": 768,
        "textembedding-gecko-multilingual@001": 768,
    }

    def __init__(
        self,
        model: str = "text-embedding-004",
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

        result = genai.embed_content(
            model=f"models/{model}",
            content=text,
            task_type="retrieval_document",
        )

        return result["embedding"]

    def embed_batch(
        self, texts: list[str], model: str | None = None, batch_size: int = 100
    ) -> list[list[float]]:
        self._configure()
        import google.generativeai as genai

        model = model or self._model
        embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            # Google API supports batch embedding
            result = genai.embed_content(
                model=f"models/{model}",
                content=batch,
                task_type="retrieval_document",
            )
            embeddings.extend(result["embedding"])

        return embeddings

    def list_models(self) -> dict[str, int]:
        return dict(self.MODELS)


# Provider registry for dynamic resolution
EMBEDDING_PROVIDERS = {
    "openai": OpenAIEmbeddingProvider,
    "google": GoogleEmbeddingProvider,
}


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
        return provider_class(model=model, **kwargs)
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
