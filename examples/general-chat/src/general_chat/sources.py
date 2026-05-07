"""Per-session source management for the General Chat example."""

from __future__ import annotations

import html
import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from openbench.chat.files import StoredFile

from general_chat.extractor import DoclingContentExtractor

logger = logging.getLogger(__name__)

DEFAULT_MAX_SOURCE_BYTES = 25 * 1024 * 1024

DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".doc", ".pptx", ".ppt"}
EXCEL_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}
EXCEL_EXTENSIONS = {".xlsx", ".xls"}
TEXT_MIME_TYPES = {"application/json"}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json"}
ALLOWED_EXTENSIONS = DOCUMENT_EXTENSIONS | EXCEL_EXTENSIONS | TEXT_EXTENSIONS


@dataclass
class SourceRecord:
    """Stored metadata and extracted content for a NotebookLM-style source."""

    id: str
    session_id: str
    name: str
    kind: str
    mime_type: str
    status: str
    error: str | None
    size_bytes: int
    created_at: str
    url: str | None
    text: str

    def to_dict(self, *, include_text: bool = True) -> dict:
        data = asdict(self)
        data["mimeType"] = data.pop("mime_type")
        data["sessionId"] = data.pop("session_id")
        data["sizeBytes"] = data.pop("size_bytes")
        data["createdAt"] = data.pop("created_at")
        if include_text:
            data["extractedText"] = data["text"]
        else:
            data.pop("text", None)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "SourceRecord":
        normalized = dict(data)
        normalized["mime_type"] = normalized.pop("mimeType", normalized.get("mime_type", ""))
        normalized["session_id"] = normalized.pop("sessionId", normalized.get("session_id", ""))
        normalized["size_bytes"] = normalized.pop("sizeBytes", normalized.get("size_bytes", 0))
        normalized["created_at"] = normalized.pop("createdAt", normalized.get("created_at", ""))
        normalized.pop("extractedText", None)
        return cls(**normalized)

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        name: str,
        kind: str,
        mime_type: str,
        size_bytes: int,
        url: str | None = None,
        text: str = "",
        status: str = "ready",
        error: str | None = None,
    ) -> "SourceRecord":
        return cls(
            id=f"source-{uuid.uuid4().hex[:10]}",
            session_id=session_id,
            name=name,
            kind=kind,
            mime_type=mime_type,
            status=status,
            error=error,
            size_bytes=size_bytes,
            created_at=datetime.now(timezone.utc).isoformat(),
            url=url,
            text=text,
        )


class SourceStore:
    """JSON-backed per-session source store."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve() / "sources"
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self, session_id: str) -> list[SourceRecord]:
        path = self._path(session_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load source store for session %s", session_id)
            return []
        return [SourceRecord.from_dict(item) for item in data.get("sources", [])]

    def add(self, record: SourceRecord) -> SourceRecord:
        records = self.list(record.session_id)
        records.append(record)
        self.save(record.session_id, records)
        return record

    def save(self, session_id: str, records: list[SourceRecord]) -> None:
        path = self._path(session_id)
        payload = {"sessionId": session_id, "sources": [asdict(record) for record in records]}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def delete(self, session_id: str, source_id: str) -> bool:
        records = self.list(session_id)
        next_records = [record for record in records if record.id != source_id]
        if len(next_records) == len(records):
            return False
        self.save(session_id, next_records)
        return True

    def clear(self, session_id: str) -> None:
        path = self._path(session_id)
        if path.exists():
            path.unlink()

    def search(self, session_id: str, query: str, *, limit: int = 20) -> list[dict]:
        needle = query.strip().lower()
        if not needle:
            return []

        results: list[dict] = []
        for record in self.list(session_id):
            if record.status != "ready":
                continue
            haystack = record.text.lower()
            idx = haystack.find(needle)
            if idx < 0 and needle not in record.name.lower():
                continue
            snippet = _snippet(record.text, idx if idx >= 0 else 0, len(needle))
            results.append(
                {
                    "sourceId": record.id,
                    "name": record.name,
                    "kind": record.kind,
                    "snippet": snippet,
                }
            )
            if len(results) >= limit:
                break
        return results

    def _path(self, session_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in session_id)
        return self.root / f"{safe}.json"


class SourceParserRegistry:
    """Routes source parsing by kind, MIME type, and extension."""

    def __init__(self, *, document_extractor: DoclingContentExtractor | None = None):
        self.document_extractor = document_extractor or DoclingContentExtractor()

    def parse_file(self, stored_file: StoredFile) -> str:
        ext = Path(stored_file.name).suffix.lower()
        if stored_file.mime_type in DOCUMENT_MIME_TYPES or ext in DOCUMENT_EXTENSIONS:
            return self._ensure_success(self.document_extractor.extract(stored_file), stored_file.name)
        if stored_file.mime_type in EXCEL_MIME_TYPES or ext in EXCEL_EXTENSIONS:
            return self._parse_excel(stored_file)
        if (
            stored_file.mime_type.startswith("text/")
            or stored_file.mime_type in TEXT_MIME_TYPES
            or ext in TEXT_EXTENSIONS
        ):
            return self._parse_text_file(stored_file)
        raise ValueError(f"Unsupported source type: {ext or stored_file.mime_type}")

    def parse_text(self, text: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Plain text source cannot be empty.")
        return cleaned

    def parse_url(
        self, url: str, *, max_bytes: int = DEFAULT_MAX_SOURCE_BYTES
    ) -> tuple[str, str, int] | tuple[str, str, int, str]:
        normalized = validate_url(url)
        try:
            text = self._parse_url_with_docling(normalized)
            if text.strip():
                return _title_from_text(text) or normalized, text.strip(), len(text.encode("utf-8"))
        except Exception as exc:
            logger.info("Docling URL extraction failed for %s: %s", normalized, exc)

        html_text, content_type = fetch_url_text(normalized, max_bytes=max_bytes)
        text = clean_html_text(html_text)
        if not text.strip():
            raise ValueError("No readable text could be extracted from the website.")
        title = extract_html_title(html_text) or normalized
        return title, text, len(html_text.encode("utf-8")), content_type

    def _parse_url_with_docling(self, url: str) -> str:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(url)
        return result.document.export_to_markdown()

    def _parse_text_file(self, stored_file: StoredFile) -> str:
        path = Path(stored_file.path)
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="latin-1")

    def _parse_excel(self, stored_file: StoredFile) -> str:
        try:
            import pandas as pd
        except ImportError as exc:
            raise ValueError("Install pandas and openpyxl for Excel source support.") from exc

        try:
            sheets = pd.read_excel(stored_file.path, sheet_name=None)
        except Exception as exc:
            raise ValueError(f"Excel extraction failed: {exc}") from exc

        parts: list[str] = []
        for name, df in sheets.items():
            parts.append(f"### Sheet: {name} ({len(df)} rows)")
            if df.empty:
                parts.append("(empty sheet)")
            else:
                parts.append(df.to_markdown(index=False))
        return "\n\n".join(parts).strip()

    @staticmethod
    def _ensure_success(text: str, name: str) -> str:
        lowered = text.lower()
        if "extraction failed:" in lowered or "read failed:" in lowered:
            raise ValueError(text)
        if not text.strip():
            raise ValueError(f"No text content could be extracted from {name}.")
        return text


def max_source_bytes_from_env() -> int:
    raw = os.getenv("GENERAL_CHAT_MAX_SOURCE_BYTES")
    if not raw:
        return DEFAULT_MAX_SOURCE_BYTES
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MAX_SOURCE_BYTES


def validate_file_source(filename: str, mime_type: str, size_bytes: int, *, max_bytes: int) -> None:
    ext = Path(filename).suffix.lower()
    if size_bytes <= 0:
        raise ValueError("Source file is empty.")
    if size_bytes > max_bytes:
        raise ValueError(f"Source file exceeds the {max_bytes} byte limit.")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported source file type: {ext or 'unknown'}")
    if mime_type == "application/octet-stream" and ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported source MIME type: application/octet-stream")


def source_record_from_file(
    *,
    session_id: str,
    stored_file: StoredFile,
    parser: SourceParserRegistry,
    max_bytes: int,
) -> SourceRecord:
    try:
        validate_file_source(
            stored_file.name,
            stored_file.mime_type,
            stored_file.size_bytes,
            max_bytes=max_bytes,
        )
        text = parser.parse_file(stored_file)
        return SourceRecord.create(
            session_id=session_id,
            name=stored_file.name,
            kind=kind_for_file(stored_file.name, stored_file.mime_type),
            mime_type=stored_file.mime_type,
            size_bytes=stored_file.size_bytes,
            url=f"/uploads/{stored_file.id}/{stored_file.name}",
            text=text,
        )
    except Exception as exc:
        return SourceRecord.create(
            session_id=session_id,
            name=stored_file.name,
            kind=kind_for_file(stored_file.name, stored_file.mime_type),
            mime_type=stored_file.mime_type,
            size_bytes=stored_file.size_bytes,
            url=f"/uploads/{stored_file.id}/{stored_file.name}",
            text="",
            status="failed",
            error=str(exc),
        )


def source_record_from_text(*, session_id: str, name: str, text: str, parser: SourceParserRegistry) -> SourceRecord:
    try:
        parsed = parser.parse_text(text)
        return SourceRecord.create(
            session_id=session_id,
            name=name.strip() or "Pasted text",
            kind="text",
            mime_type="text/plain",
            size_bytes=len(parsed.encode("utf-8")),
            text=parsed,
        )
    except Exception as exc:
        return SourceRecord.create(
            session_id=session_id,
            name=name.strip() or "Pasted text",
            kind="text",
            mime_type="text/plain",
            size_bytes=len(text.encode("utf-8")),
            text="",
            status="failed",
            error=str(exc),
        )


def source_record_from_url(
    *,
    session_id: str,
    url: str,
    parser: SourceParserRegistry,
    max_bytes: int,
) -> SourceRecord:
    try:
        parsed = parser.parse_url(url, max_bytes=max_bytes)
        if len(parsed) == 4:
            name, text, size_bytes, mime_type = parsed
        else:
            name, text, size_bytes = parsed
            mime_type = "text/html"
        return SourceRecord.create(
            session_id=session_id,
            name=name,
            kind="url",
            mime_type=mime_type,
            size_bytes=size_bytes,
            url=url,
            text=text,
        )
    except Exception as exc:
        return SourceRecord.create(
            session_id=session_id,
            name=url,
            kind="url",
            mime_type="text/html",
            size_bytes=0,
            url=url,
            text="",
            status="failed",
            error=str(exc),
        )


def kind_for_file(filename: str, mime_type: str) -> str:
    ext = Path(filename).suffix.lower()
    if mime_type in DOCUMENT_MIME_TYPES or ext in DOCUMENT_EXTENSIONS:
        return ext.lstrip(".") or "document"
    if mime_type in EXCEL_MIME_TYPES or ext in EXCEL_EXTENSIONS:
        return "xlsx"
    if mime_type.startswith("text/") or mime_type in TEXT_MIME_TYPES or ext in TEXT_EXTENSIONS:
        return "text"
    return "file"


def validate_url(url: str) -> str:
    value = url.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Website source must be a valid http or https URL.")
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127."):
        raise ValueError("Local URLs are not allowed as website sources.")
    return value


def fetch_url_text(url: str, *, max_bytes: int) -> tuple[str, str]:
    import requests

    response = requests.get(url, timeout=15, headers={"User-Agent": "OpenBench-GeneralChat/0.1"})
    response.raise_for_status()
    content_type = response.headers.get("content-type", "text/html").split(";")[0].strip()
    raw = response.content
    if len(raw) > max_bytes:
        raise ValueError(f"Website response exceeds the {max_bytes} byte limit.")
    response.encoding = response.encoding or "utf-8"
    return response.text, content_type


class _ReadableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
        if tag in {"p", "br", "div", "section", "article", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        if tag in {"p", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)


def clean_html_text(raw_html: str) -> str:
    parser = _ReadableHTMLParser()
    parser.feed(raw_html)
    text = html.unescape(" ".join(parser.parts))
    return re.sub(r"\n\s*\n\s*", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def extract_html_title(raw_html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    title = html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return title or None


def _title_from_text(text: str) -> str | None:
    for line in text.splitlines():
        cleaned = line.strip(" #\t")
        if cleaned:
            return cleaned[:120]
    return None


def _snippet(text: str, idx: int, needle_len: int, *, radius: int = 90) -> str:
    start = max(0, idx - radius)
    end = min(len(text), idx + max(needle_len, 1) + radius)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    if start:
        snippet = f"...{snippet}"
    if end < len(text):
        snippet = f"{snippet}..."
    return snippet
