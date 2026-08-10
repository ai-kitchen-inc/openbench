"""Pinecone backend for the document chunk index.

Implements :class:`DocumentIndexBackend` on top of a Pinecone serverless
index so :class:`DocumentIndexStore` can run without Postgres. Chunk ids
are deterministic (``{source_id}-chunk-{idx}``), which lets id-prefix
listing and direct fetches stand in for the SQL queries the other
backends use:

* ``read_range`` / ``get_chunk`` — ``fetch`` by constructed ids.
* ``existing_hashes`` / ``headings`` / ``delete_*`` — ``list_paginated``
  with the source's id prefix.
* ``keyword_search`` — no server-side full-text search exists; returns
  nothing. The facade's hybrid rerank still keyword-scores the vector
  candidates, so exact-term signal survives within the candidate set.

The full chunk text lives in vector metadata (chunks are ~1000 chars,
well under Pinecone's 40KB metadata limit), so reads never need a second
store.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from openbench.core.constants import (
    DEFAULT_EMBED_BATCH_SIZE,
    DEFAULT_INDEX_READY_TIMEOUT_S,
    DEFAULT_MAX_RETRIES,
)
from openbench.data.stores.document_index import ChunkRow, DocumentIndexBackend
from openbench.data.stores.exceptions import StoreConnectionError, StoreError
from openbench.data.stores.pinecone import _sanitize_metadata

logger = logging.getLogger(__name__)

DEFAULT_PINECONE_DOC_INDEX = "openbench-source-chunks"

#: Pinecone caps ``fetch`` at 100 ids per call on serverless indexes.
_FETCH_BATCH = 100

#: Defensive cap for chunk text stored in metadata. Chunks are ~1000
#: chars by default; the cap only matters for pathological configs and
#: keeps the record under Pinecone's 40KB metadata limit.
_MAX_CONTENT_CHARS = 35_000


class PineconeDocumentBackend(DocumentIndexBackend):
    """Document index backend storing chunks in a Pinecone index.

    Requires a serverless index (id-prefix listing). The whole chunk row
    round-trips through vector metadata; scores come back as cosine
    similarity, matching what the SQL backends report.

    Example:
        >>> backend = PineconeDocumentBackend(index_name="my-chunks")
        >>> store = DocumentIndexStore(backend=backend, dimension=1536)
    """

    dialect = "pinecone"

    #: Bounded wait before retrying an empty ``read_range`` from index 0
    #: — Pinecone reads are eventually consistent, and the store summarizes
    #: a source immediately after indexing it. Tests set this to 0.
    _read_retry_delay = 0.25

    def __init__(
        self,
        index_name: str = DEFAULT_PINECONE_DOC_INDEX,
        *,
        api_key: str | None = None,
        namespace: str = "",
        cloud: str | None = None,
        region: str | None = None,
        index: Any | None = None,
    ) -> None:
        """Initialize the backend.

        Args:
            index_name: Pinecone index name.
            api_key: Pinecone API key. Falls back to ``PINECONE_API_KEY``.
            namespace: Namespace for every operation. Empty = default.
            cloud: Serverless cloud for index creation. Falls back to
                ``PINECONE_CLOUD``, then ``aws``.
            region: Serverless region for index creation. Falls back to
                ``PINECONE_REGION``, then ``us-east-1``.
            index: Pre-built index client (test seam, mirrors
                ``PgVectorBackend(conn=...)``). When given, no Pinecone
                client is created and ``ensure_schema`` is a no-op.
        """
        self.index_name = index_name
        self._api_key = api_key or os.getenv("PINECONE_API_KEY")
        self.namespace = namespace
        self._cloud = cloud or os.getenv("PINECONE_CLOUD") or "aws"
        self._region = region or os.getenv("PINECONE_REGION") or "us-east-1"
        self._index = index
        self._client: Any = None
        self._dimension: int | None = None

    # --- setup ------------------------------------------------------------

    def ensure_schema(self, dimension: int) -> None:
        self._dimension = dimension
        if self._index is not None:
            return
        if not self._api_key:
            raise StoreConnectionError(
                "pinecone",
                "API key not provided. Set PINECONE_API_KEY environment variable "
                "or pass api_key to constructor.",
            )
        try:
            from pinecone import Pinecone, ServerlessSpec
        except ImportError:
            raise StoreError(
                "The pinecone package is not installed. "
                "Install with: pip install openbench[vector]"
            ) from None

        client = Pinecone(api_key=self._api_key)
        existing = {idx.name for idx in client.list_indexes()}
        if self.index_name not in existing:
            client.create_index(
                name=self.index_name,
                dimension=dimension,
                metric="cosine",
                spec=ServerlessSpec(cloud=self._cloud, region=self._region),
            )
            self._wait_for_ready(client)
        else:
            desc = client.describe_index(self.index_name)
            index_dim = int(getattr(desc, "dimension", 0) or 0)
            if index_dim and index_dim != dimension:
                raise StoreError(
                    f"Pinecone index {self.index_name!r} has dimension {index_dim} "
                    f"but the document index expects {dimension}. Point "
                    "PINECONE_DOC_INDEX at a matching index or recreate it."
                )
        self._client = client
        self._index = client.Index(self.index_name)

    def _wait_for_ready(self, client: Any, timeout: int = DEFAULT_INDEX_READY_TIMEOUT_S) -> None:
        start = time.time()
        while time.time() - start < timeout:
            try:
                desc = client.describe_index(self.index_name)
                if desc.status.ready:
                    return
            except Exception:
                pass
            time.sleep(1)
        raise StoreError(f"Index {self.index_name} not ready after {timeout}s")

    def _require_index(self) -> Any:
        if self._index is None:
            raise StoreError(
                "PineconeDocumentBackend is not initialized; ensure_schema() must run first"
            )
        return self._index

    # --- row <-> metadata -------------------------------------------------

    def _row_to_metadata(self, row: ChunkRow) -> dict[str, Any]:
        metadata = _sanitize_metadata(dict(row.metadata))
        metadata.update(
            {
                "source_id": row.source_id,
                "session_id": row.session_id,
                "owner": row.owner,
                "chunk_index": row.chunk_index,
                "total_chunks": row.total_chunks,
                "content": row.content[:_MAX_CONTENT_CHARS],
                "content_hash": row.content_hash,
            }
        )
        if row.heading:
            metadata["heading"] = row.heading
        if row.page is not None:
            metadata["page"] = row.page
        if row.sheet:
            metadata["sheet"] = row.sheet
        return metadata

    @staticmethod
    def _metadata_to_row(chunk_id: str, metadata: dict[str, Any]) -> ChunkRow:
        # Pinecone returns every number as float; coerce the indexes back.
        meta = dict(metadata or {})
        heading = meta.pop("heading", None)
        page = meta.pop("page", None)
        sheet = meta.pop("sheet", None)
        return ChunkRow(
            chunk_id=chunk_id,
            source_id=str(meta.pop("source_id", "")),
            session_id=str(meta.pop("session_id", "")),
            owner=str(meta.pop("owner", "")),
            chunk_index=int(meta.pop("chunk_index", 0)),
            total_chunks=int(meta.pop("total_chunks", 0)),
            content=str(meta.pop("content", "")),
            content_hash=str(meta.pop("content_hash", "")),
            heading=str(heading) if heading else None,
            page=int(page) if page is not None else None,
            sheet=str(sheet) if sheet else None,
            metadata=meta,
        )

    # --- filters ----------------------------------------------------------

    @staticmethod
    def _build_filter(filters: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
        """Translate the supported filter keys to a Pinecone filter.

        Returns ``(filter, match_nothing)``. An explicit empty
        ``source_ids`` list must match nothing, not everything — it is
        the authorization boundary (parity with the SQL ``1 = 0``
        clause in ``_filter_clauses``).
        """
        clauses: list[dict[str, Any]] = []

        source_ids = filters.get("source_ids")
        if isinstance(source_ids, (list, tuple, set)):
            values = [str(value) for value in source_ids]
            if not values:
                return None, True
            clauses.append({"source_id": {"$in": values}})
        elif filters.get("source_id"):
            clauses.append({"source_id": {"$eq": str(filters["source_id"])}})

        if filters.get("session_id"):
            clauses.append({"session_id": {"$eq": str(filters["session_id"])}})

        owner = filters.get("owner")
        if owner is not None:
            clauses.append({"owner": {"$eq": str(owner)}})

        if not clauses:
            return None, False
        if len(clauses) == 1:
            return clauses[0], False
        return {"$and": clauses}, False

    # --- id helpers -------------------------------------------------------

    @staticmethod
    def _chunk_prefix(source_id: str) -> str:
        return f"{source_id}-chunk-"

    @staticmethod
    def _index_from_id(chunk_id: str, source_id: str) -> int | None:
        suffix = chunk_id[len(f"{source_id}-chunk-") :]
        try:
            return int(suffix)
        except ValueError:
            return None

    def _list_ids(self, prefix: str) -> list[str]:
        """List every vector id with the given prefix. Raises on failure.

        Requires a serverless index; callers degrade explicitly when
        listing is unsupported instead of guessing here.
        """
        index = self._require_index()
        ids: list[str] = []
        token: str | None = None
        while True:
            page = index.list_paginated(
                prefix=prefix, namespace=self.namespace, pagination_token=token
            )
            ids.extend(str(vector.id) for vector in getattr(page, "vectors", None) or [])
            pagination = getattr(page, "pagination", None)
            token = getattr(pagination, "next", None) if pagination else None
            if not token:
                return ids

    def _fetch_metadata(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch metadata for the given ids, in batches. Missing ids are absent."""
        index = self._require_index()
        result: dict[str, dict[str, Any]] = {}
        for start in range(0, len(ids), _FETCH_BATCH):
            response = index.fetch(ids=ids[start : start + _FETCH_BATCH], namespace=self.namespace)
            for vector_id, vector in (getattr(response, "vectors", None) or {}).items():
                result[str(vector_id)] = dict(getattr(vector, "metadata", None) or {})
        return result

    # --- DocumentIndexBackend ---------------------------------------------

    def upsert(self, rows: list[ChunkRow], vectors: list[list[float]]) -> int:
        if not rows:
            return 0
        payload = [
            {"id": row.chunk_id, "values": list(vector), "metadata": self._row_to_metadata(row)}
            for row, vector in zip(rows, vectors, strict=True)
        ]
        for start in range(0, len(payload), DEFAULT_EMBED_BATCH_SIZE):
            self._upsert_with_retry(payload[start : start + DEFAULT_EMBED_BATCH_SIZE])
        return len(rows)

    def _upsert_with_retry(
        self, vectors: list[dict], max_retries: int = DEFAULT_MAX_RETRIES, base_delay: float = 1.0
    ) -> None:
        index = self._require_index()
        for attempt in range(max_retries + 1):
            try:
                index.upsert(vectors=vectors, namespace=self.namespace)
                return
            except Exception as exc:
                if attempt == max_retries:
                    raise StoreError(
                        f"Failed to upsert after {max_retries} retries: {exc}"
                    ) from exc
                if "429" in str(exc) or "rate" in str(exc).lower():
                    time.sleep(base_delay * (2**attempt))
                else:
                    raise

    def existing_hashes(self, source_id: str) -> dict[int, str]:
        try:
            ids = self._list_ids(self._chunk_prefix(source_id))
        except Exception as exc:
            # Listing needs a serverless index. Without it re-indexing
            # re-embeds every chunk — wasteful but still correct.
            logger.warning("Pinecone id listing failed (%s); skipping hash check", exc)
            return {}
        hashes: dict[int, str] = {}
        for chunk_id, metadata in self._fetch_metadata(ids).items():
            index = self._index_from_id(chunk_id, source_id)
            if index is not None and metadata.get("content_hash"):
                hashes[index] = str(metadata["content_hash"])
        return hashes

    def delete_source(self, source_id: str) -> int:
        index = self._require_index()
        try:
            ids = self._list_ids(self._chunk_prefix(source_id))
        except Exception as exc:
            logger.warning(
                "Pinecone id listing failed (%s); falling back to metadata-filter delete", exc
            )
            # Metadata-filter delete works where listing does not, but
            # reports no count.
            index.delete(filter={"source_id": {"$eq": source_id}}, namespace=self.namespace)
            return -1
        if ids:
            index.delete(ids=ids, namespace=self.namespace)
        return len(ids)

    def delete_chunk(self, chunk_id: str) -> bool:
        index = self._require_index()
        if chunk_id not in self._fetch_metadata([chunk_id]):
            return False
        index.delete(ids=[chunk_id], namespace=self.namespace)
        return True

    def delete_chunks_from(self, source_id: str, first_index: int) -> int:
        index = self._require_index()
        try:
            ids = self._list_ids(self._chunk_prefix(source_id))
        except Exception as exc:
            logger.warning("Pinecone id listing failed (%s); orphan chunks not trimmed", exc)
            return 0
        targets = [
            chunk_id
            for chunk_id in ids
            if (parsed := self._index_from_id(chunk_id, source_id)) is not None
            and parsed >= first_index
        ]
        if targets:
            index.delete(ids=targets, namespace=self.namespace)
        return len(targets)

    def vector_search(
        self, vector: list[float], *, filters: dict[str, Any], limit: int
    ) -> list[tuple[ChunkRow, float]]:
        pinecone_filter, match_nothing = self._build_filter(filters)
        if match_nothing:
            return []
        index = self._require_index()
        response = index.query(
            vector=list(vector),
            top_k=limit,
            namespace=self.namespace,
            filter=pinecone_filter,
            include_metadata=True,
        )
        results: list[tuple[ChunkRow, float]] = []
        for match in getattr(response, "matches", None) or []:
            metadata = dict(getattr(match, "metadata", None) or {})
            results.append(
                (self._metadata_to_row(str(match.id), metadata), float(match.score or 0.0))
            )
        return results

    def keyword_search(
        self, text: str, *, filters: dict[str, Any], limit: int
    ) -> list[tuple[ChunkRow, float]]:
        """Pinecone has no server-side full-text search; returns nothing.

        The facade's hybrid rerank still applies BM25 keyword scoring to
        the vector candidates, so exact-term matches within the top
        candidates keep their edge.
        """
        return []

    def get_chunk(self, chunk_id: str) -> ChunkRow | None:
        metadata = self._fetch_metadata([chunk_id]).get(chunk_id)
        if metadata is None:
            return None
        return self._metadata_to_row(chunk_id, metadata)

    def read_range(self, source_id: str, start: int, end: int) -> list[ChunkRow]:
        ids = [f"{source_id}-chunk-{idx}" for idx in range(max(0, start), max(0, end))]
        if not ids:
            return []
        found = self._fetch_metadata(ids)
        if not found and start == 0 and self._read_retry_delay > 0:
            # Reads are eventually consistent and the store summarizes a
            # source right after indexing it; one bounded retry bridges
            # the gap without hiding a genuinely missing source.
            time.sleep(self._read_retry_delay)
            found = self._fetch_metadata(ids)
        rows = [self._metadata_to_row(chunk_id, metadata) for chunk_id, metadata in found.items()]
        rows.sort(key=lambda row: row.chunk_index)
        return rows

    def headings(self, source_id: str) -> list[ChunkRow]:
        try:
            ids = self._list_ids(self._chunk_prefix(source_id))
        except Exception as exc:
            logger.warning("Pinecone id listing failed (%s); outline unavailable", exc)
            return []
        rows = [
            self._metadata_to_row(chunk_id, metadata)
            for chunk_id, metadata in self._fetch_metadata(ids).items()
            if metadata.get("heading")
        ]
        rows.sort(key=lambda row: row.chunk_index)
        return rows

    def stats(self, *, filters: dict[str, Any]) -> dict[str, Any]:
        scoped: list[str] = []
        source_ids = filters.get("source_ids")
        if isinstance(source_ids, (list, tuple, set)):
            scoped = [str(value) for value in source_ids]
        elif filters.get("source_id"):
            scoped = [str(filters["source_id"])]

        if scoped:
            chunks = 0
            sources = 0
            for source_id in scoped:
                try:
                    count = len(self._list_ids(self._chunk_prefix(source_id)))
                except Exception:
                    count = 0
                chunks += count
                sources += 1 if count else 0
            return {"backend": self.dialect, "chunks": chunks, "sources": sources}

        index = self._require_index()
        try:
            description = index.describe_index_stats()
        except Exception as exc:
            logger.warning("describe_index_stats failed (%s)", exc)
            return {"backend": self.dialect, "chunks": 0, "sources": -1}
        namespaces = getattr(description, "namespaces", None) or {}
        summary = namespaces.get(self.namespace or "")
        if summary is not None:
            chunks = int(getattr(summary, "vector_count", 0) or 0)
        elif not self.namespace:
            chunks = int(getattr(description, "total_vector_count", 0) or 0)
        else:
            chunks = 0
        # Distinct-source counting would need a full scan; -1 marks the
        # value as unavailable rather than pretending it is zero.
        return {"backend": self.dialect, "chunks": chunks, "sources": -1}


__all__ = ["DEFAULT_PINECONE_DOC_INDEX", "PineconeDocumentBackend"]
