"""Environment-driven configuration for the SAM 3 concept counting MCP service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SAM3_MODEL_PATH = "/models/sam3.pt"
DEFAULT_ALLOWED_ROOTS = "data,uploads,/data,/input,/general-chat/uploads"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_roots(name: str, default: str) -> list[Path]:
    raw = os.getenv(name, default)
    if raw.strip() == "":
        return []
    return [Path(item.strip()).expanduser() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class AppConfig:
    """Runtime settings for local SAM 3 concept counting."""

    sam3_model_path: Path
    sam3_conf: float
    sam3_half: bool
    sam3_device: str
    sam3_verbose: bool
    allowed_image_roots: list[Path]
    max_image_bytes: int
    max_image_pixels: int
    return_overlay_default: bool
    debug_output_dir: Path
    debug_output_url_base: str | None

    @classmethod
    def from_env(cls) -> AppConfig:
        """Build configuration from environment variables."""
        return cls(
            sam3_model_path=Path(
                os.getenv("SAM3_MODEL_PATH", DEFAULT_SAM3_MODEL_PATH)
            ).expanduser(),
            sam3_conf=_env_float("SAM3_CONF", 0.25),
            sam3_half=_env_bool("SAM3_HALF", False),
            sam3_device=os.getenv("SAM3_DEVICE", os.getenv("DEVICE", "cpu")),
            sam3_verbose=_env_bool("SAM3_VERBOSE", False),
            allowed_image_roots=_env_roots("IMAGE_INPUT_ROOTS", DEFAULT_ALLOWED_ROOTS),
            max_image_bytes=_env_int("MAX_IMAGE_BYTES", 10 * 1024 * 1024),
            max_image_pixels=_env_int("MAX_IMAGE_PIXELS", 12_000_000),
            return_overlay_default=_env_bool("RETURN_OVERLAY_DEFAULT", False),
            debug_output_dir=Path(
                os.getenv("DEBUG_OUTPUT_DIR", "/tmp/sam-segmentation-debug")
            ).expanduser(),
            debug_output_url_base=(os.getenv("DEBUG_OUTPUT_URL_BASE", "").strip() or None),
        )

    def ensure_directories(self) -> None:
        """Create runtime directories that may hold temporary artifacts."""
        self.sam3_model_path.parent.mkdir(parents=True, exist_ok=True)
        self.debug_output_dir.mkdir(parents=True, exist_ok=True)
