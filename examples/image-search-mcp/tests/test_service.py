from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.config import AppConfig
from app.dataset import CifarImageRecord
from app.embeddings import normalize_vectors
from app.service import ImageSearchService


class FakeDataset:
    def __init__(self, preview_root: Path):
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

    def iter_train(self, max_items=None):
        yield from self.records[:max_items]

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
        vector_backend="auto",
    )
    return ImageSearchService(
        config,
        dataset=FakeDataset(config.preview_path),
        embedder=FakeEmbedder(),
        vector_index=FakeIndex(),
    )


def test_index_images_skips_already_indexed_items(service):
    first = service.index_images()
    second = service.index_images()

    assert first["indexed"] == 2
    assert first["active_count"] == 2
    assert second["indexed"] == 0
    assert second["skipped_existing"] == 2


def test_search_similar_images_uses_single_query_embedding(service):
    service.index_images()

    result = service.search_similar_images(cifar10_test_index=0, top_k=1)

    assert result["count"] == 1
    assert result["results"][0]["image_id"] == "cifar10-train-00000"
    assert result["results"][0]["class_name"] == "airplane"
    assert result["results"][0]["preview_url"] == "/image-search/previews/cifar10-train-00000.png"


def test_search_requires_exactly_one_query_source(service):
    with pytest.raises(ValueError, match="exactly one"):
        service.search_similar_images()

    with pytest.raises(ValueError, match="exactly one"):
        service.search_similar_images(image_path="a.png", cifar10_test_index=0)


def test_remove_image_updates_index(service):
    service.index_images()

    result = service.remove_image("cifar10-train-00000")

    assert result["removed"] is True
    assert result["active_count"] == 1
