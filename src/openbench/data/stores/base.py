"""Base utilities for data stores - chunking, embeddings, and shared functionality."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openbench.core.abstractions import RawData


@dataclass
class ChunkingConfig:
    """Configuration for text chunking.

    Attributes:
        chunk_size: Maximum characters per chunk.
        chunk_overlap: Number of overlapping characters between chunks.
        separators: Priority-ordered list of separators to split on.
    """

    chunk_size: int = 1000
    chunk_overlap: int = 200
    separators: list[str] = field(default_factory=lambda: ["\n\n", "\n", ". ", ", ", " "])

    def __post_init__(self):
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")


@dataclass
class Chunk:
    """A chunk of text extracted from a document.

    Attributes:
        id: Unique identifier for this chunk.
        content: The text content of the chunk.
        index: Position of this chunk in the document (0-indexed).
        total_chunks: Total number of chunks in the document.
        metadata: Additional metadata for the chunk.
    """

    id: str
    content: str
    index: int
    total_chunks: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """Generate SHA256 hash of the content."""
        return f"sha256:{hashlib.sha256(self.content.encode()).hexdigest()[:16]}"


def chunk_text(text: str, config: ChunkingConfig | None = None) -> list[str]:
    """Split text into chunks based on configuration.

    Uses a recursive splitting strategy:
    1. Try to split on preferred separators (paragraphs, lines, sentences)
    2. Fall back to character-based splitting if needed
    3. Maintain overlap between chunks for context continuity

    Args:
        text: The text to split into chunks.
        config: Chunking configuration. Uses defaults if not provided.

    Returns:
        List of text chunks.
    """
    if config is None:
        config = ChunkingConfig()

    if not text or not text.strip():
        return []

    text = text.strip()

    # If text is small enough, return as single chunk
    if len(text) <= config.chunk_size:
        return [text]

    chunks = []
    current_pos = 0

    while current_pos < len(text):
        # Calculate end position for this chunk
        end_pos = min(current_pos + config.chunk_size, len(text))

        # If we're not at the end, try to find a good break point
        if end_pos < len(text):
            # Look for separators in the last portion of the chunk
            search_start = max(current_pos, end_pos - config.chunk_overlap)
            best_break = end_pos

            for separator in config.separators:
                # Find the last occurrence of this separator
                sep_pos = text.rfind(separator, search_start, end_pos)
                if sep_pos > current_pos:
                    best_break = sep_pos + len(separator)
                    break

            end_pos = best_break

        # Extract the chunk
        chunk = text[current_pos:end_pos].strip()
        if chunk:
            chunks.append(chunk)

        # Move position forward, accounting for overlap
        if end_pos >= len(text):
            break

        # Calculate next start position with overlap
        current_pos = max(current_pos + 1, end_pos - config.chunk_overlap)

    return chunks


def chunk_raw_data(data: RawData, config: ChunkingConfig | None = None) -> list[Chunk]:
    """Split RawData into chunks with metadata.

    Args:
        data: The RawData object to chunk.
        config: Chunking configuration. Uses defaults if not provided.

    Returns:
        List of Chunk objects with inherited metadata.
    """
    if config is None:
        config = ChunkingConfig()

    # Extract text content
    if isinstance(data.content, str):
        text = data.content
    elif isinstance(data.content, bytes):
        text = data.content.decode("utf-8", errors="ignore")
    else:
        text = str(data.content)

    # Generate text chunks
    text_chunks = chunk_text(text, config)

    if not text_chunks:
        return []

    # Get source info
    source_id = data.source.source_id if data.source else "unknown"
    source_type = data.source.source_type if data.source else "unknown"

    # Build chunk objects
    chunks = []
    total_chunks = len(text_chunks)

    for idx, content in enumerate(text_chunks):
        chunk_id = f"{source_id}-chunk-{idx}"

        # Merge metadata
        chunk_metadata = {
            "source_id": source_id,
            "source_type": source_type,
            "chunk_index": idx,
            "total_chunks": total_chunks,
            "chunked_at": datetime.now().isoformat(),
            **data.metadata,
        }

        chunk = Chunk(
            id=chunk_id,
            content=content,
            index=idx,
            total_chunks=total_chunks,
            metadata=chunk_metadata,
        )
        chunks.append(chunk)

    return chunks


class HybridSearchMixin:
    """Mixin providing BM25-style keyword scoring for hybrid search.

    Combines vector similarity scores with keyword relevance to improve
    retrieval quality — especially for exact term matches that pure
    semantic search can miss.

    Usage:
        results = self.hybrid_rerank(results, query_text)
    """

    @staticmethod
    def bm25_score(
        query_terms: list[str],
        document: str,
        k1: float = 1.5,
        b: float = 0.75,
        avg_dl: float = 200.0,
    ) -> float:
        """Compute simplified BM25 score for a single document.

        Uses term frequency only (no corpus-level IDF) since we're
        re-ranking a small result set, not scoring the full corpus.

        Args:
            query_terms: Lowercased query tokens.
            document: Document text.
            k1: Term frequency saturation parameter.
            b: Length normalization parameter.
            avg_dl: Assumed average document length in tokens.

        Returns:
            BM25 relevance score (higher = more relevant).
        """
        doc_terms = document.lower().split()
        doc_len = len(doc_terms)
        score = 0.0
        for term in query_terms:
            tf = doc_terms.count(term.lower())
            if tf == 0:
                continue
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * doc_len / avg_dl)
            score += numerator / denominator
        return score

    @staticmethod
    def hybrid_rerank(
        items: list[dict[str, Any]],
        scores: list[float],
        query: str,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> tuple[list[dict[str, Any]], list[float]]:
        """Re-rank search results using weighted vector + keyword scores.

        Args:
            items: Search result items (must have ``"content"`` key).
            scores: Corresponding vector similarity scores.
            query: Original query text for keyword scoring.
            vector_weight: Weight for vector similarity (0-1).
            keyword_weight: Weight for keyword relevance (0-1).

        Returns:
            Tuple of (reranked_items, reranked_scores).
        """
        if not items:
            return items, scores

        query_terms = query.lower().split()

        # Compute keyword scores
        keyword_scores = [
            HybridSearchMixin.bm25_score(query_terms, item.get("content", "")) for item in items
        ]

        # Normalize keyword scores to 0-1
        max_kw = max(keyword_scores) if keyword_scores else 0
        if max_kw > 0:
            keyword_scores = [s / max_kw for s in keyword_scores]

        # Normalize vector scores to 0-1
        max_vs = max(scores) if scores else 0
        norm_vector = [s / max_vs for s in scores] if max_vs > 0 else scores

        # Compute hybrid scores
        hybrid = [
            vector_weight * vs + keyword_weight * ks
            for vs, ks in zip(norm_vector, keyword_scores, strict=False)
        ]

        # Sort by hybrid score descending
        ranked = sorted(
            zip(items, hybrid, strict=False),
            key=lambda x: x[1],
            reverse=True,
        )

        return [r[0] for r in ranked], [r[1] for r in ranked]


class EmbeddingMixin:
    """Mixin providing embedding generation capabilities with auto-detection.

    Auto-detects dimension from provider if not explicitly set.

    Attributes:
        _embedding_provider: EmbeddingProvider instance.
        _embedding_model: Model name for embedding.
        _dimension: Vector dimension (auto-detected if None).
    """

    _embedding_provider: Any | None = None
    _embedding_model: str | None = None
    _dimension: int | None = None
    _resolved_dimension: int | None = None

    def _get_embedding_provider(self) -> Any:
        """Get the embedding provider, resolving from config if not set.

        Returns:
            EmbeddingProvider instance.

        Raises:
            ValueError: If no embedding provider is available.
        """
        if self._embedding_provider:
            return self._embedding_provider

        # Try to resolve from config
        try:
            from openbench.intelligence.embeddings import resolve_embedding_provider

            provider = resolve_embedding_provider(model=self._embedding_model)
            self._embedding_provider = provider
            return provider
        except Exception:
            pass

        raise ValueError(
            "No embedding provider configured. "
            "Either pass embedding_provider to constructor or install openai package."
        )

    def _get_dimension(self) -> int:
        """Get embedding dimension, auto-detecting from provider if needed.

        Returns:
            Vector dimension.
        """
        # Return cached dimension
        if self._resolved_dimension is not None:
            return self._resolved_dimension

        # Use explicit dimension if set
        if self._dimension is not None:
            self._resolved_dimension = self._dimension
            return self._resolved_dimension

        # Try to get from provider
        try:
            provider = self._get_embedding_provider()
            if hasattr(provider, "get_dimension"):
                self._resolved_dimension = provider.get_dimension(self._embedding_model)
                return self._resolved_dimension
        except Exception:
            pass

        # Try to get from model registry
        if self._embedding_model:
            try:
                from openbench.core.config import get_embedding_dimension

                self._resolved_dimension = get_embedding_dimension(self._embedding_model)
                return self._resolved_dimension
            except Exception:
                pass

        # Default fallback
        self._resolved_dimension = 1536
        return self._resolved_dimension

    def _embed(self, text: str) -> list[float]:
        """Generate embedding vector for text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector as list of floats.
        """
        provider = self._get_embedding_provider()
        return provider.embed(text, model=self._embedding_model)

    def _embed_batch(self, texts: list[str], batch_size: int = 100) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.
            batch_size: Number of texts to embed per API call.

        Returns:
            List of embedding vectors.
        """
        provider = self._get_embedding_provider()

        if hasattr(provider, "embed_batch"):
            return provider.embed_batch(texts, model=self._embedding_model, batch_size=batch_size)

        # Fallback to individual calls
        embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_embeddings = [provider.embed(text, model=self._embedding_model) for text in batch]
            embeddings.extend(batch_embeddings)

        return embeddings
