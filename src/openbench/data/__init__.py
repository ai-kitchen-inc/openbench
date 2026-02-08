"""Data layer for OpenBench - sources, transforms, and stores."""

from openbench.data.exceptions import (
    DataLayerError,
    ExtractionError,
    FileNotFoundError,
    SourceError,
    UnsupportedFormatError,
    ValidationError,
)
from openbench.data.sources import GroundedSearchSource, LangExtractSource, PDFSource
from openbench.data.stores import (
    Chunk,
    ChunkingConfig,
    DimensionMismatchError,
    EmbeddingError,
    IndexNotFoundError,
    InvalidQueryError,
    ItemNotFoundError,
    QuotaExceededError,
    StoreConnectionError,
    StoreError,
    chunk_raw_data,
    chunk_text,
)

__all__ = [
    # Sources
    "PDFSource",
    "GroundedSearchSource",
    "LangExtractSource",
    # Store utilities
    "Chunk",
    "ChunkingConfig",
    "chunk_text",
    "chunk_raw_data",
    # Data exceptions
    "DataLayerError",
    "SourceError",
    "ExtractionError",
    "ValidationError",
    "FileNotFoundError",
    "UnsupportedFormatError",
    # Store exceptions
    "StoreError",
    "IndexNotFoundError",
    "StoreConnectionError",
    "DimensionMismatchError",
    "QuotaExceededError",
    "EmbeddingError",
    "ItemNotFoundError",
    "InvalidQueryError",
]


# Lazy import for PineconeStore
def __getattr__(name: str):
    if name == "PineconeStore":
        from openbench.data.stores import PineconeStore

        return PineconeStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
