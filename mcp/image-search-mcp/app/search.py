"""Query image loading helpers."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.net_guard import safe_get


def load_image_path(image_path: str) -> Image.Image:
    """Load a local jpg/png/webp image path as RGB."""
    path = Path(image_path).expanduser()
    if not path.exists() or not path.is_file():
        raise ValueError(f"image_path does not exist or is not a file: {image_path}")
    try:
        return Image.open(path).convert("RGB")
    except UnidentifiedImageError as exc:
        raise ValueError(f"image_path is not a supported image: {image_path}") from exc


def load_image_base64(image_base64: str) -> Image.Image:
    """Load a base64-encoded image as RGB."""
    raw = image_base64.strip()
    if "," in raw and raw.lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=True)
        return Image.open(BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise ValueError("image_base64 must be a valid base64-encoded jpg/png/webp image") from exc


#: Upper bound for a fetched query image.
_MAX_IMAGE_URL_BYTES = 25 * 1024 * 1024


def load_image_url(image_url: str, *, timeout_seconds: float) -> Image.Image:
    """Fetch an image URL and return RGB pixels.

    The URL is a tool argument chosen by the model, so it goes through the
    SSRF guard: public hosts only, every redirect hop re-checked, body capped.
    """
    try:
        import requests  # noqa: F401  (safe_get needs it; fail with a clear message)
    except ImportError as exc:
        raise ImportError("requests is required for image_url inputs") from exc

    fetched = safe_get(image_url, max_bytes=_MAX_IMAGE_URL_BYTES, timeout=timeout_seconds)
    try:
        return Image.open(BytesIO(fetched.content)).convert("RGB")
    except UnidentifiedImageError as exc:
        raise ValueError(f"image_url did not return a supported image: {image_url}") from exc
