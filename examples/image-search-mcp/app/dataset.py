"""CIFAR-10 loading and preview helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from PIL import Image

CIFAR10_CLASSES = [
    "airplane",
    "automobile",
    "bird",
    "cat",
    "deer",
    "dog",
    "frog",
    "horse",
    "ship",
    "truck",
]


@dataclass(frozen=True)
class CifarImageRecord:
    """A CIFAR-10 image plus searchable metadata."""

    image_id: str
    split: str
    class_id: int
    class_name: str
    original_dataset_index: int
    image: Image.Image

    def metadata(self, preview_path: str | None = None, embedding_checksum: str | None = None) -> dict:
        """Return JSON-serializable metadata for this image."""
        metadata = {
            "image_id": self.image_id,
            "cifar_split": self.split,
            "class_id": self.class_id,
            "class_name": self.class_name,
            "original_dataset_index": self.original_dataset_index,
        }
        if embedding_checksum:
            metadata["embedding_checksum"] = embedding_checksum
        if preview_path:
            metadata["preview_path"] = preview_path
        return metadata


class Cifar10Store:
    """Lazy CIFAR-10 loader backed by torchvision."""

    def __init__(self, data_root: Path, preview_root: Path):
        self.data_root = data_root
        self.preview_root = preview_root
        self._train = None
        self._test = None

    def _load_split(self, split: str):
        try:
            from torchvision.datasets import CIFAR10
        except ImportError as exc:
            raise ImportError("torchvision is required to download and load CIFAR-10") from exc

        if split == "train":
            if self._train is None:
                self._train = CIFAR10(root=str(self.data_root / "cifar10"), train=True, download=True)
            return self._train
        if split == "test":
            if self._test is None:
                self._test = CIFAR10(root=str(self.data_root / "cifar10"), train=False, download=True)
            return self._test
        raise ValueError("split must be 'train' or 'test'")

    @staticmethod
    def _record(split: str, index: int, item: tuple[Image.Image, int]) -> CifarImageRecord:
        image, label = item
        class_id = int(label)
        return CifarImageRecord(
            image_id=f"cifar10-{split}-{index:05d}",
            split=split,
            class_id=class_id,
            class_name=CIFAR10_CLASSES[class_id],
            original_dataset_index=index,
            image=image.convert("RGB"),
        )

    def iter_train(self, *, max_items: int | None = None) -> Iterator[CifarImageRecord]:
        """Yield CIFAR-10 train records for indexing."""
        dataset = self._load_split("train")
        limit = len(dataset) if max_items is None else min(max_items, len(dataset))
        for index in range(limit):
            yield self._record("train", index, dataset[index])

    def get_test(self, index: int) -> CifarImageRecord:
        """Return a CIFAR-10 test record for query demos."""
        dataset = self._load_split("test")
        if index < 0 or index >= len(dataset):
            raise ValueError(f"cifar10_test_index must be between 0 and {len(dataset) - 1}")
        return self._record("test", index, dataset[index])

    def save_preview(self, record: CifarImageRecord) -> str:
        """Persist a PNG preview for an indexed CIFAR image."""
        split_dir = self.preview_root / record.split
        split_dir.mkdir(parents=True, exist_ok=True)
        path = split_dir / f"{record.image_id}.png"
        if not path.exists():
            record.image.save(path, format="PNG")
        return str(path)
