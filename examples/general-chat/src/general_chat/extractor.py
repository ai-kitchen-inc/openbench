"""Document and image content extraction using Docling."""

from __future__ import annotations

import logging
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

_PDF_MIME_TYPES = {"application/pdf"}
_PDF_EXTENSIONS = {".pdf"}

_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

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
            raise RuntimeError("docling is required for image OCR support.") from exc

        try:
            converter = DocumentConverter()
            result = converter.convert(stored_file.path)
            markdown = result.document.export_to_markdown().strip()
        except Exception as exc:
            logger.warning("Docling image extraction failed for %s: %s", stored_file.name, exc)
            raise ValueError(f"Image extraction failed: {exc}") from exc

        if not markdown:
            raise ValueError(f"No OCR text could be extracted from {stored_file.name}.")

        image_format = _image_format(stored_file.name, stored_file.mime_type)
        dimensions = _image_dimensions(stored_file.path)
        width = dimensions.get("width")
        height = dimensions.get("height")
        description = _image_description(stored_file.name, image_format, width, height, markdown)
        search_text = _build_image_search_text(
            stored_file.name,
            image_format,
            description,
            markdown,
            dimensions,
        )

        return {
            "description": description,
            "ocr_text": markdown,
            "search_text": search_text,
            "metadata": {
                "format": image_format.lower(),
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
            if _is_pdf(stored_file):
                logger.warning("docling not installed; trying pypdf for %s", stored_file.name)
                return self._extract_with_pypdf(stored_file)
            logger.warning("docling not installed; trying python-docx for %s", stored_file.name)
            return self._extract_with_python_docx(stored_file)
        except Exception as exc:
            logger.warning("Docling extraction failed for %s: %s", stored_file.name, exc)
            ext = Path(stored_file.name).suffix.lower()
            if _is_pdf(stored_file):
                logger.info("Falling back to pypdf for %s", stored_file.name)
                return self._extract_with_pypdf(stored_file)
            if stored_file.mime_type in _DOCX_MIME_TYPES or ext in _DOCX_EXTENSIONS:
                logger.info("Falling back to python-docx for %s", stored_file.name)
                return self._extract_with_python_docx(stored_file)
            return f"[{stored_file.name}] (extraction failed: {exc})"

    def _extract_with_pypdf(self, stored_file: StoredFile) -> str:
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.warning("pypdf not installed; install it with: pip install pypdf")
            return f"[{stored_file.name}] (extraction failed: pypdf is required for PDF extraction)"

        try:
            reader = PdfReader(stored_file.path)
            parts: list[str] = []
            for index, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                if text:
                    parts.append(f"### Page {index}\n\n{text}")
            full_text = "\n\n".join(parts).strip()
            if not full_text:
                return f"[{stored_file.name}] (document appears empty after extraction)"
            return full_text
        except Exception as exc:
            logger.warning("pypdf extraction failed for %s: %s", stored_file.name, exc)
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
            logger.warning("python-docx extraction failed for %s: %s", stored_file.name, exc)
            return _fallback.extract(stored_file)


def _is_pdf(stored_file: StoredFile) -> bool:
    ext = Path(stored_file.name).suffix.lower()
    return stored_file.mime_type in _PDF_MIME_TYPES or ext in _PDF_EXTENSIONS


def _image_dimensions(path: str) -> dict[str, int | None]:
    try:
        from PIL import Image
    except ImportError:
        return {"width": None, "height": None}

    try:
        with Image.open(path) as image:
            width, height = image.size
    except Exception:
        return {"width": None, "height": None}

    return {"width": int(width), "height": int(height)}


def _image_format(name: str, mime_type: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in {".jpg", ".jpeg"} or mime_type == "image/jpeg":
        return "JPEG"
    if ext == ".webp" or mime_type == "image/webp":
        return "WEBP"
    return "PNG"


def _image_description(
    name: str, image_format: str, width: int | None, height: int | None, ocr_text: str
) -> str:
    size = f"{width}x{height}" if width and height else "unknown size"
    if ocr_text.strip():
        return f"{image_format} image source {name} ({size}) with OCR-detected text."
    return f"{image_format} image source {name} ({size}) with no OCR text detected."


def _build_image_search_text(
    name: str,
    image_format: str,
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
        f"Format: {image_format}",
        f"Dimensions: {width or 'unknown'} x {height or 'unknown'}",
        "",
        "### Detected text",
        ocr_text.strip() or "(No OCR text detected.)",
    ]
    return "\n".join(lines).strip()
