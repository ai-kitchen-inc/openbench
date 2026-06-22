"""Provider-agnostic media normalization helpers.

Some image formats (HEIC, TIFF, BMP, GIF, SVG) are not universally accepted by
downstream consumers — OCR engines and multimodal LLM APIs typically want
PNG/JPEG. These helpers convert an arbitrary image into a widely-accepted raster
so both the OCR text track and the native multimodal track can consume it.

All third-party imports (Pillow, pillow-heif, cairosvg) are lazy: importing this
module never requires the optional ``[media]`` extra. The error only surfaces
when a conversion that needs the dependency is actually attempted.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Extensions whose bytes are already PNG/JPEG/WEBP and need no conversion.
_NATIVE_RASTER_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_HEIC_EXTS = {".heic", ".heif"}
_PILLOW_CONVERT_EXTS = {".tiff", ".tif", ".bmp", ".gif"}
_SVG_EXTS = {".svg"}


def is_svg(path: str | Path, mime_type: str = "") -> bool:
    """Return True when the file is an SVG (by extension or MIME type)."""
    return Path(path).suffix.lower() in _SVG_EXTS or mime_type == "image/svg+xml"


def read_svg_text(path: str | Path) -> str:
    """Read an SVG as text. SVG is XML, so its markup is directly readable."""
    p = Path(path)
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="latin-1")


def normalize_image(path: str | Path, mime_type: str = "") -> tuple[str, str]:
    """Normalize an image to a raster PNG/JPEG widely accepted downstream.

    Args:
        path: Path to the source image.
        mime_type: Optional MIME hint (used for SVG detection).

    Returns:
        Tuple of ``(output_path, output_mime_type)``. When the input already
        is a native raster (PNG/JPEG/WEBP) the original path is returned
        unchanged. Conversions write a sibling file next to the source.

    Raises:
        RuntimeError: If a required optional dependency is missing.
        ValueError: If the conversion fails.
    """
    src = Path(path)
    ext = src.suffix.lower()

    if ext in _NATIVE_RASTER_EXTS:
        return str(src), mime_type or _ext_mime(ext)

    if ext in _HEIC_EXTS or mime_type in {"image/heic", "image/heif"}:
        return _convert_heic_to_jpeg(src)

    if is_svg(src, mime_type):
        return _rasterize_svg(src)

    if ext in _PILLOW_CONVERT_EXTS:
        return _convert_with_pillow(src)

    # Unknown image type — hand back as-is and let the caller decide.
    return str(src), mime_type or _ext_mime(ext)


def _convert_heic_to_jpeg(src: Path) -> tuple[str, str]:
    try:
        import pillow_heif
        from PIL import Image

        pillow_heif.register_heif_opener()
    except ImportError as exc:
        raise RuntimeError(
            "pillow-heif is required for HEIC support. "
            "Install with: pip install 'openbench[media]'"
        ) from exc

    out = src.with_suffix(".jpg")
    try:
        with Image.open(src) as image:
            image.convert("RGB").save(out, format="JPEG")
    except Exception as exc:
        raise ValueError(f"HEIC conversion failed for {src.name}: {exc}") from exc
    return str(out), "image/jpeg"


def _convert_with_pillow(src: Path) -> tuple[str, str]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required for TIFF/BMP/GIF support. "
            "Install with: pip install 'openbench[media]'"
        ) from exc

    out = src.with_suffix(".png")
    try:
        with Image.open(src) as image:
            # GIF/animated: first frame is sufficient for understanding/OCR.
            if getattr(image, "is_animated", False):
                image.seek(0)
            image.convert("RGBA").save(out, format="PNG")
    except Exception as exc:
        raise ValueError(f"Image conversion failed for {src.name}: {exc}") from exc
    return str(out), "image/png"


def _rasterize_svg(src: Path) -> tuple[str, str]:
    try:
        import cairosvg
    except ImportError as exc:
        raise RuntimeError(
            "cairosvg is required for SVG rasterization. "
            "Install with: pip install 'openbench[media]'"
        ) from exc

    out = src.with_suffix(".png")
    try:
        cairosvg.svg2png(url=str(src), write_to=str(out))
    except Exception as exc:
        raise ValueError(f"SVG rasterization failed for {src.name}: {exc}") from exc
    return str(out), "image/png"


def _ext_mime(ext: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")
