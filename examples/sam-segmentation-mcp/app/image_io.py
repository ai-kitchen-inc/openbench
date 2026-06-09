"""Image loading and validation helpers for SAM 3 concept counting."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

SUPPORTED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class LoadedImage:
    """Loaded RGB image plus non-sensitive source metadata."""

    image: Image.Image
    metadata: dict[str, Any]


def _ensure_image_limits(image: Image.Image, *, max_pixels: int) -> None:
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("Image has invalid dimensions.")
    if width * height > max_pixels:
        raise ValueError(f"Image exceeds the {max_pixels} pixel limit.")


def _read_supported_image(data: bytes, *, max_pixels: int) -> Image.Image:
    try:
        with Image.open(BytesIO(data)) as image:
            if (image.format or "").lower() not in {"png", "jpeg", "jpg", "webp"}:
                raise ValueError("Only png, jpeg, and webp images are supported.")
            converted = image.convert("RGB")
            converted.load()
    except UnidentifiedImageError as exc:
        raise ValueError("Input is not a supported png, jpeg, or webp image.") from exc
    _ensure_image_limits(converted, max_pixels=max_pixels)
    return converted


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_allowed_path(path: Path, allowed_roots: list[Path]) -> None:
    if not allowed_roots:
        return
    resolved = path.resolve()
    resolved_roots = [root.resolve() for root in allowed_roots]
    if not any(_is_relative_to(resolved, root) for root in resolved_roots):
        roots = ", ".join(str(root) for root in resolved_roots)
        raise ValueError(f"image_path must be under an allowed input root: {roots}")


def load_image_path(
    image_path: str,
    *,
    allowed_roots: list[Path],
    max_bytes: int,
    max_pixels: int,
) -> LoadedImage:
    """Load a local image path as RGB."""
    path = Path(image_path).expanduser()
    if not path.exists() or not path.is_file():
        raise ValueError(f"image_path does not exist or is not a file: {image_path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("image_path must point to a png, jpg, jpeg, or webp file.")
    _validate_allowed_path(path, allowed_roots)
    size_bytes = path.stat().st_size
    if size_bytes <= 0:
        raise ValueError("image_path is empty.")
    if size_bytes > max_bytes:
        raise ValueError(f"image_path exceeds the {max_bytes} byte limit.")
    image = _read_supported_image(path.read_bytes(), max_pixels=max_pixels)
    return LoadedImage(
        image=image,
        metadata={"source": "image_path", "image_path": image_path, "size_bytes": size_bytes},
    )


def load_image_base64(
    image_base64: str,
    *,
    mime_type: str | None,
    max_bytes: int,
    max_pixels: int,
) -> LoadedImage:
    """Load a base64-encoded image as RGB."""
    raw = image_base64.strip()
    data_url_mime = None
    if raw.lower().startswith("data:") and "," in raw:
        header, raw = raw.split(",", 1)
        data_url_mime = header[5:].split(";", 1)[0].strip().lower() or None
    selected_mime = (mime_type or data_url_mime or "").strip().lower()
    if selected_mime and selected_mime not in SUPPORTED_MIME_TYPES:
        raise ValueError("mime_type must be image/png, image/jpeg, or image/webp.")
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError("image_base64 must be valid base64 image bytes or a data URL.") from exc
    if not data:
        raise ValueError("image_base64 is empty.")
    if len(data) > max_bytes:
        raise ValueError(f"image_base64 exceeds the {max_bytes} byte limit.")
    image = _read_supported_image(data, max_pixels=max_pixels)
    return LoadedImage(
        image=image,
        metadata={
            "source": "image_base64",
            "mime_type": selected_mime or None,
            "size_bytes": len(data),
        },
    )
