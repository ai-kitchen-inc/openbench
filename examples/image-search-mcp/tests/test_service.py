from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pytest
from app.config import AppConfig
from app.dataset import (
    CIFAR10_CLASS_COUNT,
    CIFAR10_PER_CLASS_TOTAL,
    CIFAR10_TEST_COUNT,
    CIFAR10_TOTAL_COUNT,
    CIFAR10_TRAIN_COUNT,
    Cifar10CorpusSummary,
    CifarImageRecord,
)
from app.embeddings import normalize_vectors
from app.service import ImageSearchService
from PIL import Image

if TYPE_CHECKING:
    from pathlib import Path


class FakeDataset:
    def __init__(
        self,
        preview_root: Path,
        *,
        expected_summary: Cifar10CorpusSummary | None = None,
    ):
        self.preview_root = preview_root
        self.records = [
            CifarImageRecord(
                image_id="cifar10-train-00000",
                split="train",
                class_id=0,
                class_name="airplane",
                original_dataset_index=0,
                image=Image.new("RGB", (4, 4), color=(255, 0, 0)),
            ),
            CifarImageRecord(
                image_id="cifar10-train-00001",
                split="train",
                class_id=1,
                class_name="automobile",
                original_dataset_index=1,
                image=Image.new("RGB", (4, 4), color=(0, 255, 0)),
            ),
        ]
        self.test_records = [
            CifarImageRecord(
                image_id="cifar10-test-00000",
                split="test",
                class_id=1,
                class_name="automobile",
                original_dataset_index=0,
                image=Image.new("RGB", (4, 4), color=(0, 0, 255)),
            )
        ]
        self._expected_summary = expected_summary

    def iter_train(self, max_items=None):
        yield from self.records[:max_items]

    def iter_all(self, max_items=None):
        records = [*self.records, *self.test_records]
        yield from records[:max_items]

    def get_test(self, index):
        return CifarImageRecord(
            image_id=f"cifar10-test-{index:05d}",
            split="test",
            class_id=0,
            class_name="airplane",
            original_dataset_index=index,
            image=Image.new("RGB", (4, 4), color=(255, 0, 0)),
        )

    def save_preview(self, record):
        self.preview_root.mkdir(parents=True, exist_ok=True)
        path = self.preview_root / f"{record.image_id}.png"
        record.image.save(path)
        return str(path)

    @property
    def manifest_path(self):
        return self.preview_root.parent / "cifar10" / "openbench_cifar10_manifest.json"

    def expected_summary(self):
        if self._expected_summary is not None:
            return self._expected_summary
        return self.summarize(write_manifest=False)

    def summarize(self, write_manifest=True):
        records = [*self.records, *self.test_records]
        class_counts = {}
        for record in records:
            class_counts[record.class_name] = class_counts.get(record.class_name, 0) + 1
        summary = Cifar10CorpusSummary(
            source="fake-cifar10",
            train_count=len(self.records),
            test_count=len(self.test_records),
            total_count=len(records),
            class_names=sorted(class_counts),
            class_counts=class_counts,
            manifest_path=str(self.manifest_path),
        )
        if write_manifest:
            self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            self.manifest_path.write_text("{}", encoding="utf-8")
        return summary


class FakeEmbedder:
    model_id = "fake"
    device = "cpu"

    @staticmethod
    def _vector(image):
        pixel = image.convert("RGB").getpixel((0, 0))
        if pixel[0] >= pixel[1]:
            return [1.0, 0.0]
        return [0.0, 1.0]

    def embed_images(self, images):
        return normalize_vectors(np.array([self._vector(image) for image in images], dtype=np.float32))

    def embed_image(self, image):
        return self.embed_images([image])[0]


@dataclass(frozen=True)
class FakeHit:
    metadata: dict
    score: float


class FakeIndex:
    backend = "fake"
    dimension = None

    def __init__(self):
        self.metadata = []
        self.vectors = []

    @property
    def count(self):
        return len(self.metadata)

    def has_image(self, image_id):
        return any(item["image_id"] == image_id for item in self.metadata)

    def add(self, vectors, metadata):
        self.vectors.extend(vectors.tolist())
        self.metadata.extend(metadata)
        self.dimension = len(self.vectors[0])

    def search(self, query, top_k):
        scores = np.asarray(self.vectors, dtype=np.float32) @ np.asarray(query, dtype=np.float32)
        order = np.argsort(-scores)[:top_k]
        return [FakeHit(self.metadata[index], float(scores[index])) for index in order]

    def clear(self):
        self.metadata = []
        self.vectors = []
        self.dimension = None

    def load(self):
        return None

    def remove(self, image_id):
        for index, item in enumerate(self.metadata):
            if item["image_id"] == image_id:
                self.metadata.pop(index)
                self.vectors.pop(index)
                return True
        return False


@pytest.fixture()
def service(tmp_path):
    config = AppConfig(
        model_id="fake-model",
        requested_device="cpu",
        data_path=tmp_path / "data",
        index_path=tmp_path / "index",
        model_cache_path=tmp_path / "models",
        preview_path=tmp_path / "previews",
        preview_url_base="/image-search/previews",
        batch_size=2,
        top_k_default=5,
        top_k_max=50,
        vector_backend="auto",
    )
    return ImageSearchService(
        config,
        dataset=FakeDataset(config.preview_path),
        embedder=FakeEmbedder(),
        vector_index=FakeIndex(),
    )


def test_expected_cifar10_summary_is_full_corpus():
    summary = Cifar10CorpusSummary.expected()

    assert summary.train_count == CIFAR10_TRAIN_COUNT
    assert summary.test_count == CIFAR10_TEST_COUNT
    assert summary.total_count == CIFAR10_TOTAL_COUNT
    assert len(summary.class_names) == CIFAR10_CLASS_COUNT
    assert set(summary.class_counts.values()) == {CIFAR10_PER_CLASS_TOTAL}
    assert summary.complete is True


def test_index_images_skips_already_indexed_items(service):
    first = service.index_images()
    second = service.index_images()

    assert first["indexed"] == 3
    assert first["active_count"] == 3
    assert first["complete"] is True
    assert second["indexed"] == 0
    assert second["skipped_existing"] == 3


def test_index_images_can_render_progress(service, capsys):
    service.index_images(show_progress=True)

    captured = capsys.readouterr()

    assert "Indexing CIFAR-10" in captured.out
    assert "3/3 seen" in captured.out
    assert "indexed=3" in captured.out


def test_preview_url_uses_absolute_path_relative_to_preview_root(service):
    preview_path = service.config.preview_path / "train" / "cifar10-train-14511.png"

    assert (
        service._preview_url(str(preview_path))
        == "/image-search/previews/train/cifar10-train-14511.png"
    )


@pytest.mark.parametrize(
    "preview_path",
    [
        r"data\previews\train\cifar10-train-14511.png",
        "data/previews/train/cifar10-train-14511.png",
        "C:/repo/examples/image-search-mcp/data/previews/train/cifar10-train-14511.png",
        "/data/previews/train/cifar10-train-14511.png",
    ],
)
def test_preview_url_normalizes_persisted_preview_paths(service, preview_path):
    assert (
        service._preview_url(preview_path)
        == "/image-search/previews/train/cifar10-train-14511.png"
    )


def test_search_similar_images_uses_single_query_embedding(service):
    service.index_images()

    result = service.search_similar_images(cifar10_test_index=0, top_k=2)

    assert result["count"] == 2
    assert result["top_k"] == 2
    assert result["corpus"]["complete"] is True
    assert result["results"][0]["image_id"] == "cifar10-train-00000"
    assert result["results"][0]["class_name"] == "airplane"
    assert result["results"][0]["cifar_split"] == "train"
    assert result["results"][0]["original_dataset_index"] == 0
    assert result["results"][0]["preview_url"] == "/image-search/previews/cifar10-train-00000.png"


def test_search_similar_images_caps_top_k(service):
    service.index_images()
    service.config = AppConfig(
        model_id=service.config.model_id,
        requested_device=service.config.requested_device,
        data_path=service.config.data_path,
        index_path=service.config.index_path,
        model_cache_path=service.config.model_cache_path,
        preview_path=service.config.preview_path,
        preview_url_base=service.config.preview_url_base,
        batch_size=service.config.batch_size,
        top_k_default=service.config.top_k_default,
        top_k_max=1,
        vector_backend=service.config.vector_backend,
    )

    result = service.search_similar_images(cifar10_test_index=0, top_k=10)

    assert result["requested_top_k"] == 10
    assert result["top_k"] == 1
    assert len(result["results"]) == 1


def test_search_similar_images_requires_initialized_index(service):
    with pytest.raises(RuntimeError, match="empty or not initialized"):
        service.search_similar_images(cifar10_test_index=0)


def test_partial_index_is_searchable_but_incomplete(tmp_path):
    config = AppConfig(
        model_id="fake-model",
        requested_device="cpu",
        data_path=tmp_path / "data",
        index_path=tmp_path / "index",
        model_cache_path=tmp_path / "models",
        preview_path=tmp_path / "previews",
        preview_url_base="/image-search/previews",
        batch_size=2,
        top_k_default=5,
        top_k_max=50,
        vector_backend="auto",
    )
    service = ImageSearchService(
        config,
        dataset=FakeDataset(config.preview_path, expected_summary=Cifar10CorpusSummary.expected()),
        embedder=FakeEmbedder(),
        vector_index=FakeIndex(),
    )
    service.index_images(max_items=3, write_previews=False)

    stats = service.list_index_stats()

    assert stats["active_count"] == 3
    assert stats["expected_count"] == CIFAR10_TOTAL_COUNT
    assert stats["complete"] is False
    assert stats["partial"] is True
    assert stats["searchable"] is True
    assert stats["healthy"] is True
    assert "partial CIFAR-10 index" in stats["warning"]

    result = service.search_similar_images(cifar10_test_index=0, top_k=2)

    assert result["count"] == 2
    assert result["corpus"]["complete"] is False
    assert result["corpus"]["partial"] is True
    assert result["corpus"]["healthy"] is True
    assert "partial CIFAR-10 index" in result["corpus"]["warning"]


def test_search_requires_exactly_one_query_source(service):
    with pytest.raises(ValueError, match="exactly one"):
        service.search_similar_images()

    with pytest.raises(ValueError, match="exactly one"):
        service.search_similar_images(image_path="a.png", cifar10_test_index=0)


def test_remove_image_updates_index(service):
    service.index_images()

    result = service.remove_image("cifar10-train-00000")

    assert result["removed"] is True
    assert result["active_count"] == 2
