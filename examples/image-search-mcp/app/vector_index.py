"""Persistent FAISS/HNSW vector index for normalized image embeddings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

BackendName = Literal["faiss", "hnswlib"]


@dataclass(frozen=True)
class SearchHit:
    """Nearest-neighbor result from the vector index."""

    metadata: dict
    score: float


class VectorIndex:
    """Cosine-similarity vector index with disk persistence."""

    def __init__(self, path: Path, backend: Literal["auto", "faiss", "hnswlib"] = "auto"):
        self.path = path
        self.requested_backend = backend
        self.backend: BackendName | None = None
        self.dimension: int | None = None
        self.metadata: list[dict] = []
        self.vectors = np.empty((0, 0), dtype=np.float32)
        self._index = None
        self.path.mkdir(parents=True, exist_ok=True)
        self.load()

    @property
    def manifest_path(self) -> Path:
        return self.path / "manifest.json"

    @property
    def metadata_path(self) -> Path:
        return self.path / "metadata.jsonl"

    @property
    def vectors_path(self) -> Path:
        return self.path / "vectors.npy"

    def _index_path(self, backend: BackendName | None = None) -> Path:
        selected = backend or self.backend or "faiss"
        return self.path / ("index.faiss" if selected == "faiss" else "index.hnsw")

    def _select_backend(self) -> BackendName:
        if self.requested_backend in {"auto", "faiss"}:
            try:
                import faiss  # noqa: F401

                return "faiss"
            except ImportError:
                if self.requested_backend == "faiss":
                    raise ImportError("faiss-cpu is required when VECTOR_BACKEND=faiss")
        try:
            import hnswlib  # noqa: F401

            return "hnswlib"
        except ImportError as exc:
            raise ImportError("Install faiss-cpu or hnswlib for vector search") from exc

    def load(self) -> None:
        """Load persisted vectors and metadata if available."""
        self.backend = self._select_backend()
        if self.metadata_path.exists():
            self.metadata = [
                json.loads(line)
                for line in self.metadata_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        if self.vectors_path.exists():
            self.vectors = np.load(self.vectors_path).astype(np.float32)
            self.dimension = int(self.vectors.shape[1]) if self.vectors.size else None
        if self.vectors.size:
            self._build_index()

    def save(self) -> None:
        """Persist manifest, metadata, vectors, and backend index."""
        self.path.mkdir(parents=True, exist_ok=True)
        np.save(self.vectors_path, self.vectors.astype(np.float32))
        with self.metadata_path.open("w", encoding="utf-8") as handle:
            for item in self.metadata:
                handle.write(json.dumps(item, sort_keys=True) + "\n")
        manifest = {
            "backend": self.backend,
            "dimension": self.dimension,
            "count": len(self.metadata),
            "active_count": self.count,
        }
        self.manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        if self._index is not None:
            if self.backend == "faiss":
                import faiss

                faiss.write_index(self._index, str(self._index_path("faiss")))
            else:
                self._index.save_index(str(self._index_path("hnswlib")))

    def _active_rows(self) -> tuple[np.ndarray, list[dict]]:
        active_indices = [
            index for index, item in enumerate(self.metadata) if not item.get("tombstoned", False)
        ]
        if not active_indices:
            return np.empty((0, self.dimension or 0), dtype=np.float32), []
        return self.vectors[active_indices].astype(np.float32), [self.metadata[i] for i in active_indices]

    def _build_index(self) -> None:
        active_vectors, _ = self._active_rows()
        if active_vectors.size == 0:
            self._index = None
            return
        self.dimension = int(active_vectors.shape[1])
        if self.backend == "faiss":
            import faiss

            index = faiss.IndexFlatIP(self.dimension)
            index.add(active_vectors)
            self._index = index
        else:
            import hnswlib

            index = hnswlib.Index(space="cosine", dim=self.dimension)
            index.init_index(max_elements=max(len(active_vectors), 1), ef_construction=200, M=16)
            index.add_items(active_vectors, np.arange(len(active_vectors)))
            index.set_ef(max(50, min(200, len(active_vectors))))
            self._index = index

    @property
    def count(self) -> int:
        """Return active vector count."""
        return sum(1 for item in self.metadata if not item.get("tombstoned", False))

    def has_image(self, image_id: str) -> bool:
        """Return True if an active image is already indexed."""
        return any(
            item.get("image_id") == image_id and not item.get("tombstoned", False)
            for item in self.metadata
        )

    def add(self, vectors: np.ndarray, metadata: list[dict]) -> None:
        """Add normalized vectors and metadata, then persist."""
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.ndim != 2:
            raise ValueError("vectors must be a 2D float32 array")
        if len(vectors) != len(metadata):
            raise ValueError("vectors and metadata lengths must match")
        if len(vectors) == 0:
            return
        if self.dimension is not None and vectors.shape[1] != self.dimension:
            raise ValueError(
                f"embedding dimension mismatch: expected {self.dimension}, got {vectors.shape[1]}"
            )
        if self.vectors.size == 0:
            self.vectors = vectors
        else:
            self.vectors = np.vstack([self.vectors, vectors])
        self.dimension = int(vectors.shape[1])
        self.metadata.extend(metadata)
        self._build_index()
        self.save()

    def search(self, query: np.ndarray, top_k: int) -> list[SearchHit]:
        """Return nearest active items by cosine similarity."""
        if self.count == 0 or self._index is None:
            raise ValueError("Index is empty. Run index_images or rebuild_index first.")
        query = np.asarray(query, dtype=np.float32).reshape(1, -1)
        if self.dimension is None or query.shape[1] != self.dimension:
            raise ValueError(
                f"query dimension mismatch: expected {self.dimension}, got {query.shape[1]}"
            )
        active_vectors, active_metadata = self._active_rows()
        k = min(max(int(top_k), 1), len(active_metadata))
        if self.backend == "faiss":
            scores, labels = self._index.search(query, k)
            pairs = zip(labels[0].tolist(), scores[0].tolist(), strict=False)
        else:
            labels, distances = self._index.knn_query(query, k=k)
            pairs = ((label, 1.0 - distance) for label, distance in zip(labels[0], distances[0], strict=False))
        hits = []
        for label, score in pairs:
            if label < 0:
                continue
            hits.append(SearchHit(metadata=active_metadata[int(label)], score=float(score)))
        return hits

    def remove(self, image_id: str) -> bool:
        """Remove an image from the active index and persist a rebuilt index."""
        keep_vectors = []
        keep_metadata = []
        removed = False
        for vector, item in zip(self.vectors, self.metadata, strict=False):
            if item.get("image_id") == image_id and not item.get("tombstoned", False):
                removed = True
                continue
            keep_vectors.append(vector)
            keep_metadata.append(item)
        if not removed:
            return False
        if keep_vectors:
            self.vectors = np.vstack(keep_vectors).astype(np.float32)
        else:
            self.vectors = np.empty((0, self.dimension or 0), dtype=np.float32)
        self.metadata = keep_metadata
        self._build_index()
        self.save()
        return True

    def clear(self) -> None:
        """Clear all persisted index state."""
        self.metadata = []
        self.vectors = np.empty((0, 0), dtype=np.float32)
        self.dimension = None
        self._index = None
        for file_name in ("manifest.json", "metadata.jsonl", "vectors.npy", "index.faiss", "index.hnsw"):
            path = self.path / file_name
            if path.exists():
                path.unlink()
