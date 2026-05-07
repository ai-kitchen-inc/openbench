"""Document and image content extraction using Docling."""

from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Any

from openbench.chat.files import FileContentExtractor, StoredFile

logger = logging.getLogger(__name__)

_DOCLING_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
}
_DOCLING_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".ppt"}

_DOCX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}
_DOCX_EXTENSIONS = {".docx", ".doc"}

_IMAGE_MIME_TYPES = {"image/png"}
_IMAGE_EXTENSIONS = {".png"}

_fallback = FileContentExtractor()


class DoclingContentExtractor:
    """Extract text and image OCR using Docling, with narrow fallbacks."""

    def extract(self, stored_file: StoredFile) -> str:
        ext = Path(stored_file.name).suffix.lower()
        if stored_file.mime_type in _DOCLING_MIME_TYPES or ext in _DOCLING_EXTENSIONS:
            return self._extract_with_docling(stored_file)
        return _fallback.extract(stored_file)

    def extract_image(self, stored_file: StoredFile) -> dict[str, Any]:
        ext = Path(stored_file.name).suffix.lower()
        if stored_file.mime_type not in _IMAGE_MIME_TYPES and ext not in _IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported image source type: {ext or stored_file.mime_type}")

        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise RuntimeError("docling is required for PNG OCR support.") from exc

        try:
            converter = DocumentConverter()
            result = converter.convert(stored_file.path)
            markdown = result.document.export_to_markdown().strip()
        except Exception as exc:
            logger.warning("Docling image extraction failed for %s: %s", stored_file.name, exc)
            raise ValueError(f"Image extraction failed: {exc}") from exc

        if not markdown:
            raise ValueError(f"No OCR text could be extracted from {stored_file.name}.")

        dimensions = _png_dimensions(stored_file.path)
        width = dimensions.get("width")
        height = dimensions.get("height")
        description = _image_description(stored_file.name, width, height, markdown)
        search_text = _build_image_search_text(
            stored_file.name,
            description,
            markdown,
            dimensions,
        )

        return {
            "description": description,
            "ocr_text": markdown,
            "search_text": search_text,
            "metadata": {
                "format": "png",
                "width": width,
                "height": height,
            },
        }

    def _extract_with_docling(self, stored_file: StoredFile) -> str:
        try:
            from docling.document_converter import DocumentConverter

            converter = DocumentConverter()
            result = converter.convert(stored_file.path)
            text = result.document.export_to_markdown()
            if not text.strip():
                return f"[{stored_file.name}] (document appears empty after extraction)"
            return text
        except ImportError:
            logger.warning(
                "docling not installed; trying python-docx for %s", stored_file.name
            )
            return self._extract_with_python_docx(stored_file)
        except Exception as exc:
            logger.warning("Docling extraction failed for %s: %s", stored_file.name, exc)
            ext = Path(stored_file.name).suffix.lower()
            if stored_file.mime_type in _DOCX_MIME_TYPES or ext in _DOCX_EXTENSIONS:
                logger.info("Falling back to python-docx for %s", stored_file.name)
                return self._extract_with_python_docx(stored_file)
            return f"[{stored_file.name}] (extraction failed: {exc})"

    def _extract_with_python_docx(self, stored_file: StoredFile) -> str:
        try:
            import docx

            doc = docx.Document(stored_file.path)
            parts: list[str] = []

            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    parts.append(text)

            for table in doc.tables:
                for row in table.rows:
                    row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if row_cells:
                        parts.append(" | ".join(row_cells))

            full_text = "\n\n".join(parts)
            if not full_text.strip():
                return f"[{stored_file.name}] (document appears empty after extraction)"
            return full_text
        except ImportError:
            logger.warning("python-docx not installed; install it with: pip install python-docx")
            return _fallback.extract(stored_file)
        except Exception as exc:
            logger.warning(
                "python-docx extraction failed for %s: %s", stored_file.name, exc
            )
            return _fallback.extract(stored_file)


def _png_dimensions(path: str) -> dict[str, int | None]:
    try:
        with open(path, "rb") as handle:
            header = handle.read(24)
    except OSError:
        return {"width": None, "height": None}

    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return {"width": None, "height": None}

    width, height = struct.unpack(">II", header[16:24])
    return {"width": int(width), "height": int(height)}


def _image_description(name: str, width: int | None, height: int | None, ocr_text: str) -> str:
    size = f"{width}x{height}" if width and height else "unknown size"
    if ocr_text.strip():
        return f"PNG image source {name} ({size}) with OCR-detected text."
    return f"PNG image source {name} ({size}) with no OCR text detected."


def _build_image_search_text(
    name: str,
    description: str,
    ocr_text: str,
    dimensions: dict[str, int | None],
) -> str:
    width = dimensions.get("width")
    height = dimensions.get("height")
    lines = [
        f"## {name}",
        "",
        "### Image summary",
        description,
        f"Format: PNG",
        f"Dimensions: {width or 'unknown'} x {height or 'unknown'}",
        "",
        "### Detected text",
        ocr_text.strip() or "(No OCR text detected.)",
    ]
    return "\n".join(lines).strip()
