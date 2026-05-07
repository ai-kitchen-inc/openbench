"""Document content extractor using Docling for rich file types."""

from __future__ import annotations

import logging
from pathlib import Path

from openbench.chat.files import FileContentExtractor, StoredFile

logger = logging.getLogger(__name__)

# MIME types that Docling handles well
_DOCLING_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/msword",  # .doc
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
    "application/vnd.ms-powerpoint",  # .ppt
}

# Extension-based fallback when browser sends application/octet-stream
_DOCLING_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".ppt"}

# MIME types / extensions that python-docx can handle as a secondary fallback
_DOCX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}
_DOCX_EXTENSIONS = {".docx", ".doc"}

_fallback = FileContentExtractor()


class DoclingContentExtractor:
    """Extract text from documents using Docling, with fallback chain for Word files.

    Extraction priority:
      1. Docling — PDF, DOCX, DOC, PPTX, PPT (best quality, markdown output).
      2. python-docx — DOCX/DOC only, when Docling is not installed or fails.
      3. FileContentExtractor — everything else (Excel, CSV, plain text, images).
    """

    def extract(self, stored_file: StoredFile) -> str:
        ext = Path(stored_file.name).suffix.lower()
        if stored_file.mime_type in _DOCLING_MIME_TYPES or ext in _DOCLING_EXTENSIONS:
            return self._extract_with_docling(stored_file)
        return _fallback.extract(stored_file)

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
            if (
                stored_file.mime_type in _DOCX_MIME_TYPES
                or ext in _DOCX_EXTENSIONS
            ):
                logger.info(
                    "Falling back to python-docx for %s", stored_file.name
                )
                return self._extract_with_python_docx(stored_file)
            return f"[{stored_file.name}] (extraction failed: {exc})"

    def _extract_with_python_docx(self, stored_file: StoredFile) -> str:
        """Extract text from a Word document using python-docx."""
        try:
            import docx  # python-docx

            doc = docx.Document(stored_file.path)
            parts: list[str] = []

            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    parts.append(text)

            # Also pull text from tables
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
            logger.warning(
                "python-docx not installed; install it with: pip install python-docx"
            )
            return _fallback.extract(stored_file)
        except Exception as exc:
            logger.warning(
                "python-docx extraction failed for %s: %s", stored_file.name, exc
            )
            return _fallback.extract(stored_file)
