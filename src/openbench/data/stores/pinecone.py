"""Pinecone vector store implementation."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from openbench.core.abstractions import DataStore, Query, RawData, SearchResult
from openbench.data.stores.base import (
    ChunkingConfig,
    EmbeddingMixin,
    HybridSearchMixin,
    chunk_raw_data,
)
from openbench.data.stores.exceptions import (
    DimensionMismatchError,
    EmbeddingError,
    IndexNotFoundError,
    StoreConnectionError,
    StoreError,
)


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Sanitize metadata for Pinecone (only primitives allowed)."""
    result = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, str | int | float | bool) or (
            isinstance(value, list) and all(isinstance(i, str) for i in value)
        ):
            result[key] = value
        else:
            result[key] = json.dumps(value)
    return result


if TYPE_CHECKING:
    from pinecone import Index, Pinecone

    from openbench.core.abstractions import EmbeddingProvider
    from openbench.core.context import ProjectContext


class PineconeStore(DataStore, EmbeddingMixin, HybridSearchMixin):
    """Pinecone vector store for semantic search and retrieval.

    Implements the DataStore interface with Pinecone as the backend.
    Supports multi-tenant isolation via namespaces tied to ProjectContext.
    Auto-detects embedding dimension from provider if not specified.
    Optional hybrid search combines vector similarity with BM25 keyword scoring.

    Example:
        ```python
        from openbench.data.stores import PineconeStore
        from openbench.intelligence import OpenAIEmbeddingProvider

        # Initialize with auto-detected dimension
        store = PineconeStore(
            index_name="openbench",
            embedding_model="text-embedding-3-small",  # Auto-detects 1536 dim
        )

        # Or with explicit provider
        provider = OpenAIEmbeddingProvider(model="text-embedding-3-large")
        store = PineconeStore(
            index_name="openbench",
            embedding_provider=provider,  # Auto-detects 3072 dim
        )

        # Enable hybrid search (vector + keyword)
        store = PineconeStore(
            index_name="openbench",
            hybrid_search=True,
            vector_weight=0.7,  # 70% vector, 30% keyword
        )

        # Index data
        store.index(raw_data)

        # Search
        results = store.search(Query(text="sustainability"))
        ```
    """

    def __init__(
        self,
        index_name: str,
        *,
        api_key: str | None = None,
        project: ProjectContext | None = None,
        namespace: str | None = None,
        dimension: int | None = None,
        metric: str = "cosine",
        embedding_provider: EmbeddingProvider | None = None,
        embedding_model: str | None = None,
        chunking_config: ChunkingConfig | None = None,
        create_if_missing: bool = True,
        hybrid_search: bool = False,
        vector_weight: float = 0.7,
    ):
        """Initialize PineconeStore.

        Args:
            index_name: Name of the Pinecone index.
            api_key: Pinecone API key. Falls back to PINECONE_API_KEY env var.
            project: ProjectContext for namespace isolation.
            namespace: Explicit namespace override. If not provided, uses project.namespace.
            dimension: Vector dimension. If None, auto-detects from embedding provider/model.
            metric: Distance metric ('cosine', 'euclidean', 'dotproduct').
            embedding_provider: EmbeddingProvider for generating embeddings.
            embedding_model: Embedding model name for auto-detection.
            chunking_config: Configuration for text chunking.
            create_if_missing: Create index if it doesn't exist.
            hybrid_search: Enable hybrid search (vector + BM25 keyword scoring).
            vector_weight: Weight for vector similarity in hybrid search (0-1).
        """
        self._index_name = index_name
        self._api_key = api_key or os.getenv("PINECONE_API_KEY")
        self._project = project
        self._namespace_override = namespace
        self._dimension = dimension  # Can be None for auto-detection
        self._metric = metric
        self._embedding_provider = embedding_provider
        self._embedding_model = embedding_model
        self._chunking_config = chunking_config or ChunkingConfig()
        self._create_if_missing = create_if_missing
        self._hybrid_search = hybrid_search
        self._vector_weight = vector_weight

        # For EmbeddingMixin auto-detection
        self._resolved_dimension: int | None = None

        # Lazy initialization
        self._client: Pinecone | None = None
        self._index: Index | None = None

    @property
    def store_type(self) -> str:
        """Return store type identifier."""
        return "vector"

    @property
    def namespace(self) -> str:
        """Resolve namespace for vector isolation.

        Priority:
        1. Explicit namespace parameter
        2. project.namespace (if project provided)
        3. Active project namespace (from registry)
        4. Empty string (default/global)
        """
        if self._namespace_override:
            return self._namespace_override

        if self._project:
            return self._project.namespace

        # Try active project from registry
        try:
            from openbench.core.context import get_project_registry

            registry = get_project_registry()
            active = registry.get_active()
            if active:
                return active.namespace
        except Exception:
            pass

        return ""

    @property
    def pinecone_index(self) -> Index:
        """Get Pinecone index, initializing if needed."""
        if self._index is None:
            self._init_client()
            self._index = self._get_or_create_index()
        return self._index

    def _init_client(self) -> None:
        """Initialize Pinecone client."""
        if self._client is not None:
            return

        if not self._api_key:
            raise StoreConnectionError(
                "pinecone",
                "API key not provided. Set PINECONE_API_KEY environment variable "
                "or pass api_key to constructor.",
            )

        try:
            from pinecone import Pinecone

            self._client = Pinecone(api_key=self._api_key)
        except ImportError:
            raise StoreError(
                "pinecone-client not installed. Install with: pip install openbench[vector]"
            ) from None
        except Exception as e:
            raise StoreConnectionError("pinecone", str(e)) from e

    def _get_or_create_index(self) -> Index:
        """Get existing index or create if missing."""
        from pinecone import ServerlessSpec

        # Check if index exists
        existing_indexes = [idx.name for idx in self._client.list_indexes()]

        if self._index_name not in existing_indexes:
            if not self._create_if_missing:
                raise IndexNotFoundError(self._index_name)

            # Get dimension (auto-detect if not set)
            dimension = self._get_dimension()

            # Create new index
            self._client.create_index(
                name=self._index_name,
                dimension=dimension,
                metric=self._metric,
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )

            # Wait for index to be ready
            self._wait_for_index_ready()
        else:
            # Validate provider dimension matches existing index
            self._validate_index_dimension()

        return self._client.Index(self._index_name)

    def _validate_index_dimension(self) -> None:
        """Validate that embedding provider dimension matches existing index.

        Raises DimensionMismatchError with actionable guidance if they differ.
        """
        if not self._embedding_provider:
            return

        try:
            desc = self._client.describe_index(self._index_name)
            index_dim = int(desc.dimension)
        except Exception:
            return

        try:
            provider_dim = self._embedding_provider.get_dimension()
        except (ValueError, AttributeError):
            return

        if provider_dim != index_dim:
            provider_class = type(self._embedding_provider).__name__
            raise DimensionMismatchError(
                expected=index_dim,
                got=provider_dim,
                message=(
                    f"Embedding provider {provider_class} outputs {provider_dim}-dim vectors "
                    f"but index '{self._index_name}' has dimension {index_dim}. "
                    f"Fix: {provider_class}(dimension={index_dim})"
                ),
            )

    def _wait_for_index_ready(self, timeout: int = 60) -> None:
        """Wait for index to be ready for operations."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                desc = self._client.describe_index(self._index_name)
                if desc.status.ready:
                    return
            except Exception:
                pass
            time.sleep(1)

        raise StoreError(f"Index {self._index_name} not ready after {timeout}s")

    def _build_filter(self, filters: dict[str, Any]) -> dict[str, Any]:
        """Convert OpenBench query filters to Pinecone filter format.

        Args:
            filters: OpenBench filter dict.

        Returns:
            Pinecone-compatible filter dict.
        """
        if not filters:
            return {}

        pinecone_filter = {}

        for key, value in filters.items():
            # Handle operators
            if key.startswith("$"):
                # Already in operator format
                pinecone_filter[key] = value
            elif isinstance(value, dict):
                # Value is already operator dict
                pinecone_filter[key] = value
            else:
                # Simple equality
                pinecone_filter[key] = {"$eq": value}

        return pinecone_filter

    def _to_search_result(self, response: Any) -> SearchResult:
        """Convert Pinecone query response to SearchResult.

        Args:
            response: Pinecone QueryResponse.

        Returns:
            OpenBench SearchResult.
        """
        items = []
        scores = []

        for match in response.matches:
            item = {
                "id": match.id,
                "score": match.score,
                "metadata": match.metadata or {},
            }
            # Include content if available
            if match.metadata and "content" in match.metadata:
                item["content"] = match.metadata["content"]

            items.append(item)
            scores.append(match.score)

        return SearchResult(
            items=items,
            total=len(items),
            scores=scores,
            metadata={"namespace": self.namespace},
        )

    def index(self, data: RawData, **options) -> str:
        """Index RawData into Pinecone.

        Chunks the data, generates embeddings, and upserts to Pinecone.

        Args:
            data: RawData to index.
            **options:
                batch_size: Vectors per upsert batch (default: 100).
                skip_embedding: Use pre-computed vectors (default: False).

        Returns:
            Source ID of the indexed data.
        """
        batch_size = options.get("batch_size", 100)

        # Chunk the data
        chunks = chunk_raw_data(data, self._chunking_config)

        if not chunks:
            return data.source.source_id if data.source else "unknown"

        # Generate embeddings
        try:
            texts = [chunk.content for chunk in chunks]
            embeddings = self._embed_batch(texts, batch_size=batch_size)
        except Exception as e:
            raise EmbeddingError(message=str(e)) from e

        # Validate dimension
        expected_dim = self._get_dimension()
        if embeddings and len(embeddings[0]) != expected_dim:
            raise DimensionMismatchError(expected=expected_dim, got=len(embeddings[0]))

        # Build vectors for upsert
        vectors = []
        for chunk, embedding in zip(chunks, embeddings, strict=False):
            # Build metadata and sanitize for Pinecone
            raw_metadata = {
                "content": chunk.content[:8000],  # Limit content size
                "content_hash": chunk.content_hash,
                "project_id": self.namespace,
                "indexed_at": datetime.now().isoformat(),
                **chunk.metadata,
            }
            vector = {
                "id": f"{self.namespace}-{chunk.id}" if self.namespace else chunk.id,
                "values": embedding,
                "metadata": _sanitize_metadata(raw_metadata),
            }
            vectors.append(vector)

        # Upsert in batches
        self._upsert_batch(vectors, batch_size)

        source_id = data.source.source_id if data.source else "unknown"
        return source_id

    def _upsert_batch(self, vectors: list[dict], batch_size: int) -> int:
        """Upsert vectors in batches with retry logic.

        Args:
            vectors: List of vector dicts to upsert.
            batch_size: Number of vectors per batch.

        Returns:
            Total number of vectors upserted.
        """
        total = 0
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i : i + batch_size]
            self._upsert_with_retry(batch)
            total += len(batch)
        return total

    def _upsert_with_retry(
        self, vectors: list[dict], max_retries: int = 3, base_delay: float = 1.0
    ) -> None:
        """Upsert with exponential backoff retry.

        Args:
            vectors: Vectors to upsert.
            max_retries: Maximum retry attempts.
            base_delay: Base delay in seconds.
        """
        for attempt in range(max_retries + 1):
            try:
                self.pinecone_index.upsert(vectors=vectors, namespace=self.namespace)
                return
            except Exception as e:
                if attempt == max_retries:
                    raise StoreError(f"Failed to upsert after {max_retries} retries: {e}") from e

                # Check if rate limited
                if "429" in str(e) or "rate" in str(e).lower():
                    delay = base_delay * (2**attempt)
                    time.sleep(delay)
                else:
                    raise

    def search(self, query: Query) -> SearchResult:
        """Search the store for relevant items.

        Args:
            query: Query with text and/or filters.

        Returns:
            SearchResult with matched items and scores.
        """
        # Generate query embedding
        if query.vector:
            query_vector = query.vector
        elif query.text:
            try:
                query_vector = self._embed(query.text)
            except Exception as e:
                raise EmbeddingError(
                    text_length=len(query.text) if query.text else 0, message=str(e)
                ) from e
        else:
            raise StoreError("Query must have either text or vector")

        # Build filter
        pinecone_filter = self._build_filter(query.filters) if query.filters else None

        # Execute query
        response = self.pinecone_index.query(
            vector=query_vector,
            top_k=query.limit,
            namespace=self.namespace,
            filter=pinecone_filter,
            include_metadata=True,
        )

        result = self._to_search_result(response)

        # Apply hybrid reranking if enabled and we have a text query
        if self._hybrid_search and query.text and result.items:
            result.items, result.scores = self.hybrid_rerank(
                result.items,
                result.scores,
                query.text,
                vector_weight=self._vector_weight,
                keyword_weight=1 - self._vector_weight,
            )

        return result

    def get(self, item_id: str) -> dict[str, Any] | None:
        """Retrieve a specific item by ID.

        Args:
            item_id: ID of the item to retrieve.

        Returns:
            Item dict with id, values, and metadata, or None if not found.
        """
        # Prefix with namespace if not already
        full_id = item_id
        if self.namespace and not item_id.startswith(self.namespace):
            full_id = f"{self.namespace}-{item_id}"

        response = self.pinecone_index.fetch(ids=[full_id], namespace=self.namespace)

        if full_id in response.vectors:
            vector = response.vectors[full_id]
            return {
                "id": vector.id,
                "values": vector.values,
                "metadata": vector.metadata or {},
            }

        return None

    def delete(self, item_id: str) -> bool:
        """Delete an item from the store.

        Args:
            item_id: ID of the item to delete.

        Returns:
            True if deleted, False if not found.
        """
        # Prefix with namespace if not already
        full_id = item_id
        if self.namespace and not item_id.startswith(self.namespace):
            full_id = f"{self.namespace}-{item_id}"

        try:
            self.pinecone_index.delete(ids=[full_id], namespace=self.namespace)
            return True
        except Exception:
            return False

    def update(self, item_id: str, data: Any) -> bool:
        """Update an existing item's metadata.

        Args:
            item_id: ID of the item to update.
            data: New metadata to merge.

        Returns:
            True if updated, False if not found.
        """
        existing = self.get(item_id)
        if not existing:
            return False

        # Merge metadata
        new_metadata = {**existing.get("metadata", {})}
        if isinstance(data, dict):
            new_metadata.update(data)
        new_metadata["updated_at"] = datetime.now().isoformat()

        # Re-upsert with same vector and new metadata
        full_id = existing["id"]
        self.pinecone_index.upsert(
            vectors=[
                {
                    "id": full_id,
                    "values": existing["values"],
                    "metadata": new_metadata,
                }
            ],
            namespace=self.namespace,
        )

        return True

    def delete_by_source(self, source_id: str) -> int:
        """Delete all chunks from a specific source.

        Args:
            source_id: Source ID to delete chunks for.

        Returns:
            Number of items deleted (approximate).
        """
        # Use metadata filter to find matching vectors
        # Then delete by IDs

        try:
            # Delete by prefix
            self.pinecone_index.delete(
                filter={"source_id": {"$eq": source_id}},
                namespace=self.namespace,
            )
            return -1  # Pinecone doesn't return count
        except Exception:
            return 0

    def delete_namespace(self) -> bool:
        """Delete all vectors in the current namespace.

        Returns:
            True if successful.
        """
        if not self.namespace:
            raise StoreError("Cannot delete default namespace. Specify a namespace.")

        try:
            self.pinecone_index.delete(delete_all=True, namespace=self.namespace)
            return True
        except Exception:
            return False

    def describe_index(self) -> dict[str, Any]:
        """Get index statistics.

        Returns:
            Dict with index stats including vector count, dimension, etc.
        """
        stats = self.pinecone_index.describe_index_stats()

        return {
            "index_name": self._index_name,
            "dimension": stats.dimension,
            "total_vector_count": stats.total_vector_count,
            "namespaces": {
                ns: {"vector_count": data.vector_count} for ns, data in stats.namespaces.items()
            },
        }
