"""Application service layer for indexing and image similarity search."""

from __future__ import annotations

import logging
import os
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import Image

from app.config import AppConfig
from app.dataset import Cifar10CorpusSummary, Cifar10Store
from app.embeddings import DinoV3Embedder, embedding_checksum
from app.search import load_image_base64, load_image_path, load_image_url
from app.vector_index import VectorIndex

logger = logging.getLogger(__name__)


class Cifar10IndexNotReadyError(RuntimeError):
    """Raised when the persisted image index cannot be searched yet."""


class _IndexProgress:
    """Small stdout progress bar for local one-off indexing commands."""

    def __init__(self, total: int, *, enabled: bool | None = None):
        self.total = max(0, int(total))
        self.enabled = self._resolve_enabled(enabled)
        self._last_seen = -1
        self._step = max(1, self.total // 200) if self.total else 1

    @staticmethod
    def _resolve_enabled(enabled: bool | None) -> bool:
        if enabled is not None:
            return enabled
        raw = os.getenv("IMAGE_SEARCH_PROGRESS", "").strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        return sys.stdout.isatty()

    def update(self, *, seen: int, indexed: int, skipped: int, failed: int, force: bool = False) -> None:
        if not self.enabled:
            return
        if not force and seen < self.total and seen - self._last_seen < self._step:
            return
        self._last_seen = seen
        total = self.total or seen or 1
        fraction = min(1.0, seen / total)
        width = 30
        filled = min(width, round(width * fraction))
        bar = "#" * filled + "-" * (width - filled)
        percent = fraction * 100
        sys.stdout.write(
            "\r"
            f"Indexing CIFAR-10 [{bar}] {percent:6.2f}% "
            f"{seen}/{self.total or '?'} seen "
            f"indexed={indexed} skipped={skipped} failed={failed}"
        )
        sys.stdout.flush()

    def finish(self, *, seen: int, indexed: int, skipped: int, failed: int) -> None:
        self.update(
            seen=seen,
            indexed=indexed,
            skipped=skipped,
            failed=failed,
            force=True,
        )
        if self.enabled:
            sys.stdout.write("\n")
            sys.stdout.flush()


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
        normalized_path = preview_path.replace("\\", "/")
        try:
            relative = Path(preview_path).resolve().relative_to(self.config.preview_path.resolve())
            suffix = relative.as_posix()
        except ValueError:
            marker = "/previews/"
            if marker in normalized_path:
                suffix = normalized_path.rsplit(marker, 1)[1]
            elif normalized_path.startswith("previews/"):
                suffix = normalized_path.removeprefix("previews/")
            else:
                suffix = Path(normalized_path).name
        suffix = suffix.lstrip("/")
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

    def _validate_top_k(self, top_k: int | None) -> tuple[int, int]:
        try:
            requested = int(top_k or self.config.top_k_default)
        except (TypeError, ValueError) as exc:
            raise ValueError("top_k must be an integer") from exc
        if requested <= 0:
            raise ValueError("top_k must be positive")
        return requested, min(requested, self.config.top_k_max)

    def _expected_summary(self) -> Cifar10CorpusSummary:
        expected_summary = getattr(self.dataset, "expected_summary", None)
        if callable(expected_summary):
            return expected_summary()
        return Cifar10CorpusSummary.expected()

    def _dataset_summary(self, *, write_manifest: bool = True) -> Cifar10CorpusSummary:
        summarize = getattr(self.dataset, "summarize", None)
        if callable(summarize):
            return summarize(write_manifest=write_manifest)
        return self._expected_summary()

    def _index_corpus_status(self) -> dict[str, Any]:
        expected = self._expected_summary()
        active_metadata = [
            item for item in self.index.metadata if not item.get("tombstoned", False)
        ]
        split_counts = Counter(str(item.get("cifar_split") or "") for item in active_metadata)
        class_counts = Counter(str(item.get("class_name") or "") for item in active_metadata)
        train_count = int(split_counts.get("train", 0))
        test_count = int(split_counts.get("test", 0))
        active_count = len(active_metadata)
        expected_class_counts = expected.class_counts
        complete = (
            active_count == expected.total_count
            and train_count == expected.train_count
            and test_count == expected.test_count
            and all(
                int(class_counts.get(class_name, 0)) == int(expected_class_counts.get(class_name, 0))
                for class_name in expected.class_names
            )
        )
        searchable = (
            active_count > 0
            and self.index.dimension is not None
            and self.index.backend is not None
        )
        warning = None
        if searchable and not complete:
            warning = (
                "Searching a partial CIFAR-10 index. Full 60,000-image indexing is "
                "recommended for best coverage."
            )
        elif not searchable:
            warning = "CIFAR-10 image index is empty or not initialized."
        return {
            "expected_count": expected.total_count,
            "expected_train_count": expected.train_count,
            "expected_test_count": expected.test_count,
            "expected_class_count": len(expected.class_names),
            "expected_per_class_total": (
                next(iter(expected_class_counts.values())) if expected_class_counts else None
            ),
            "active_count": active_count,
            "metadata_count": len(self.index.metadata),
            "train_count": train_count,
            "test_count": test_count,
            "class_counts": {
                class_name: int(class_counts.get(class_name, 0))
                for class_name in expected.class_names
            },
            "extra_class_counts": {
                class_name: int(count)
                for class_name, count in class_counts.items()
                if class_name and class_name not in set(expected.class_names)
            },
            "complete": complete,
            "partial": searchable and not complete,
            "searchable": searchable,
            "healthy": searchable,
            "warning": warning,
        }

    def _require_searchable_index(self) -> dict[str, Any]:
        status = self._index_corpus_status()
        if not status["searchable"]:
            raise Cifar10IndexNotReadyError(
                "CIFAR-10 image index is empty or not initialized: "
                f"active_count={status['active_count']}, "
                f"dimension={self.index.dimension}. "
                "Run image_search.index_images or image_search.rebuild_index first."
            )
        return status

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
        """Search the persisted index for visually similar CIFAR-10 images."""
        query_image, query_metadata = self._load_query_image(
            image_path=image_path,
            image_base64=image_base64,
            image_url=image_url,
            cifar10_test_index=cifar10_test_index,
        )
        corpus_status = self._require_searchable_index()
        requested_top_k, selected_top_k = self._validate_top_k(top_k)
        query_vector = self.embedder.embed_image(query_image)
        hits = self.index.search(query_vector, selected_top_k)
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
                    "cifar_split": hit.metadata.get("cifar_split"),
                    "original_dataset_index": hit.metadata.get("original_dataset_index"),
                    "preview_path": hit.metadata.get("preview_path"),
                    "preview_url": self._preview_url(hit.metadata.get("preview_path")),
                    "metadata": hit.metadata,
                }
            )
        return {
            "query": query_metadata,
            "model_id": self.config.model_id,
            "backend": self.index.backend,
            "top_k": selected_top_k,
            "requested_top_k": requested_top_k,
            "max_top_k": self.config.top_k_max,
            "threshold": threshold,
            "count": len(results),
            "corpus": corpus_status,
            "results": results,
        }

    def index_images(
        self,
        *,
        batch_size: int | None = None,
        max_items: int | None = None,
        write_previews: bool = True,
        show_progress: bool | None = None,
    ) -> dict[str, Any]:
        """Index missing CIFAR-10 images in batches."""
        selected_batch_size = batch_size or self.config.batch_size
        if selected_batch_size <= 0:
            raise ValueError("batch_size must be positive")
        expected_summary = self._expected_summary()
        dataset_summary = self._dataset_summary(write_manifest=max_items is None)
        dataset_matches_expected = (
            dataset_summary.train_count == expected_summary.train_count
            and dataset_summary.test_count == expected_summary.test_count
            and dataset_summary.total_count == expected_summary.total_count
            and all(
                dataset_summary.class_counts.get(class_name)
                == expected_summary.class_counts.get(class_name)
                for class_name in expected_summary.class_names
            )
        )
        if max_items is None and not dataset_matches_expected:
            raise RuntimeError(
                "Loaded CIFAR-10 dataset is incomplete: "
                f"train_count={dataset_summary.train_count}, "
                f"test_count={dataset_summary.test_count}, "
                f"total_count={dataset_summary.total_count}. "
                f"Expected {expected_summary.total_count} CIFAR-10 images."
            )
        logger.info(
            "CIFAR-10 corpus ready: total=%s train=%s test=%s classes=%s",
            dataset_summary.total_count,
            dataset_summary.train_count,
            dataset_summary.test_count,
            len(dataset_summary.class_names),
        )
        pending_records = []
        stats = {"seen": 0, "skipped_existing": 0, "indexed": 0, "failed": 0}
        progress_total = (
            min(max_items, dataset_summary.total_count)
            if max_items is not None
            else dataset_summary.total_count
        )
        progress = _IndexProgress(progress_total, enabled=show_progress)

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
            logger.info("indexed %s CIFAR-10 images", stats["indexed"])
            pending_records.clear()
            progress.update(
                seen=stats["seen"],
                indexed=stats["indexed"],
                skipped=stats["skipped_existing"],
                failed=stats["failed"],
            )

        for record in self.dataset.iter_all(max_items=max_items):
            stats["seen"] += 1
            if self.index.has_image(record.image_id):
                stats["skipped_existing"] += 1
                progress.update(
                    seen=stats["seen"],
                    indexed=stats["indexed"],
                    skipped=stats["skipped_existing"],
                    failed=stats["failed"],
                )
                continue
            try:
                pending_records.append(record)
                if len(pending_records) >= selected_batch_size:
                    flush()
            except Exception:
                logger.exception("failed to queue image %s", record.image_id)
                stats["failed"] += 1
                progress.update(
                    seen=stats["seen"],
                    indexed=stats["indexed"],
                    skipped=stats["skipped_existing"],
                    failed=stats["failed"],
                )
        flush()
        progress.finish(
            seen=stats["seen"],
            indexed=stats["indexed"],
            skipped=stats["skipped_existing"],
            failed=stats["failed"],
        )
        corpus_status = self._index_corpus_status()
        logger.info(
            "CIFAR-10 index status: active=%s expected=%s complete=%s",
            corpus_status["active_count"],
            corpus_status["expected_count"],
            corpus_status["complete"],
        )
        return {
            **stats,
            "backend": self.index.backend,
            "dimension": self.index.dimension,
            "active_count": self.index.count,
            "index_path": str(self.config.index_path),
            "dataset_manifest_path": dataset_summary.manifest_path,
            "dataset": dataset_summary.to_dict(),
            **corpus_status,
        }

    def rebuild_index(
        self,
        *,
        batch_size: int | None = None,
        max_items: int | None = None,
        write_previews: bool = True,
        show_progress: bool | None = None,
    ) -> dict[str, Any]:
        """Clear and rebuild the CIFAR-10 image index."""
        self.index.clear()
        self.index.load()
        return self.index_images(
            batch_size=batch_size,
            max_items=max_items,
            write_previews=write_previews,
            show_progress=show_progress,
        )

    def list_index_stats(self) -> dict[str, Any]:
        """Return index health and persistence stats."""
        actual_device = getattr(self.embedder, "device", self.config.requested_device)
        corpus_status = self._index_corpus_status()
        index_manifest_path = getattr(self.index, "manifest_path", None)
        dataset_manifest_path = getattr(self.dataset, "manifest_path", None)
        return {
            "model_id": self.config.model_id,
            "requested_device": self.config.requested_device,
            "device": actual_device,
            "backend": self.index.backend,
            "dimension": self.index.dimension,
            "active_count": self.index.count,
            "metadata_count": len(self.index.metadata),
            "index_path": str(self.config.index_path),
            "index_manifest_path": str(index_manifest_path) if index_manifest_path else None,
            "dataset_manifest_path": str(dataset_manifest_path) if dataset_manifest_path else None,
            "data_path": str(self.config.data_path),
            "model_cache_path": str(self.config.model_cache_path),
            "preview_path": str(self.config.preview_path),
            "preview_url_base": self.config.preview_url_base,
            **corpus_status,
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
