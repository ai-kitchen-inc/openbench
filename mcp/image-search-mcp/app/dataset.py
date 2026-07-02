"""CIFAR-10 loading and preview helpers."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

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
CIFAR10_TRAIN_COUNT = 50_000
CIFAR10_TEST_COUNT = 10_000
CIFAR10_TOTAL_COUNT = CIFAR10_TRAIN_COUNT + CIFAR10_TEST_COUNT
CIFAR10_CLASS_COUNT = len(CIFAR10_CLASSES)
CIFAR10_PER_CLASS_TOTAL = 6_000
CIFAR10_SOURCE = "torchvision.datasets.CIFAR10"


@dataclass(frozen=True)
class Cifar10CorpusSummary:
    """Expected or observed CIFAR-10 corpus counts."""

    source: str
    train_count: int
    test_count: int
    total_count: int
    class_names: list[str]
    class_counts: dict[str, int]
    generated_at: str | None = None
    manifest_path: str | None = None

    @property
    def split_counts(self) -> dict[str, int]:
        """Return train/test counts keyed like indexed metadata."""
        return {"train": self.train_count, "test": self.test_count}

    @property
    def complete(self) -> bool:
        """Return whether the summary matches the full CIFAR-10 corpus."""
        return (
            self.train_count == CIFAR10_TRAIN_COUNT
            and self.test_count == CIFAR10_TEST_COUNT
            and self.total_count == CIFAR10_TOTAL_COUNT
            and len(self.class_names) == CIFAR10_CLASS_COUNT
            and all(self.class_counts.get(name) == CIFAR10_PER_CLASS_TOTAL for name in CIFAR10_CLASSES)
        )

    def to_dict(self) -> dict:
        """Return a JSON-serializable summary."""
        return {
            "source": self.source,
            "train_count": self.train_count,
            "test_count": self.test_count,
            "total_count": self.total_count,
            "class_count": len(self.class_names),
            "class_names": list(self.class_names),
            "class_counts": dict(self.class_counts),
            "split_counts": self.split_counts,
            "expected_train_count": CIFAR10_TRAIN_COUNT,
            "expected_test_count": CIFAR10_TEST_COUNT,
            "expected_total_count": CIFAR10_TOTAL_COUNT,
            "expected_per_class_total": CIFAR10_PER_CLASS_TOTAL,
            "complete": self.complete,
            "generated_at": self.generated_at,
            "manifest_path": self.manifest_path,
        }

    @classmethod
    def expected(cls) -> Cifar10CorpusSummary:
        """Return the canonical expected CIFAR-10 corpus summary."""
        return cls(
            source=CIFAR10_SOURCE,
            train_count=CIFAR10_TRAIN_COUNT,
            test_count=CIFAR10_TEST_COUNT,
            total_count=CIFAR10_TOTAL_COUNT,
            class_names=list(CIFAR10_CLASSES),
            class_counts=dict.fromkeys(CIFAR10_CLASSES, CIFAR10_PER_CLASS_TOTAL),
        )


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

    @property
    def manifest_path(self) -> Path:
        """Path for the local CIFAR-10 corpus manifest."""
        return self.data_root / "cifar10" / "openbench_cifar10_manifest.json"

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

    def iter_all(self, *, max_items: int | None = None) -> Iterator[CifarImageRecord]:
        """Yield CIFAR-10 records across train and test splits."""
        yielded = 0
        for split in ("train", "test"):
            dataset = self._load_split(split)
            for index in range(len(dataset)):
                if max_items is not None and yielded >= max_items:
                    return
                yielded += 1
                yield self._record(split, index, dataset[index])

    def expected_summary(self) -> Cifar10CorpusSummary:
        """Return expected full CIFAR-10 counts without loading data."""
        return Cifar10CorpusSummary.expected()

    def summarize(self, *, write_manifest: bool = True) -> Cifar10CorpusSummary:
        """Load CIFAR-10 metadata and summarize train/test/class counts."""
        split_targets = {
            "train": list(self._load_split("train").targets),
            "test": list(self._load_split("test").targets),
        }
        class_counts: Counter[str] = Counter()
        for targets in split_targets.values():
            class_counts.update(CIFAR10_CLASSES[int(label)] for label in targets)

        generated_at = datetime.now(timezone.utc).isoformat()
        manifest_path = str(self.manifest_path)
        summary = Cifar10CorpusSummary(
            source=CIFAR10_SOURCE,
            train_count=len(split_targets["train"]),
            test_count=len(split_targets["test"]),
            total_count=len(split_targets["train"]) + len(split_targets["test"]),
            class_names=list(CIFAR10_CLASSES),
            class_counts={name: int(class_counts.get(name, 0)) for name in CIFAR10_CLASSES},
            generated_at=generated_at,
            manifest_path=manifest_path,
        )
        if write_manifest:
            self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            self.manifest_path.write_text(
                json.dumps(summary.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
        return summary

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
