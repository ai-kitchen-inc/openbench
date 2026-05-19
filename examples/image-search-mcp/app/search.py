"""Query image loading helpers."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError


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


def load_image_url(image_url: str, *, timeout_seconds: float) -> Image.Image:
    """Fetch an image URL and return RGB pixels."""
    try:
        import requests
    except ImportError as exc:
        raise ImportError("requests is required for image_url inputs") from exc

    response = requests.get(image_url, timeout=timeout_seconds)
    response.raise_for_status()
    try:
        return Image.open(BytesIO(response.content)).convert("RGB")
    except UnidentifiedImageError as exc:
        raise ValueError(f"image_url did not return a supported image: {image_url}") from exc
