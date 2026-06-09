"""DINOv3 image embedding utilities."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def normalize_vectors(vectors: np.ndarray) -> np.ndarray:
    """Return L2-normalized float32 vectors."""
    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (array / norms).astype(np.float32)


def embedding_checksum(vector: np.ndarray) -> str:
    """Compute a short checksum for a normalized embedding."""
    digest = hashlib.sha256(np.asarray(vector, dtype=np.float32).tobytes()).hexdigest()
    return f"sha256:{digest[:16]}"


class DinoV3Embedder:
    """Lazy DINOv3 embedder using HuggingFace Transformers and PyTorch."""

    def __init__(
        self, model_id: str, requested_device: str = "auto", cache_dir: Path | None = None
    ):
        self.model_id = model_id
        self.requested_device = requested_device
        self.cache_dir = cache_dir
        self._processor = None
        self._model = None
        self._device = None

    @property
    def device(self) -> str:
        """Return the actual device, resolving CUDA availability lazily."""
        if self._device is None:
            self._device = self._resolve_device()
        return self._device

    def _resolve_device(self) -> str:
        try:
            import torch
        except ImportError as exc:
            raise ImportError("torch is required for DINOv3 embeddings") from exc

        requested = (self.requested_device or "auto").lower()
        if requested == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        if requested == "cuda" and not torch.cuda.is_available():
            logger.warning("DEVICE=cuda requested but CUDA is unavailable; falling back to CPU")
            return "cpu"
        return requested

    def _load(self) -> None:
        if self._model is not None and self._processor is not None:
            return
        try:
            import torch
            from transformers import AutoImageProcessor, AutoModel
        except ImportError as exc:
            raise ImportError("torch and transformers are required for DINOv3 embeddings") from exc

        cache_dir = str(self.cache_dir) if self.cache_dir else None
        self._processor = AutoImageProcessor.from_pretrained(self.model_id, cache_dir=cache_dir)
        self._model = AutoModel.from_pretrained(self.model_id, cache_dir=cache_dir)
        self._model.to(torch.device(self.device))
        self._model.eval()

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        """Embed a batch of PIL images and return normalized vectors."""
        if not images:
            return np.empty((0, 0), dtype=np.float32)
        self._load()

        import torch

        rgb_images = [image.convert("RGB") for image in images]
        inputs = self._processor(images=rgb_images, return_tensors="pt")
        inputs = {key: value.to(torch.device(self.device)) for key, value in inputs.items()}

        with torch.no_grad():
            outputs = self._model(**inputs)
            if getattr(outputs, "pooler_output", None) is not None:
                features = outputs.pooler_output
            else:
                features = outputs.last_hidden_state[:, 0]
        return normalize_vectors(features.detach().cpu().numpy())

    def embed_image(self, image: Image.Image) -> np.ndarray:
        """Embed one image and return a single normalized vector."""
        return self.embed_images([image])[0]
