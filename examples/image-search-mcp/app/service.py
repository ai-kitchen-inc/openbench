"""Application service layer for indexing and image similarity search."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image

from app.config import AppConfig
from app.dataset import Cifar10Store
from app.embeddings import DinoV3Embedder, embedding_checksum
from app.search import load_image_base64, load_image_path, load_image_url
from app.vector_index import VectorIndex

logger = logging.getLogger(__name__)


class ImageSearchService:
    """Coordinates CIFAR-10, DINOv3 embeddings, and ANN vector search."""

    def __init__(
        self,
        config: AppConfig,
        *,
        dataset: Cifar10Store | None = None,
        embedder: Any | None = None,
        vector_index: VectorIndex | None = None,
    ):
        self.config = config
        self.config.ensure_directories()
        self.dataset = dataset or Cifar10Store(config.data_path, config.preview_path)
        self.embedder = embedder or DinoV3Embedder(
            config.model_id,
            requested_device=config.requested_device,
            cache_dir=config.model_cache_path,
        )
        self.index = vector_index or VectorIndex(config.index_path, backend=config.vector_backend)

    def _preview_url(self, preview_path: str | None) -> str | None:
        if not preview_path or not self.config.preview_url_base:
            return None
        base = self.config.preview_url_base.rstrip("/")
        try:
            relative = Path(preview_path).resolve().relative_to(self.config.preview_path.resolve())
            suffix = relative.as_posix()
        except ValueError:
            suffix = Path(preview_path).name
        return f"{base}/{suffix}"

    def _load_query_image(
        self,
        *,
        image_path: str | None = None,
        image_base64: str | None = None,
        image_url: str | None = None,
        cifar10_test_index: int | None = None,
    ) -> tuple[Image.Image, dict[str, Any]]:
        provided = [
            image_path is not None,
            image_base64 is not None,
            image_url is not None,
            cifar10_test_index is not None,
        ]
        if sum(provided) != 1:
            raise ValueError(
                "Provide exactly one query input: image_path, image_base64, image_url, "
                "or cifar10_test_index."
            )
        if image_path is not None:
            return load_image_path(image_path), {"source": "image_path", "image_path": image_path}
        if image_base64 is not None:
            return load_image_base64(image_base64), {"source": "image_base64"}
        if image_url is not None:
            return (
                load_image_url(image_url, timeout_seconds=self.config.image_url_timeout_seconds),
                {"source": "image_url", "image_url": image_url},
            )
        assert cifar10_test_index is not None
        record = self.dataset.get_test(cifar10_test_index)
        return (
            record.image,
            {
                "source": "cifar10_test_index",
                "cifar10_test_index": cifar10_test_index,
                "class_id": record.class_id,
                "class_name": record.class_name,
            },
        )

    def search_similar_images(
        self,
        *,
        image_path: str | None = None,
        image_base64: str | None = None,
        image_url: str | None = None,
        cifar10_test_index: int | None = None,
        top_k: int | None = None,
        threshold: float | None = None,
    ) -> dict[str, Any]:
        """Search the persisted index for visually similar CIFAR-10 train images."""
        query_image, query_metadata = self._load_query_image(
            image_path=image_path,
            image_base64=image_base64,
            image_url=image_url,
            cifar10_test_index=cifar10_test_index,
        )
        requested_top_k = top_k or self.config.top_k_default
        if requested_top_k <= 0:
            raise ValueError("top_k must be positive")
        query_vector = self.embedder.embed_image(query_image)
        hits = self.index.search(query_vector, requested_top_k)
        results = []
        for rank, hit in enumerate(hits, start=1):
            if threshold is not None and hit.score < threshold:
                continue
            results.append(
                {
                    "rank": rank,
                    "image_id": hit.metadata.get("image_id"),
                    "similarity_score": hit.score,
                    "class_id": hit.metadata.get("class_id"),
                    "class_name": hit.metadata.get("class_name"),
                    "preview_path": hit.metadata.get("preview_path"),
                    "preview_url": self._preview_url(hit.metadata.get("preview_path")),
                    "metadata": hit.metadata,
                }
            )
        return {
            "query": query_metadata,
            "model_id": self.config.model_id,
            "backend": self.index.backend,
            "top_k": requested_top_k,
            "threshold": threshold,
            "count": len(results),
            "results": results,
        }

    def index_images(
        self,
        *,
        batch_size: int | None = None,
        max_items: int | None = None,
        write_previews: bool = True,
    ) -> dict[str, Any]:
        """Index missing CIFAR-10 train images in batches."""
        selected_batch_size = batch_size or self.config.batch_size
        if selected_batch_size <= 0:
            raise ValueError("batch_size must be positive")
        pending_records = []
        stats = {"seen": 0, "skipped_existing": 0, "indexed": 0, "failed": 0}

        def flush() -> None:
            if not pending_records:
                return
            images = [record.image for record in pending_records]
            vectors = self.embedder.embed_images(images)
            metadata = []
            for record, vector in zip(pending_records, vectors, strict=False):
                preview_path = self.dataset.save_preview(record) if write_previews else None
                metadata.append(
                    record.metadata(
                        preview_path=preview_path,
                        embedding_checksum=embedding_checksum(vector),
                    )
                )
            self.index.add(vectors, metadata)
            stats["indexed"] += len(pending_records)
            logger.info("indexed %s CIFAR-10 train images", stats["indexed"])
            pending_records.clear()

        for record in self.dataset.iter_train(max_items=max_items):
            stats["seen"] += 1
            if self.index.has_image(record.image_id):
                stats["skipped_existing"] += 1
                continue
            try:
                pending_records.append(record)
                if len(pending_records) >= selected_batch_size:
                    flush()
            except Exception:
                logger.exception("failed to queue image %s", record.image_id)
                stats["failed"] += 1
        flush()
        return {
            **stats,
            "backend": self.index.backend,
            "dimension": self.index.dimension,
            "active_count": self.index.count,
            "index_path": str(self.config.index_path),
        }

    def rebuild_index(
        self,
        *,
        batch_size: int | None = None,
        max_items: int | None = None,
        write_previews: bool = True,
    ) -> dict[str, Any]:
        """Clear and rebuild the CIFAR-10 train index."""
        self.index.clear()
        self.index.load()
        return self.index_images(
            batch_size=batch_size,
            max_items=max_items,
            write_previews=write_previews,
        )

    def list_index_stats(self) -> dict[str, Any]:
        """Return index health and persistence stats."""
        actual_device = getattr(self.embedder, "device", self.config.requested_device)
        return {
            "model_id": self.config.model_id,
            "requested_device": self.config.requested_device,
            "device": actual_device,
            "backend": self.index.backend,
            "dimension": self.index.dimension,
            "active_count": self.index.count,
            "metadata_count": len(self.index.metadata),
            "index_path": str(self.config.index_path),
            "data_path": str(self.config.data_path),
            "model_cache_path": str(self.config.model_cache_path),
            "preview_path": str(self.config.preview_path),
            "preview_url_base": self.config.preview_url_base,
            "healthy": self.index.count > 0 and self.index.dimension is not None,
        }

    def remove_image(self, image_id: str) -> dict[str, Any]:
        """Remove an indexed image by image_id."""
        if not image_id:
            raise ValueError("image_id is required")
        removed = self.index.remove(image_id)
        return {
            "image_id": image_id,
            "removed": removed,
            "active_count": self.index.count,
            "message": "removed" if removed else "image_id not found",
        }


@lru_cache(maxsize=1)
def get_service() -> ImageSearchService:
    """Return a process-wide service configured from the environment."""
    return ImageSearchService(AppConfig.from_env())
