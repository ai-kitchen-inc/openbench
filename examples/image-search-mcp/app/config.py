"""Environment-driven configuration for the image search MCP service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_MODEL_ID = "facebook/dinov3-vits16-pretrain-lvd1689m"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class AppConfig:
    """Runtime settings for local DINOv3 image search."""

    model_id: str
    requested_device: str
    data_path: Path
    index_path: Path
    model_cache_path: Path
    preview_path: Path
    preview_url_base: str | None
    batch_size: int
    top_k_default: int
    vector_backend: Literal["auto", "faiss", "hnswlib"]
    image_url_timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls) -> AppConfig:
        """Build configuration from environment variables."""
        data_path = Path(os.getenv("DATA_PATH", "data")).expanduser()
        index_path = Path(os.getenv("INDEX_PATH", str(data_path / "index"))).expanduser()
        model_cache_path = Path(os.getenv("MODEL_CACHE_PATH", "models")).expanduser()
        preview_path = Path(os.getenv("PREVIEW_PATH", str(data_path / "previews"))).expanduser()
        backend = os.getenv("VECTOR_BACKEND", "auto").strip().lower() or "auto"
        if backend not in {"auto", "faiss", "hnswlib"}:
            raise ValueError("VECTOR_BACKEND must be one of: auto, faiss, hnswlib")
        return cls(
            model_id=os.getenv("DINO_MODEL_ID", DEFAULT_MODEL_ID),
            requested_device=os.getenv("DEVICE", "auto"),
            data_path=data_path,
            index_path=index_path,
            model_cache_path=model_cache_path,
            preview_path=preview_path,
            preview_url_base=os.getenv("PREVIEW_URL_BASE") or None,
            batch_size=_env_int("BATCH_SIZE", 64),
            top_k_default=_env_int("TOP_K_DEFAULT", 10),
            vector_backend=backend,  # type: ignore[arg-type]
        )

    def ensure_directories(self) -> None:
        """Create local persistence directories if they do not exist."""
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.index_path.mkdir(parents=True, exist_ok=True)
        self.model_cache_path.mkdir(parents=True, exist_ok=True)
        self.preview_path.mkdir(parents=True, exist_ok=True)
