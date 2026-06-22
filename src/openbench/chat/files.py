"""File storage and content extraction for chat uploads.

Provides:
- FileStore: Protocol for pluggable file storage (local disk / Drive / S3 / ...)
- LocalFileStore: Disk-based implementation. Files live in
  ``upload_dir/<file_id>/<original_filename>``. This used to be called
  ``FileStore``; the old name is aliased for backward compat.
- FileContentExtractor: Extract text from uploaded files (PDF, text, etc.)
- StoredFile: Metadata for a stored file. Carries an optional
  ``backend_ref`` so Drive-backed stores can round-trip file ids without
  leaking backend specifics into the attachment protocol.
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from openbench.chat.session import Attachment

logger = logging.getLogger(__name__)


@dataclass
class StoredFile:
    """Metadata for a stored file.

    Attributes:
        id: Opaque id returned by the store; stable across reads.
        name: Original filename with the store's uniqueness suffix.
        path: Local filesystem path — real for :class:`LocalFileStore`,
            a TTL-cached temp path for remote stores.
        mime_type: MIME type of the file's contents.
        size_bytes: File size in bytes.
        stored_at: ISO-8601 timestamp of the store / last modification.
        extracted_text: Optional extracted text preview (from the
            :class:`FileContentExtractor`).
        web_view_link: Cloud viewer URL when the backing store is
            cloud-hosted (Drive). ``None`` for local stores. Frontend
            can use this to open the file directly in the user's
            authenticated cloud UI — for example, clicking a Drive
            webViewLink in a new tab opens ``drive.google.com`` without
            proxying bytes through the backend.
    """

    id: str
    name: str
    path: str
    mime_type: str
    size_bytes: int
    stored_at: str
    extracted_text: str | None = None
    web_view_link: str | None = None

    def to_attachment(self, base_url: str) -> Attachment:
        """Convert to an Attachment for chat messages.

        Args:
            base_url: URL prefix for serving the file (e.g. "/uploads").
        """
        url = f"{base_url}/{self.id}/{self.name}"
        file_type: str = "file"
        if self.mime_type.startswith("image/"):
            file_type = "image"
        elif self.mime_type.startswith("audio/"):
            file_type = "audio"
        elif self.mime_type.startswith("video/"):
            file_type = "video"

        return Attachment(
            id=self.id,
            type=file_type,
            name=self.name,
            url=url,
            mime_type=self.mime_type,
            size_bytes=self.size_bytes,
            extracted_text=self.extracted_text,
        )


@runtime_checkable
class FileStore(Protocol):
    """Pluggable file storage for chat uploads.

    Two implementations ship:

    - :class:`LocalFileStore` — disk-backed, files under ``upload_dir/``.
    - ``GoogleDriveFileStore`` (``openbench.integrations.gdrive``) —
      uploads to the user's ``OpenBench/uploads/`` Drive folder.

    Methods intentionally return plain :class:`StoredFile` values so
    downstream code (XQL skill, chat renderer, etc.) only depends on
    local paths via :meth:`get_local_path`. Backends that live in the
    cloud (Drive) download-on-demand to a temp cache and return the
    cached path — callers never have to know the file is remote.
    """

    def store(self, filename: str, content: bytes, mime_type: str) -> StoredFile:
        """Persist the file and return its metadata + public url."""
        ...

    def get(self, file_id: str) -> StoredFile | None:
        """Return metadata for a previously-stored file, or None if absent."""
        ...

    def get_local_path(self, file_id: str) -> str | None:
        """Return a filesystem path the caller can read.

        For local stores this is the actual on-disk path; for remote
        backends it's a temp-file path populated on first access. Return
        None if the file can't be produced (unknown id, IO error).
        """
        ...

    def delete(self, file_id: str) -> bool:
        """Delete a previously-stored file and return True if removed."""
        ...


class LocalFileStore:
    """Disk-based file storage for chat uploads.

    Files are stored in subdirectories named by their unique ID:
        upload_dir/<file_id>/<original_filename>
    """

    def __init__(self, upload_dir: str = "./uploads"):
        self.upload_dir = Path(upload_dir)

    def store(self, filename: str, content: bytes, mime_type: str) -> StoredFile:
        """Store a file on disk.

        Args:
            filename: Original filename.
            content: Raw file bytes.
            mime_type: MIME type (e.g. "application/pdf").

        Returns:
            StoredFile with metadata.
        """
        file_id = f"file-{uuid.uuid4().hex[:8]}"
        file_dir = self.upload_dir / file_id
        file_dir.mkdir(parents=True, exist_ok=True)

        safe_name = Path(filename).name  # strip directory traversal
        file_path = file_dir / safe_name
        file_path.write_bytes(content)

        return StoredFile(
            id=file_id,
            name=safe_name,
            path=str(file_path.absolute()),
            mime_type=mime_type or "application/octet-stream",
            size_bytes=len(content),
            stored_at=datetime.now(timezone.utc).isoformat(),
        )

    def get(self, file_id: str) -> StoredFile | None:
        """Retrieve stored file metadata by ID.

        Args:
            file_id: The file's unique ID.

        Returns:
            StoredFile if found, None otherwise.
        """
        file_dir = self.upload_dir / file_id
        if not file_dir.is_dir():
            return None

        # Find the first file in the directory
        files = [f for f in file_dir.iterdir() if f.is_file()]
        if not files:
            return None

        file_path = files[0]
        mime_type = _guess_mime_type(file_path.name)

        return StoredFile(
            id=file_id,
            name=file_path.name,
            path=str(file_path.absolute()),
            mime_type=mime_type,
            size_bytes=file_path.stat().st_size,
            stored_at=datetime.fromtimestamp(
                file_path.stat().st_mtime, tz=timezone.utc
            ).isoformat(),
        )

    def get_local_path(self, file_id: str) -> str | None:
        """Return the on-disk path; identical to ``get().path`` for local."""
        stored = self.get(file_id)
        return stored.path if stored is not None else None

    def delete(self, file_id: str) -> bool:
        """Delete the upload directory for a stored file id."""
        if not file_id:
            return False

        root = self.upload_dir.resolve()
        target = (self.upload_dir / file_id).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return False
        if target == root or not target.exists() or not target.is_dir():
            return False

        shutil.rmtree(target)
        return True


# Backward-compat alias — the old ``FileStore`` concrete class is now the
# :class:`LocalFileStore` implementation. Callers still importing
# ``FileStore`` directly get the local one.
_LocalFileStoreAlias = LocalFileStore


_EXCEL_MIMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}

_TEXT_LIKE_MIMES = {
    "application/json",
    "application/xml",
    "application/yaml",
    "application/x-yaml",
    "application/javascript",
    "application/typescript",
}


class FileContentExtractor:
    """Extract text content from uploaded files.

    Supports:
    - application/pdf: Uses PDFSource for extraction
    - application/epub+zip: Uses EPUBSource for extraction
    - Excel (.xlsx/.xls): Converts sheets to markdown tables (first 10 rows)
    - text/* and text-like (JSON, XML, YAML, JS, TS): Direct file read
    - image/*: Returns metadata description
    - other: Returns metadata description
    """

    def extract(self, stored_file: StoredFile) -> str:
        """Extract text content from a stored file.

        Args:
            stored_file: The file to extract content from.

        Returns:
            Extracted text content.
        """
        mime = stored_file.mime_type
        ext = os.path.splitext(stored_file.name)[1].lower()

        if mime == "application/pdf":
            return self._extract_pdf(stored_file)

        if mime == "application/epub+zip" or ext == ".epub":
            return self._extract_epub(stored_file)

        if mime in _EXCEL_MIMES:
            return self._extract_excel(stored_file)

        if mime.startswith("audio/"):
            return self._extract_audio(stored_file)

        if mime.startswith("text/") or mime in _TEXT_LIKE_MIMES:
            return self._extract_text(stored_file)

        if mime.startswith("image/"):
            return f"[Image: {stored_file.name}] ({mime}, {stored_file.size_bytes} bytes)"

        return f"[File: {stored_file.name}] ({mime}, {stored_file.size_bytes} bytes)"

    def _extract_pdf(self, stored_file: StoredFile) -> str:
        """Extract text from PDF using PDFSource."""
        try:
            from openbench.data.sources.pdf import PDFSource

            source = PDFSource(path=stored_file.path)
            raw_data = source.extract()
            return raw_data.content
        except Exception as e:
            logger.warning(f"PDF extraction failed for {stored_file.name}: {e}")
            return f"[PDF: {stored_file.name}] (extraction failed: {e})"

    def _extract_epub(self, stored_file: StoredFile) -> str:
        """Extract text from an EPUB using EPUBSource."""
        try:
            from openbench.data.sources.epub import EPUBSource

            source = EPUBSource(path=stored_file.path)
            raw_data = source.extract()
            return raw_data.content
        except Exception as e:
            logger.warning(f"EPUB extraction failed for {stored_file.name}: {e}")
            return f"[EPUB: {stored_file.name}] (extraction failed: {e})"

    def _extract_audio(self, stored_file: StoredFile) -> str:
        """Transcribe audio to text via the resolved TranscriptionProvider."""
        try:
            from openbench.intelligence.transcription import get_transcriber

            transcript = get_transcriber().transcribe(
                stored_file.path, mime_type=stored_file.mime_type
            )
            if transcript.strip():
                return transcript
            return f"[Audio: {stored_file.name}] (no speech detected)"
        except Exception as e:
            logger.warning(f"Audio transcription failed for {stored_file.name}: {e}")
            return f"[Audio: {stored_file.name}] (transcription failed: {e})"

    def _extract_text(self, stored_file: StoredFile) -> str:
        """Read text file directly."""
        try:
            return Path(stored_file.path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return Path(stored_file.path).read_text(encoding="latin-1")
            except Exception as e:
                return f"[Text file: {stored_file.name}] (read failed: {e})"

    def _extract_excel(self, stored_file: StoredFile, max_rows: int = 10) -> str:
        """Extract Excel sheets as markdown tables (preview)."""
        try:
            import pandas as pd

            sheets = pd.read_excel(stored_file.path, sheet_name=None)
            parts: list[str] = []
            for name, df in sheets.items():
                total = len(df)
                preview = df.head(max_rows)
                md = preview.to_markdown(index=False)
                header = f"### Sheet: {name} ({total} rows)"
                if total > max_rows:
                    header += f" — showing first {max_rows}"
                parts.append(f"{header}\n\n{md}")
            return "\n\n".join(parts)
        except ImportError:
            return f"[Excel: {stored_file.name}] (install pandas + openpyxl for Excel support)"
        except Exception as e:
            logger.warning(f"Excel extraction failed for {stored_file.name}: {e}")
            return f"[Excel: {stored_file.name}] (extraction failed: {e})"


def _guess_mime_type(filename: str) -> str:
    """Guess MIME type from filename extension."""
    ext = os.path.splitext(filename)[1].lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".epub": "application/epub+zip",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".json": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".bmp": "image/bmp",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
    }
    return mime_map.get(ext, "application/octet-stream")
