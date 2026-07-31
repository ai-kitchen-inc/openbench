"""Data stores for OpenBench - vector stores, databases, and caches."""

from openbench.data.stores.base import (
    Chunk,
    ChunkingConfig,
    EmbeddingMixin,
    chunk_raw_data,
    chunk_text,
)
from openbench.data.stores.document_index import (
    ChunkRow,
    DocumentIndexBackend,
    DocumentIndexStore,
    PgVectorBackend,
    SQLiteDocumentBackend,
    build_document_index,
)
from openbench.data.stores.exceptions import (
    DimensionMismatchError,
    EmbeddingError,
    IndexNotFoundError,
    InvalidQueryError,
    ItemNotFoundError,
    QuotaExceededError,
    StoreConnectionError,
    StoreError,
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
            ) from None
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
    "ChunkRow",
    "DocumentIndexBackend",
    "DocumentIndexStore",
    "PgVectorBackend",
    "SQLiteDocumentBackend",
    "build_document_index",
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
