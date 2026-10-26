"""Tools for the pdf-tools SDK skill.

Read, analyze, manipulate, and generate PDF documents. Wraps:
- ``pypdf`` for reading, metadata, merge, split
- ``pdfplumber`` for table extraction
- ``PDFGenerator`` (reportlab) for PDF creation

All imports are lazy so the skill loads without extras.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from pathlib import Path
from typing import Any

__all__ = [
    "pdf_metadata",
    "read_pdf",
    "read_pdf_page",
    "extract_pdf_tables",
    "merge_pdfs",
    "split_pdf",
    "generate_pdf",
    "PDF_METADATA_SCHEMA",
    "READ_PDF_SCHEMA",
    "READ_PDF_PAGE_SCHEMA",
    "EXTRACT_PDF_TABLES_SCHEMA",
    "MERGE_PDFS_SCHEMA",
    "SPLIT_PDF_SCHEMA",
    "GENERATE_PDF_SCHEMA",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error(message: str, source: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {"error": message}
    if source:
        result["source"] = source
    return result


def _export_dir() -> str | None:
    return os.environ.get("OPENBENCH_EXPORT_DIR") or None


def _url_base() -> str | None:
    base = os.environ.get("OPENBENCH_EXPORT_URL_BASE")
    return base.rstrip("/") if base else None


def _output_path(filename: str) -> Path:
    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".pdf"
    unique = f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"
    target = _export_dir()
    p = Path(target) / unique if target else Path(unique)
    p = p.resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _public_url(path: Path) -> str:
    base = _url_base()
    if base is None:
        return str(path)
    from openbench.utils.download_tokens import sign_download_url

    return sign_download_url(f"{base}/{path.name}")


def _file_item(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    item: dict[str, Any] = {
        "name": path.name,
        "url": _public_url(path),
        "mimeType": "application/pdf",
    }
    if size is not None:
        item["size"] = size
    return item


def _push_render(item: dict[str, Any]) -> None:
    try:
        from openbench.chat.render_queue import push
    except Exception:
        return
    with contextlib.suppress(Exception):
        push(item)


def _push_table(headers: list[str], rows: list[list[str]], title: str = "") -> None:
    item: dict[str, Any] = {"headers": headers, "rows": rows}
    if title:
        item["title"] = title
    _push_render(item)


# ---------------------------------------------------------------------------
# pdf_metadata
# ---------------------------------------------------------------------------


def pdf_metadata(path: str) -> dict[str, Any]:
    """Quick metadata read — title, author, page count, encrypted status.

    Cheap call. Use this FIRST before deciding whether to read full text.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return _error("pypdf required — install openbench[data]", path)

    p = Path(path)
    if not p.exists():
        return _error(f"File not found: {path}", path)

    try:
        reader = PdfReader(p)
    except Exception as e:
        return _error(f"Not a valid PDF: {e}", path)

    encrypted = reader.is_encrypted
    if encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return {
                "source": str(p.resolve()),
                "encrypted": True,
                "page_count": 0,
                "message": "PDF is encrypted — password required",
            }

    meta = reader.metadata or {}
    try:
        size = p.stat().st_size
    except OSError:
        size = None

    return {
        "source": str(p.resolve()),
        "title": getattr(meta, "title", None) or "",
        "author": getattr(meta, "author", None) or "",
        "subject": getattr(meta, "subject", None) or "",
        "creator": getattr(meta, "creator", None) or "",
        "page_count": len(reader.pages),
        "file_size_bytes": size,
        "encrypted": encrypted,
    }


# ---------------------------------------------------------------------------
# read_pdf
# ---------------------------------------------------------------------------


def read_pdf(
    path: str,
    pages: list[int] | None = None,
    max_chars: int = 10000,
) -> dict[str, Any]:
    """Extract text from a PDF. Supports page filtering and truncation.

    Args:
        path: PDF file path.
        pages: 0-indexed page numbers to read. None = all pages.
        max_chars: Truncate output at this many chars (default 10000).
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return _error("pypdf required — install openbench[data]", path)

    p = Path(path)
    if not p.exists():
        return _error(f"File not found: {path}", path)

    try:
        reader = PdfReader(p)
    except Exception as e:
        return _error(f"Not a valid PDF: {e}", path)

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return _error("PDF is encrypted — password required", path)

    total_pages = len(reader.pages)
    target_pages = pages if pages is not None else list(range(total_pages))

    # Validate page numbers
    for pg in target_pages:
        if pg < 0 or pg >= total_pages:
            return _error(f"Page {pg} out of range (0-{total_pages - 1})", path)

    text_parts: list[str] = []
    pages_read: list[int] = []
    total_chars = 0
    truncated = False
    truncated_at_page: int | None = None

    for pg in target_pages:
        page_text = reader.pages[pg].extract_text() or ""
        if max_chars and total_chars + len(page_text) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 0:
                text_parts.append(page_text[:remaining])
                pages_read.append(pg)
            truncated = True
            truncated_at_page = pg
            break
        text_parts.append(page_text)
        pages_read.append(pg)
        total_chars += len(page_text)

    text = "\n\n".join(text_parts)
    result: dict[str, Any] = {
        "source": str(p.resolve()),
        "text": text,
        "page_count": total_pages,
        "pages_read": pages_read,
        "truncated": truncated,
    }
    if truncated:
        result["truncated_at_page"] = truncated_at_page
        result["message"] = (
            f"Truncated at {max_chars} chars (page {truncated_at_page} of {total_pages}). "
            "Use read_pdf_page for specific pages."
        )
    return result


# ---------------------------------------------------------------------------
# read_pdf_page
# ---------------------------------------------------------------------------


def read_pdf_page(path: str, page: int) -> dict[str, Any]:
    """Extract text from a single PDF page.

    Args:
        path: PDF file path.
        page: 0-indexed page number.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return _error("pypdf required — install openbench[data]", path)

    p = Path(path)
    if not p.exists():
        return _error(f"File not found: {path}", path)

    try:
        reader = PdfReader(p)
    except Exception as e:
        return _error(f"Not a valid PDF: {e}", path)

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return _error("PDF is encrypted — password required", path)

    total = len(reader.pages)
    if page < 0 or page >= total:
        return _error(f"Page {page} out of range (0-{total - 1})", path)

    text = reader.pages[page].extract_text() or ""
    return {
        "source": str(p.resolve()),
        "page": page,
        "page_count": total,
        "text": text,
    }


# ---------------------------------------------------------------------------
# extract_pdf_tables
# ---------------------------------------------------------------------------


def extract_pdf_tables(path: str, page: int | None = None) -> dict[str, Any]:
    """Extract tables from a PDF using pdfplumber.

    Pushes each table to the render queue as an ObTable component.

    Args:
        path: PDF file path.
        page: 0-indexed page to extract from. None = all pages.
    """
    try:
        import pdfplumber
    except ImportError:
        return _error("pdfplumber required — pip install pdfplumber", path)

    p = Path(path)
    if not p.exists():
        return _error(f"File not found: {path}", path)

    try:
        pdf = pdfplumber.open(p)
    except Exception as e:
        return _error(f"Failed to open PDF: {e}", path)

    tables_out: list[dict[str, Any]] = []
    target_pages = [pdf.pages[page]] if page is not None and page < len(pdf.pages) else pdf.pages

    for pg in target_pages:
        page_tables = pg.extract_tables()
        if not page_tables:
            continue
        for idx, table in enumerate(page_tables):
            if not table or len(table) < 2:
                continue
            # First row as headers, rest as data
            headers = [str(c or "") for c in table[0]]
            rows = [[str(c or "") for c in row] for row in table[1:]]
            table_entry = {
                "page": pg.page_number - 1,  # pdfplumber is 1-indexed
                "table_index": idx,
                "headers": headers,
                "rows": rows,
            }
            tables_out.append(table_entry)
            # Push to render queue for ObTable display
            title = f"Table (page {pg.page_number})"
            if len(page_tables) > 1:
                title += f" #{idx + 1}"
            _push_table(headers, rows, title)

    pdf.close()

    result: dict[str, Any] = {
        "source": str(p.resolve()),
        "tables": tables_out,
        "table_count": len(tables_out),
    }
    if not tables_out:
        result["message"] = (
            "No tables detected. The PDF may use invisible borders or be a scanned image."
        )
    return result


# ---------------------------------------------------------------------------
# merge_pdfs
# ---------------------------------------------------------------------------


def merge_pdfs(paths: list[str], filename: str = "merged.pdf") -> dict[str, Any]:
    """Merge multiple PDF files into one.

    Args:
        paths: List of PDF file paths to merge (in order).
        filename: Output filename.
    """
    try:
        from pypdf import PdfWriter
    except ImportError:
        return _error("pypdf required — install openbench[data]")

    if not isinstance(paths, list) or len(paths) < 2:
        return _error("`paths` must be a list of 2+ PDF file paths")

    for fp in paths:
        if not Path(fp).exists():
            return _error(f"File not found: {fp}")

    try:
        writer = PdfWriter()
        total_pages = 0
        for fp in paths:
            writer.append(fp)
            total_pages += len(writer.pages) - total_pages  # track pages added

        out_path = _output_path(filename)
        with open(out_path, "wb") as f:
            writer.write(f)
    except Exception as e:
        return _error(f"Merge failed: {e}")

    item = _file_item(out_path)
    item["page_count"] = len(writer.pages)
    item["source_files"] = [Path(fp).name for fp in paths]
    _push_render(item)
    return item


# ---------------------------------------------------------------------------
# split_pdf
# ---------------------------------------------------------------------------


def split_pdf(
    path: str,
    pages: list[int],
    filename: str = "split.pdf",
) -> dict[str, Any]:
    """Extract specific pages from a PDF into a new file.

    Args:
        path: Source PDF file path.
        pages: 0-indexed page numbers to extract.
        filename: Output filename.
    """
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return _error("pypdf required — install openbench[data]", path)

    p = Path(path)
    if not p.exists():
        return _error(f"File not found: {path}", path)
    if not isinstance(pages, list) or not pages:
        return _error("`pages` must be a non-empty list of page numbers", path)

    try:
        reader = PdfReader(p)
    except Exception as e:
        return _error(f"Not a valid PDF: {e}", path)

    total = len(reader.pages)
    for pg in pages:
        if pg < 0 or pg >= total:
            return _error(f"Page {pg} out of range (0-{total - 1})", path)

    try:
        writer = PdfWriter()
        for pg in pages:
            writer.add_page(reader.pages[pg])
        out_path = _output_path(filename)
        with open(out_path, "wb") as f:
            writer.write(f)
    except Exception as e:
        return _error(f"Split failed: {e}", path)

    item = _file_item(out_path)
    item["page_count"] = len(pages)
    item["pages_extracted"] = pages
    _push_render(item)
    return item


# ---------------------------------------------------------------------------
# generate_pdf
# ---------------------------------------------------------------------------


def generate_pdf(
    title: str,
    sections: list[dict[str, Any]],
    filename: str = "report.pdf",
    author: str = "",
) -> dict[str, Any]:
    """Create a PDF report from structured sections.

    Section types:
        {"type": "heading", "content": "Section Title"}
        {"type": "text", "content": "Paragraph text..."}
        {"type": "table", "headers": [...], "rows": [[...], ...]}

    Args:
        title: Report title (appears on first page).
        sections: Ordered list of section dicts.
        filename: Output filename.
        author: Optional author name for metadata.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        return _error("reportlab required — install openbench[output]")

    if not isinstance(sections, list) or not sections:
        return _error("`sections` must be a non-empty list")

    out_path = _output_path(filename)

    try:
        doc = SimpleDocTemplate(
            str(out_path),
            pagesize=A4,
            title=title,
            author=author,
        )
        styles = getSampleStyleSheet()
        heading_style = ParagraphStyle(
            "SkillHeading",
            parent=styles["Heading1"],
            fontSize=16,
            spaceAfter=12,
        )
        subheading_style = ParagraphStyle(
            "SkillSubHeading",
            parent=styles["Heading2"],
            fontSize=13,
            spaceAfter=8,
        )
        body_style = styles["BodyText"]

        elements: list[Any] = []
        # Title
        elements.append(Paragraph(title, heading_style))
        elements.append(Spacer(1, 12))

        for section in sections:
            if not isinstance(section, dict):
                continue
            stype = section.get("type", "text")
            content = section.get("content", "")

            if stype == "heading":
                elements.append(Paragraph(str(content), subheading_style))
                elements.append(Spacer(1, 6))
            elif stype == "text":
                # Sanitize for reportlab — replace < > that aren't tags
                safe = str(content).replace("&", "&amp;")
                elements.append(Paragraph(safe, body_style))
                elements.append(Spacer(1, 8))
            elif stype == "table":
                headers = section.get("headers", [])
                rows = section.get("rows", [])
                if headers and rows:
                    table_data = [headers, *rows]
                    t = Table(table_data)
                    t.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE", (0, 0), (-1, -1), 9),
                                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                            ]
                        )
                    )
                    elements.append(t)
                    elements.append(Spacer(1, 12))

        doc.build(elements)
    except Exception as e:
        return _error(f"PDF generation failed: {e}")

    item = _file_item(out_path)
    item["section_count"] = len(sections)
    _push_render(item)
    return item


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


PDF_METADATA_SCHEMA = _schema(
    "pdf_metadata",
    "Quick metadata read from a PDF — title, author, page count, file size, "
    "encrypted status. Use this FIRST before reading full text. Cheap call.",
    {"path": {"type": "string", "description": "PDF file path"}},
    ["path"],
)

READ_PDF_SCHEMA = _schema(
    "read_pdf",
    "Extract text from a PDF with optional page filtering and truncation. "
    "For large PDFs (>20 pages), pass specific page numbers to avoid "
    "blowing the context window.",
    {
        "path": {"type": "string"},
        "pages": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "0-indexed page numbers to read. Omit for all pages.",
        },
        "max_chars": {
            "type": "integer",
            "description": "Truncate at this many chars (default 10000).",
        },
    },
    ["path"],
)

READ_PDF_PAGE_SCHEMA = _schema(
    "read_pdf_page",
    "Extract text from a single PDF page. Use after pdf_metadata to read "
    "specific pages of interest without loading the whole document.",
    {
        "path": {"type": "string"},
        "page": {"type": "integer", "description": "0-indexed page number"},
    },
    ["path", "page"],
)

EXTRACT_PDF_TABLES_SCHEMA = _schema(
    "extract_pdf_tables",
    "Detect and extract tables from a PDF. Each table appears as an ObTable "
    "in the chat. Works best on PDFs with visible grid lines. Returns empty "
    "for scanned/image PDFs.",
    {
        "path": {"type": "string"},
        "page": {
            "type": "integer",
            "description": "0-indexed page to extract from. Omit for all pages.",
        },
    },
    ["path"],
)

MERGE_PDFS_SCHEMA = _schema(
    "merge_pdfs",
    "Combine multiple PDF files into one document, in the order given, and "
    "return a downloadable file card. Use when the user asks to merge / "
    "combine / join PDFs — Indonesian 'gabungkan pdf', 'satukan pdf'.",
    {
        "paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of PDF file paths to merge (in order).",
        },
        "filename": {"type": "string", "description": "Output filename (default 'merged.pdf')"},
    },
    ["paths"],
)

SPLIT_PDF_SCHEMA = _schema(
    "split_pdf",
    "Extract specific pages from a PDF into a new file and return a "
    "downloadable file card with only the selected pages. Use when the "
    "user asks to split / extract pages — Indonesian 'pisahkan pdf', "
    "'ambil halaman'.",
    {
        "path": {"type": "string"},
        "pages": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "0-indexed page numbers to extract.",
        },
        "filename": {"type": "string", "description": "Output filename (default 'split.pdf')"},
    },
    ["path", "pages"],
)

GENERATE_PDF_SCHEMA = _schema(
    "generate_pdf",
    "Create a PDF report from structured sections and return a download "
    "card. Use whenever the user asks for a PDF deliverable, in any "
    "language — English 'export as pdf', 'download a pdf report', 'save "
    "this as pdf'; Indonesian 'unduh sebagai pdf', 'buatkan laporan pdf', "
    "'ekspor ke pdf', 'berkas pdf'. When a file is requested, replying "
    "with markdown alone is not enough — call this tool. For spreadsheets "
    "use export_to_excel; for markdown/text use generate_markdown.",
    {
        "title": {"type": "string", "description": "Report title"},
        "sections": {
            "type": "array",
            "description": "Ordered list of report sections.",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["heading", "text", "table"],
                        "description": "Section kind.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Heading or paragraph text. Unused for 'table'.",
                    },
                    "headers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Column headers. Required for 'table'.",
                    },
                    "rows": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}},
                        "description": "Table rows, one array of cell strings per row.",
                    },
                },
                "required": ["type"],
            },
        },
        "filename": {"type": "string", "description": "Output filename (default 'report.pdf')"},
        "author": {"type": "string", "description": "Author name for PDF metadata"},
    },
    ["title", "sections"],
)
