"""Per-session source management and discovery for the General Chat example."""

from __future__ import annotations

import hashlib
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
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from general_chat.extractor import DoclingContentExtractor

if TYPE_CHECKING:
    from openbench.chat.files import StoredFile

logger = logging.getLogger(__name__)

DEFAULT_MAX_SOURCE_BYTES = 25 * 1024 * 1024
DEFAULT_DISCOVERY_LIMIT = 8
DEFAULT_DISCOVERY_TIMEOUT = 15
DEFAULT_DISCOVERY_CONNECT_TIMEOUT = 5
DEFAULT_DISCOVERY_RETRIES = 2
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "application/epub+zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
}
DOCUMENT_EXTENSIONS = {".pdf", ".epub", ".docx", ".doc", ".pptx", ".ppt"}

EXCEL_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}
EXCEL_EXTENSIONS = {".xlsx", ".xls"}

TEXT_MIME_TYPES = {"application/json"}
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json"}

IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/heic",
    "image/heif",
    "image/tiff",
    "image/bmp",
    "image/svg+xml",
}
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".heic",
    ".heif",
    ".tiff",
    ".tif",
    ".bmp",
    ".svg",
}
IMAGE_SEARCH_CONTAINER_UPLOAD_ROOT = "/general-chat/uploads"
UPLOAD_METADATA_KEYS = {
    "imageSearchPath",
    "samSegmentationPath",
    "imageSearchPreviewUrl",
}
_UPLOAD_FILE_ID_PATTERN = re.compile(r"(?:^|/)(file-[A-Za-z0-9_-]+)(?:/|$)")

ALLOWED_EXTENSIONS = (
    DOCUMENT_EXTENSIONS | EXCEL_EXTENSIONS | TEXT_EXTENSIONS | IMAGE_EXTENSIONS
)

DUCKDUCKGO_SEARCH_URL = "https://html.duckduckgo.com/html/"
DUCKDUCKGO_RESULT_ANCHOR = "result__a"
DUCKDUCKGO_RESULT_SNIPPET = "result__snippet"


def _without_nul(value: str) -> str:
    return value.replace("\x00", "\uFFFD")


def _sanitize_json_value(value: Any) -> Any:
    """Remove NUL characters that PostgreSQL JSONB cannot store."""
    if isinstance(value, str):
        return _without_nul(value)
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {
            _without_nul(str(key)): _sanitize_json_value(item)
            for key, item in value.items()
        }
    return value


def _source_record_payload(record: SourceRecord) -> dict[str, Any]:
    return _sanitize_json_value(asdict(record))


@dataclass
class ParsedSourceContent:
    """Normalized parsed source payload before persistence."""

    text: str
    metadata: dict[str, Any] | None = None


@dataclass
class SearchDiscoveryResult:
    """Normalized internet discovery result for the frontend."""

    id: str
    title: str
    url: str
    domain: str
    snippet: str
    favicon_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "domain": self.domain,
            "snippet": self.snippet,
            "faviconUrl": self.favicon_url,
        }


@dataclass
class SearchProviderFailure:
    """Normalized provider failure details for logging and fallback."""

    provider: str
    category: str
    message: str
    exception_class: str


@dataclass
class SearchProviderResponse:
    """Provider search outcome: either results or a normalized failure."""

    provider: str
    results: list[SearchDiscoveryResult]
    failure: SearchProviderFailure | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None


@dataclass
class SearchDiscoveryResponse:
    """Adapter-level response used by the API layer."""

    query: str
    results: list[SearchDiscoveryResult]
    warning: str | None = None
    failed_providers: list[SearchProviderFailure] | None = None


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
    metadata: dict[str, Any] | None = None

    def to_dict(self, *, include_text: bool = True) -> dict[str, Any]:
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
    def from_dict(cls, data: dict[str, Any]) -> SourceRecord:
        normalized = dict(data)
        normalized["mime_type"] = normalized.pop(
            "mimeType", normalized.get("mime_type", "")
        )
        normalized["session_id"] = normalized.pop(
            "sessionId", normalized.get("session_id", "")
        )
        normalized["size_bytes"] = normalized.pop(
            "sizeBytes", normalized.get("size_bytes", 0)
        )
        normalized["created_at"] = normalized.pop(
            "createdAt", normalized.get("created_at", "")
        )
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
        metadata: dict[str, Any] | None = None,
    ) -> SourceRecord:
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
            text=_without_nul(text),
            metadata=_sanitize_json_value(metadata),
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

    def upsert(self, record: SourceRecord) -> SourceRecord:
        records = self.list(record.session_id)
        replaced = False
        for i, existing in enumerate(records):
            if existing.id == record.id:
                records[i] = record
                replaced = True
                break
        if not replaced:
            records.append(record)
        self.save(record.session_id, records)
        return record

    def save(self, session_id: str, records: list[SourceRecord]) -> None:
        path = self._path(session_id)
        payload = {
            "sessionId": session_id,
            "sources": [_source_record_payload(record) for record in records],
        }
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

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

    def find_by_upload_file_id(
        self,
        file_id: str,
        *,
        session_id: str | None = None,
    ) -> SourceRecord | None:
        records = self.list(session_id) if session_id else self._list_all()
        for record in records:
            if file_id in upload_file_ids_for_source(record):
                return record
            metadata = record.metadata or {}
            if metadata.get("fileId") == file_id:
                return record
        return None

    def search(self, session_id: str, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        if not needle:
            return []

        results: list[dict[str, Any]] = []
        for record in self.list(session_id):
            if record.status != "ready":
                continue
            haystack = record.text.lower()
            idx = haystack.find(needle)
            if idx < 0 and needle not in record.name.lower():
                continue
            results.append(
                {
                    "sourceId": record.id,
                    "name": record.name,
                    "kind": record.kind,
                    "snippet": _snippet(record.text, max(idx, 0), len(needle)),
                }
            )
            if len(results) >= limit:
                break
        return results

    def _path(self, session_id: str) -> Path:
        safe = "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in session_id
        )
        return self.root / f"{safe}.json"

    def _list_all(self) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        for path in self.root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            records.extend(SourceRecord.from_dict(item) for item in data.get("sources", []))
        return records


class PostgresSourceStore:
    """PostgreSQL-backed per-session source store for GCE deployments."""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        conn: Any | None = None,
        table_name: str = "openbench_sources",
    ):
        if conn is None and not database_url:
            raise ValueError("Either database_url= or conn= must be provided.")
        self.database_url = database_url
        self._conn = conn
        self.table_name = table_name
        self._init_db()

    def list(self, session_id: str) -> list[SourceRecord]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT data FROM {self.table_name}
                WHERE session_id = %s
                ORDER BY created_at
                """,
                (session_id,),
            )
            rows = cur.fetchall()
        return [self._record_from_data(row[0]) for row in rows]

    def add(self, record: SourceRecord) -> SourceRecord:
        return self.upsert(record)

    def upsert(self, record: SourceRecord) -> SourceRecord:
        payload = json.dumps(_source_record_payload(record), ensure_ascii=False)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.table_name}
                        (session_id, source_id, status, file_id, created_at, updated_at, data)
                    VALUES (%s, %s, %s, %s, %s, now(), %s::jsonb)
                    ON CONFLICT(session_id, source_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        file_id = EXCLUDED.file_id,
                        updated_at = now(),
                        data = EXCLUDED.data
                    """,
                    (
                        record.session_id,
                        record.id,
                        record.status,
                        self._file_id_for(record),
                        record.created_at,
                        payload,
                    ),
                )
            conn.commit()
        return record

    def save(self, session_id: str, records: list[SourceRecord]) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self.table_name} WHERE session_id = %s",
                    (session_id,),
                )
                for record in records:
                    payload = json.dumps(_source_record_payload(record), ensure_ascii=False)
                    cur.execute(
                        f"""
                        INSERT INTO {self.table_name}
                            (session_id, source_id, status, file_id, created_at, updated_at, data)
                        VALUES (%s, %s, %s, %s, %s, now(), %s::jsonb)
                        """,
                        (
                            record.session_id,
                            record.id,
                            record.status,
                            self._file_id_for(record),
                            record.created_at,
                            payload,
                        ),
                    )
            conn.commit()

    def delete(self, session_id: str, source_id: str) -> bool:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    DELETE FROM {self.table_name}
                    WHERE session_id = %s AND source_id = %s
                    """,
                    (session_id, source_id),
                )
                rowcount = cur.rowcount
            conn.commit()
        return bool(rowcount)

    def clear(self, session_id: str) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self.table_name} WHERE session_id = %s",
                    (session_id,),
                )
            conn.commit()

    def search(self, session_id: str, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        if not needle:
            return []
        results: list[dict[str, Any]] = []
        for record in self.list(session_id):
            if record.status != "ready":
                continue
            haystack = record.text.lower()
            idx = haystack.find(needle)
            if idx < 0 and needle not in record.name.lower():
                continue
            results.append(
                {
                    "sourceId": record.id,
                    "name": record.name,
                    "kind": record.kind,
                    "snippet": _snippet(record.text, max(idx, 0), len(needle)),
                }
            )
            if len(results) >= limit:
                break
        return results

    def find_by_upload_file_id(
        self,
        file_id: str,
        *,
        session_id: str | None = None,
    ) -> SourceRecord | None:
        with self._connection() as conn, conn.cursor() as cur:
            if session_id:
                cur.execute(
                    f"""
                    SELECT data FROM {self.table_name}
                    WHERE session_id = %s AND file_id = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (session_id, file_id),
                )
            else:
                cur.execute(
                    f"""
                    SELECT data FROM {self.table_name}
                    WHERE file_id = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (file_id,),
                )
            row = cur.fetchone()
        return self._record_from_data(row[0]) if row else None

    def _init_db(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        session_id TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        file_id TEXT,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        data JSONB NOT NULL,
                        PRIMARY KEY (session_id, source_id)
                    )
                    """
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_file "
                    f"ON {self.table_name} (file_id)"
                )
                cur.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_session "
                    f"ON {self.table_name} (session_id, updated_at DESC)"
                )
            conn.commit()

    def _connection(self):
        if self._conn is not None:
            return _ExternalConnection(self._conn)
        try:
            import psycopg
        except ImportError as exc:
            raise ImportError(
                "PostgresSourceStore requires psycopg. Install openbench[gcp]."
            ) from exc
        return psycopg.connect(self.database_url)

    @staticmethod
    def _file_id_for(record: SourceRecord) -> str | None:
        metadata = record.metadata or {}
        file_id = metadata.get("fileId")
        if isinstance(file_id, str):
            return file_id
        ids = upload_file_ids_for_source(record)
        return next(iter(ids), None)

    @staticmethod
    def _record_from_data(data: Any) -> SourceRecord:
        if isinstance(data, str):
            data = json.loads(data)
        return SourceRecord.from_dict(data)


class _ExternalConnection:
    def __init__(self, conn: Any):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def build_source_store(root: str | Path):
    database_url = os.getenv("GENERAL_CHAT_DATABASE_URL")
    if database_url:
        return PostgresSourceStore(database_url)
    return SourceStore(root)


class SourceParserRegistry:
    """Routes source parsing by kind, MIME type, and extension."""

    def __init__(self, *, document_extractor: DoclingContentExtractor | None = None):
        self.document_extractor = document_extractor or DoclingContentExtractor()

    def parse_file(self, stored_file: StoredFile) -> ParsedSourceContent:
        ext = Path(stored_file.name).suffix.lower()
        if stored_file.mime_type in DOCUMENT_MIME_TYPES or ext in DOCUMENT_EXTENSIONS:
            text = self._ensure_success(
                self.document_extractor.extract(stored_file),
                stored_file.name,
            )
            return ParsedSourceContent(text=text)
        if stored_file.mime_type in EXCEL_MIME_TYPES or ext in EXCEL_EXTENSIONS:
            return ParsedSourceContent(text=self._parse_excel(stored_file))
        if stored_file.mime_type in IMAGE_MIME_TYPES or ext in IMAGE_EXTENSIONS:
            return self._parse_image(stored_file)
        if (
            stored_file.mime_type.startswith("text/")
            or stored_file.mime_type in TEXT_MIME_TYPES
            or ext in TEXT_EXTENSIONS
        ):
            return ParsedSourceContent(text=self._parse_text_file(stored_file))
        raise ValueError(f"Unsupported source type: {ext or stored_file.mime_type}")

    def parse_text(self, text: str) -> ParsedSourceContent:
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Plain text source cannot be empty.")
        return ParsedSourceContent(text=cleaned)

    def parse_url(
        self, url: str, *, max_bytes: int = DEFAULT_MAX_SOURCE_BYTES
    ) -> tuple[str, ParsedSourceContent, int, str]:
        normalized = validate_url(url)
        try:
            text = self._parse_url_with_docling(normalized)
            if text.strip():
                return (
                    _title_from_text(text) or normalized,
                    ParsedSourceContent(text=text.strip()),
                    len(text.encode("utf-8")),
                    "text/markdown",
                )
        except Exception as exc:
            logger.info("Docling URL extraction failed for %s: %s", normalized, exc)

        html_text, content_type = fetch_url_text(normalized, max_bytes=max_bytes)
        text = clean_html_text(html_text)
        if not text.strip():
            raise ValueError("No readable text could be extracted from the website.")
        title = extract_html_title(html_text) or normalized
        return (
            title,
            ParsedSourceContent(text=text),
            len(html_text.encode("utf-8")),
            content_type,
        )

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
            raise ValueError(
                "Install pandas and openpyxl for Excel source support."
            ) from exc

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

    def _parse_image(self, stored_file: StoredFile) -> ParsedSourceContent:
        image_data = self.document_extractor.extract_image(stored_file)
        search_text = str(image_data.get("search_text", "")).strip()
        if not search_text:
            raise ValueError(f"No searchable content could be extracted from {stored_file.name}.")
        metadata = dict(image_data.get("metadata") or {})
        metadata["description"] = image_data.get("description", "")
        metadata["ocrText"] = image_data.get("ocr_text", "")
        return ParsedSourceContent(text=search_text, metadata=metadata)

    @staticmethod
    def _ensure_success(text: str, name: str) -> str:
        lowered = text.lower()
        if "extraction failed:" in lowered or "read failed:" in lowered:
            raise ValueError(text)
        if not text.strip():
            raise ValueError(f"No text content could be extracted from {name}.")
        return text


class BaseSearchDiscoveryProvider:
    """Base class for internet source discovery."""

    provider_name = "base"

    def search(
        self, query: str, *, limit: int = DEFAULT_DISCOVERY_LIMIT
    ) -> SearchProviderResponse:
        raise NotImplementedError


class SearchHTTPTransport:
    """Shared HTTP transport for API-backed discovery providers."""

    def __init__(
        self,
        *,
        connect_timeout: int = DEFAULT_DISCOVERY_CONNECT_TIMEOUT,
        read_timeout: int = DEFAULT_DISCOVERY_TIMEOUT,
        retries: int = DEFAULT_DISCOVERY_RETRIES,
    ):
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util import Retry

        self._session = requests.Session()
        self._timeout = (connect_timeout, read_timeout)
        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            allowed_methods=frozenset({"GET", "POST"}),
            status_forcelist=(429, 500, 502, 503, 504),
            backoff_factor=0.5,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        return self._session.get(
            url,
            params=params,
            timeout=self._timeout,
            headers=headers,
        )

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        return self._session.post(
            url,
            json=json,
            timeout=self._timeout,
            headers=headers,
        )


def _log_provider_failure(
    *,
    provider: str,
    query: str,
    category: str,
    exc: Exception | None,
    exception_class: str,
    message: str,
    fallback_attempted: bool,
) -> None:
    logger.warning(
        "Search discovery provider request failed",
        extra={
            "provider": provider,
            "query": query,
            "failure_category": category,
            "exception_class": exception_class,
            "failure_message": message,
            "fallback_attempted": fallback_attempted,
        },
        exc_info=exc is not None,
    )


def _provider_failure_response(
    *,
    provider: str,
    query: str,
    category: str,
    message: str,
    exception_class: str,
    fallback_attempted: bool,
    exc: Exception | None = None,
) -> SearchProviderResponse:
    _log_provider_failure(
        provider=provider,
        query=query,
        category=category,
        exc=exc,
        exception_class=exception_class,
        message=message,
        fallback_attempted=fallback_attempted,
    )
    return SearchProviderResponse(
        provider=provider,
        results=[],
        failure=SearchProviderFailure(
            provider=provider,
            category=category,
            message=message,
            exception_class=exception_class,
        ),
    )


class DuckDuckGoSearchDiscoveryProvider(BaseSearchDiscoveryProvider):
    """Provider-free HTML search result retrieval via DuckDuckGo."""

    provider_name = "duckduckgo"

    def __init__(self, transport: SearchHTTPTransport | None = None):
        self._transport = transport or SearchHTTPTransport()

    def search(
        self, query: str, *, limit: int = DEFAULT_DISCOVERY_LIMIT
    ) -> SearchProviderResponse:
        import requests

        try:
            response = self._transport.get(
                DUCKDUCKGO_SEARCH_URL,
                params={"q": query},
                headers={"User-Agent": "OpenBench-GeneralChat/0.1"},
            )
            response.raise_for_status()
            parser = _DuckDuckGoResultsParser(limit=limit)
            parser.feed(response.text)
            return SearchProviderResponse(provider=self.provider_name, results=parser.results)
        except requests.exceptions.SSLError as exc:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="ssl",
                message=str(exc),
                exception_class=exc.__class__.__name__,
                fallback_attempted=True,
                exc=exc,
            )
        except requests.exceptions.Timeout as exc:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="timeout",
                message=str(exc),
                exception_class=exc.__class__.__name__,
                fallback_attempted=True,
                exc=exc,
            )
        except requests.exceptions.ConnectionError as exc:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="network",
                message=str(exc),
                exception_class=exc.__class__.__name__,
                fallback_attempted=True,
                exc=exc,
            )
        except requests.exceptions.RequestException as exc:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="http",
                message=str(exc),
                exception_class=exc.__class__.__name__,
                fallback_attempted=True,
                exc=exc,
            )
        except Exception as exc:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="parse",
                message=str(exc),
                exception_class=exc.__class__.__name__,
                fallback_attempted=True,
                exc=exc,
            )


class TavilySearchDiscoveryProvider(BaseSearchDiscoveryProvider):
    """Official Tavily API provider for source discovery."""

    provider_name = "tavily"

    def __init__(
        self,
        transport: SearchHTTPTransport | None = None,
        api_key: str | None = None,
    ):
        self._transport = transport or SearchHTTPTransport()
        self._api_key = api_key or os.getenv("TAVILY_API_KEY", "").strip()

    def search(
        self, query: str, *, limit: int = DEFAULT_DISCOVERY_LIMIT
    ) -> SearchProviderResponse:
        import requests

        if not self._api_key:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="config",
                message="Tavily search is not configured. Set TAVILY_API_KEY.",
                exception_class="MissingAPIKey",
                fallback_attempted=True,
            )

        try:
            response = self._transport.post(
                TAVILY_SEARCH_URL,
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": limit,
                    "search_depth": "basic",
                    "include_answer": False,
                    "include_images": False,
                    "include_raw_content": False,
                },
                headers={"Content-Type": "application/json"},
            )
        except requests.exceptions.SSLError as exc:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="ssl",
                message=str(exc),
                exception_class=exc.__class__.__name__,
                fallback_attempted=True,
                exc=exc,
            )
        except requests.exceptions.Timeout as exc:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="timeout",
                message=str(exc),
                exception_class=exc.__class__.__name__,
                fallback_attempted=True,
                exc=exc,
            )
        except requests.exceptions.ConnectionError as exc:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="network",
                message=str(exc),
                exception_class=exc.__class__.__name__,
                fallback_attempted=True,
                exc=exc,
            )
        except requests.exceptions.RequestException as exc:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="http",
                message=str(exc),
                exception_class=exc.__class__.__name__,
                fallback_attempted=True,
                exc=exc,
            )

        if response.status_code in {401, 403}:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="auth",
                message="Tavily credentials are invalid or unauthorized.",
                exception_class="HTTPError",
                fallback_attempted=True,
            )
        if response.status_code == 429:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="rate_limit",
                message="Tavily rate limit exceeded.",
                exception_class="HTTPError",
                fallback_attempted=True,
            )
        if response.status_code >= 400:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="http",
                message=f"Tavily request failed with status {response.status_code}.",
                exception_class="HTTPError",
                fallback_attempted=True,
            )

        try:
            payload = response.json()
        except Exception as exc:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="parse",
                message=str(exc),
                exception_class=exc.__class__.__name__,
                fallback_attempted=True,
                exc=exc,
            )

        results = [
            SearchDiscoveryResult(
                id=_discovery_result_id(url),
                title=str(item.get("title") or url),
                url=url,
                domain=_domain_label(url),
                snippet=_clean_inline_text(str(item.get("content") or "")),
                favicon_url=_favicon_url(url),
            )
            for item in payload.get("results", [])
            for url in [str(item.get("url") or "").strip()]
            if url
        ]
        return SearchProviderResponse(provider=self.provider_name, results=results)


class GroundedSearchDiscoveryProvider(BaseSearchDiscoveryProvider):
    """Optional provider-backed discovery using grounded search citations."""

    provider_name = "grounded"

    def search(
        self, query: str, *, limit: int = DEFAULT_DISCOVERY_LIMIT
    ) -> SearchProviderResponse:
        try:
            from openbench.data.sources.grounded_search import GroundedSearchSource

            source = GroundedSearchSource(query=query, provider="gemini")
            raw = source.extract()
            results: list[SearchDiscoveryResult] = []
            seen: set[str] = set()
            for item in raw.metadata.get("sources", []):
                url = str(item.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                title = str(item.get("title") or _domain_label(url))
                try:
                    html_text, _content_type = fetch_url_text(
                        url,
                        max_bytes=DEFAULT_MAX_SOURCE_BYTES,
                    )
                    snippet = clean_html_text(html_text)
                    page_title = extract_html_title(html_text)
                    if page_title:
                        title = page_title
                except Exception:
                    snippet = ""
                results.append(
                    SearchDiscoveryResult(
                        id=_discovery_result_id(url),
                        title=title,
                        url=url,
                        domain=_domain_label(url),
                        snippet=_snippet(snippet or title, 0, 0),
                        favicon_url=_favicon_url(url),
                    )
                )
                if len(results) >= limit:
                    break
            return SearchProviderResponse(provider=self.provider_name, results=results)
        except Exception as exc:
            return _provider_failure_response(
                provider=self.provider_name,
                query=query,
                category="provider",
                message=str(exc),
                exception_class=exc.__class__.__name__,
                fallback_attempted=True,
                exc=exc,
            )


class SearchDiscoveryAdapter:
    """Hybrid discovery adapter with provider-backed optional fallback."""

    def __init__(self, provider_name: str | None = None):
        requested = (
            provider_name
            or os.getenv("GENERAL_CHAT_DISCOVERY_PROVIDER")
            or "tavily"
        ).strip().lower()
        self.provider_name = requested
        self._cache: dict[str, list[SearchDiscoveryResult]] = {}
        self._providers = self._build_provider_chain(requested)

    def search(
        self, query: str, *, limit: int = DEFAULT_DISCOVERY_LIMIT
    ) -> SearchDiscoveryResponse:
        cleaned = query.strip()
        if not cleaned:
            return SearchDiscoveryResponse(query="", results=[])
        cache_key = f"{cleaned.lower()}::{limit}"
        if cache_key in self._cache:
            return SearchDiscoveryResponse(
                query=cleaned,
                results=self._cache[cache_key],
            )

        failures: list[SearchProviderFailure] = []
        for index, provider in enumerate(self._providers):
            response = provider.search(cleaned, limit=limit)
            if response.ok:
                self._cache[cache_key] = response.results
                if failures:
                    logger.info(
                        "Search discovery fallback succeeded",
                        extra={
                            "provider": provider.provider_name,
                            "query": cleaned,
                            "failed_providers": [failure.provider for failure in failures],
                            "fallback_attempted": True,
                        },
                    )
                return SearchDiscoveryResponse(
                    query=cleaned,
                    results=response.results,
                    failed_providers=failures or None,
                )
            assert response.failure is not None
            failures.append(response.failure)
            logger.info(
                "Search discovery provider failed; trying fallback",
                extra={
                    "provider": provider.provider_name,
                    "query": cleaned,
                    "failure_category": response.failure.category,
                    "failure_exception_class": response.failure.exception_class,
                    "fallback_attempted": index < len(self._providers) - 1,
                },
            )

        logger.warning(
            "All search discovery providers failed",
            extra={
                "query": cleaned,
                "failed_providers": [failure.provider for failure in failures],
                "failure_categories": [failure.category for failure in failures],
                "fallback_attempted": len(self._providers) > 1,
            },
        )
        warning = self._warning_from_failures(failures)
        return SearchDiscoveryResponse(
            query=cleaned,
            results=[],
            warning=warning,
            failed_providers=failures or None,
        )

    def _build_provider_chain(self, provider_name: str) -> list[BaseSearchDiscoveryProvider]:
        configured = os.getenv("GENERAL_CHAT_DISCOVERY_PROVIDERS", "").strip()
        if configured:
            names = [item.strip().lower() for item in configured.split(",") if item.strip()]
        elif provider_name in {"grounded", "gemini"}:
            names = ["grounded", "tavily"]
        else:
            names = ["tavily"]

        providers: list[BaseSearchDiscoveryProvider] = []
        seen: set[str] = set()
        for name in names:
            if name in seen:
                continue
            provider = self._provider_from_name(name)
            if provider is None:
                continue
            seen.add(name)
            providers.append(provider)

        if not providers:
            providers.append(TavilySearchDiscoveryProvider())
        return providers

    def _provider_from_name(self, provider_name: str) -> BaseSearchDiscoveryProvider | None:
        normalized = provider_name.strip().lower()
        if normalized == "tavily":
            return TavilySearchDiscoveryProvider()
        if normalized in {"grounded", "gemini"}:
            if os.getenv("GOOGLE_API_KEY"):
                return GroundedSearchDiscoveryProvider()
            logger.info(
                "Skipping grounded search discovery provider; GOOGLE_API_KEY not configured",
                extra={"provider": "grounded"},
            )
            return None
        if normalized == "duckduckgo":
            return DuckDuckGoSearchDiscoveryProvider()
        logger.warning(
            "Ignoring unknown search discovery provider",
            extra={"provider": normalized},
        )
        return None

    @staticmethod
    def _warning_from_failures(failures: list[SearchProviderFailure]) -> str:
        if any(failure.category == "config" for failure in failures):
            return "Internet search is not configured. Set TAVILY_API_KEY to enable discovery."
        if any(failure.category == "auth" for failure in failures):
            return "Internet search credentials are invalid. Check TAVILY_API_KEY."
        if any(failure.category == "rate_limit" for failure in failures):
            return "Internet search is temporarily rate-limited. Try again later."
        return "Discovery provider is temporarily unavailable. Try again later."


class _DuckDuckGoResultsParser(HTMLParser):
    """Extract basic search result cards from DuckDuckGo HTML results."""

    def __init__(self, *, limit: int):
        super().__init__()
        self.limit = limit
        self.results: list[SearchDiscoveryResult] = []
        self._current_link: dict[str, str] | None = None
        self._current_snippet_parts: list[str] = []
        self._in_anchor = False
        self._in_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        class_name = attr_map.get("class", "")
        if tag == "a" and DUCKDUCKGO_RESULT_ANCHOR in class_name and len(self.results) < self.limit:
            href = _unwrap_duckduckgo_href(attr_map.get("href", ""))
            if href:
                self._current_link = {"url": href, "title": ""}
                self._current_snippet_parts = []
                self._in_anchor = True
        elif tag in {"a", "span"} and DUCKDUCKGO_RESULT_SNIPPET in class_name and self._current_link:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_anchor:
            self._in_anchor = False
        if tag in {"a", "span"} and self._in_snippet:
            self._in_snippet = False
        if tag == "div" and self._current_link and self._current_link.get("title"):
            self._flush_result()

    def handle_data(self, data: str) -> None:
        text = _clean_inline_text(data)
        if not text:
            return
        if self._in_anchor and self._current_link is not None:
            self._current_link["title"] += text
        elif self._in_snippet and self._current_link is not None:
            self._current_snippet_parts.append(text)

    def close(self) -> None:
        super().close()
        self._flush_result()

    def _flush_result(self) -> None:
        if not self._current_link:
            return
        url = self._current_link.get("url", "").strip()
        title = self._current_link.get("title", "").strip()
        snippet = _clean_inline_text(" ".join(self._current_snippet_parts))
        if url and title and not any(item.url == url for item in self.results):
            self.results.append(
                SearchDiscoveryResult(
                    id=_discovery_result_id(url),
                    title=title,
                    url=url,
                    domain=_domain_label(url),
                    snippet=snippet or _domain_label(url),
                    favicon_url=_favicon_url(url),
                )
            )
        self._current_link = None
        self._current_snippet_parts = []


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


def image_search_metadata(
    stored_file: StoredFile,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return metadata that lets image MCP tools read an uploaded image."""
    root = os.getenv(
        "GENERAL_CHAT_IMAGE_SEARCH_CONTAINER_UPLOAD_ROOT",
        IMAGE_SEARCH_CONTAINER_UPLOAD_ROOT,
    )
    image_path = f"{root.rstrip('/')}/{stored_file.id}/{stored_file.name}"
    result = dict(metadata or {})
    result["imageSearchPath"] = image_path
    result["samSegmentationPath"] = image_path
    result["imageSearchPreviewUrl"] = f"/uploads/{stored_file.id}/{stored_file.name}"
    return result


def upload_file_ids_for_source(record: SourceRecord) -> set[str]:
    """Return local upload file ids referenced by a source record."""
    values: list[str] = []
    if record.url:
        values.append(record.url)
    metadata = record.metadata or {}
    for key in UPLOAD_METADATA_KEYS:
        value = metadata.get(key)
        if isinstance(value, str):
            values.append(value)
    ids: set[str] = set()
    for value in values:
        ids.update(_upload_file_ids_from_value(value))
    return ids


def mark_source_upload_deleted(
    record: SourceRecord,
    *,
    deleted_at: str | None = None,
) -> SourceRecord:
    """Scrub stale upload references after the physical upload is deleted."""
    if deleted_at is None:
        deleted_at = datetime.now(timezone.utc).isoformat()

    metadata = dict(record.metadata or {})
    for key in UPLOAD_METADATA_KEYS:
        metadata.pop(key, None)
    metadata["uploadDeleted"] = True
    metadata["uploadDeletedAt"] = deleted_at
    record.metadata = metadata

    if record.url and _upload_file_ids_from_value(record.url):
        record.url = None
    record.text = _scrub_deleted_upload_text(record.text)
    return record


def _upload_file_ids_from_value(value: str) -> set[str]:
    return {match.group(1) for match in _UPLOAD_FILE_ID_PATTERN.finditer(value)}


def _scrub_deleted_upload_text(text: str) -> str:
    if not text:
        return text
    kept: list[str] = []
    removed = False
    for line in text.splitlines():
        if _line_advertises_deleted_upload(line):
            removed = True
            continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    if removed:
        note = "[Upload file deleted after use; re-upload it to run image MCP tools again.]"
        cleaned = f"{cleaned}\n\n{note}".strip() if cleaned else note
    return cleaned


def _line_advertises_deleted_upload(line: str) -> bool:
    lowered = line.lower()
    return any(
        needle in lowered
        for needle in (
            "/uploads/",
            "/general-chat/uploads/",
            "mcp path:",
            "image_search.search_similar_images",
            "sam_segmentation.count_objects_with_sam3",
            "image_path=",
        )
    )


def image_search_text(
    stored_file: StoredFile,
    *,
    parsed_text: str = "",
    error: str | None = None,
) -> str:
    """Build attachment text with explicit image MCP instructions."""
    metadata = image_search_metadata(stored_file)
    parts = [
        f"Image source: {stored_file.name}",
        f"Browser URL: {metadata['imageSearchPreviewUrl']}",
        f"image_search MCP path: {metadata['imageSearchPath']}",
        f"sam_segmentation MCP path: {metadata['samSegmentationPath']}",
        "",
        (
            "To find visually similar CIFAR-10 images for this uploaded image, call "
            f"image_search.search_similar_images with image_path=\"{metadata['imageSearchPath']}\"."
        ),
        (
            "To count objects matching a text concept in this uploaded image, call "
            "sam_segmentation.count_objects_with_sam3 with "
            f"image_path=\"{metadata['samSegmentationPath']}\" and concept set to "
            "the noun phrase requested by the user, such as \"dog\", \"person\", "
            "\"red apple\", or \"yellow school bus\". Call it once and answer from "
            "the returned count when successful."
        ),
        (
            "Do not use filesystem MCP tools for this /general-chat/uploads path; "
            "it is mounted for image MCP containers and is outside the filesystem "
            "MCP sandbox."
        ),
        (
            "The browser preview URL is not a filesystem path. Image MCP tools can "
            "only read the /general-chat/uploads path above."
        ),
    ]
    if parsed_text.strip():
        parts.extend(["", "Extracted image context:", parsed_text.strip()])
    if error:
        parts.extend(["", f"Image text extraction note: {error}"])
    return "\n".join(parts).strip()


def source_record_from_file(
    *,
    session_id: str,
    stored_file: StoredFile,
    parser: SourceParserRegistry,
    max_bytes: int,
) -> SourceRecord:
    kind = kind_for_file(stored_file.name, stored_file.mime_type)
    try:
        validate_file_source(
            stored_file.name,
            stored_file.mime_type,
            stored_file.size_bytes,
            max_bytes=max_bytes,
        )
    except Exception as exc:
        return SourceRecord.create(
            session_id=session_id,
            name=stored_file.name,
            kind=kind,
            mime_type=stored_file.mime_type,
            size_bytes=stored_file.size_bytes,
            url=f"/uploads/{stored_file.id}/{stored_file.name}",
            text="",
            status="failed",
            error=str(exc),
        )

    try:
        parsed = parser.parse_file(stored_file)
        metadata = parsed.metadata
        text = parsed.text
        if kind == "image":
            metadata = image_search_metadata(stored_file, metadata)
            text = image_search_text(stored_file, parsed_text=parsed.text)
        return SourceRecord.create(
            session_id=session_id,
            name=stored_file.name,
            kind=kind,
            mime_type=stored_file.mime_type,
            size_bytes=stored_file.size_bytes,
            url=f"/uploads/{stored_file.id}/{stored_file.name}",
            text=text,
            metadata=metadata,
        )
    except Exception as exc:
        if kind == "image":
            metadata = image_search_metadata(stored_file, {"extractionError": str(exc)})
            return SourceRecord.create(
                session_id=session_id,
                name=stored_file.name,
                kind=kind,
                mime_type=stored_file.mime_type,
                size_bytes=stored_file.size_bytes,
                url=f"/uploads/{stored_file.id}/{stored_file.name}",
                text=image_search_text(stored_file, error=str(exc)),
                metadata=metadata,
            )
        return SourceRecord.create(
            session_id=session_id,
            name=stored_file.name,
            kind=kind,
            mime_type=stored_file.mime_type,
            size_bytes=stored_file.size_bytes,
            url=f"/uploads/{stored_file.id}/{stored_file.name}",
            text="",
            status="failed",
            error=str(exc),
        )


def source_record_from_text(
    *, session_id: str, name: str, text: str, parser: SourceParserRegistry
) -> SourceRecord:
    try:
        parsed = parser.parse_text(text)
        return SourceRecord.create(
            session_id=session_id,
            name=name.strip() or "Pasted text",
            kind="text",
            mime_type="text/plain",
            size_bytes=len(parsed.text.encode("utf-8")),
            text=parsed.text,
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
        name, parsed, size_bytes, mime_type = parser.parse_url(url, max_bytes=max_bytes)
        return SourceRecord.create(
            session_id=session_id,
            name=name,
            kind="url",
            mime_type=mime_type,
            size_bytes=size_bytes,
            url=url,
            text=parsed.text,
            metadata=parsed.metadata,
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
        return "spreadsheet"
    if mime_type in IMAGE_MIME_TYPES or ext in IMAGE_EXTENSIONS:
        return "image"
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

    response = requests.get(
        url,
        timeout=DEFAULT_DISCOVERY_TIMEOUT,
        headers={"User-Agent": "OpenBench-GeneralChat/0.1"},
    )
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


def _clean_inline_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def _snippet(text: str, idx: int, needle_len: int, *, radius: int = 90) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""
    start = max(0, idx - radius)
    end = min(len(cleaned), idx + max(needle_len, 1) + radius)
    snippet = cleaned[start:end].strip()
    if start:
        snippet = f"...{snippet}"
    if end < len(cleaned):
        snippet = f"{snippet}..."
    return snippet


def _unwrap_duckduckgo_href(href: str) -> str:
    if not href:
        return ""
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    if query.get("uddg"):
        return query["uddg"][0]
    return href


def _domain_label(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or url


def _favicon_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/favicon.ico"


def _discovery_result_id(url: str) -> str:
    return f"discover-{hashlib.md5(url.encode('utf-8')).hexdigest()[:12]}"
