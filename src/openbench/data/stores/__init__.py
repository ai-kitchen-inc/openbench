"""Data stores for OpenBench - vector stores, databases, and caches."""

from openbench.data.stores.base import (
    Chunk,
    ChunkingConfig,
    EmbeddingMixin,
    chunk_text,
    chunk_raw_data,
)
from openbench.data.stores.exceptions import (
    StoreError,
    IndexNotFoundError,
    StoreConnectionError,
    DimensionMismatchError,
    QuotaExceededError,
    EmbeddingError,
    ItemNotFoundError,
    InvalidQueryError,
)

# Lazy import for optional dependency
def __getattr__(name: str):
    if name == "PineconeStore":
        try:
            from openbench.data.stores.pinecone import PineconeStore
            return PineconeStore
        except ImportError:
            raise ImportError(
                "PineconeStore requires pinecone-client. "
                "Install with: pip install openbench[vector]"
            )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Base utilities
    "Chunk",
    "ChunkingConfig",
    "EmbeddingMixin",
    "chunk_text",
    "chunk_raw_data",
    # Stores
    "PineconeStore",
    # Exceptions
    "StoreError",
    "IndexNotFoundError",
    "StoreConnectionError",
    "DimensionMismatchError",
    "QuotaExceededError",
    "EmbeddingError",
    "ItemNotFoundError",
    "InvalidQueryError",
]
