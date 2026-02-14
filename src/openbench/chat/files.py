"""File storage and content extraction for chat uploads.

Provides:
- FileStore: Disk-based file storage with unique IDs
- FileContentExtractor: Extract text from uploaded files (PDF, text, etc.)
- StoredFile: Metadata for a stored file
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from openbench.chat.session import Attachment

logger = logging.getLogger(__name__)


@dataclass
class StoredFile:
    """Metadata for a file stored on disk."""

    id: str
    name: str
    path: str
    mime_type: str
    size_bytes: int
    stored_at: str
    extracted_text: str | None = None

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


class FileStore:
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


class FileContentExtractor:
    """Extract text content from uploaded files.

    Supports:
    - application/pdf: Uses PDFSource for extraction
    - text/*: Direct file read
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

        if mime == "application/pdf":
            return self._extract_pdf(stored_file)

        if mime.startswith("text/"):
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

    def _extract_text(self, stored_file: StoredFile) -> str:
        """Read text file directly."""
        try:
            return Path(stored_file.path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return Path(stored_file.path).read_text(encoding="latin-1")
            except Exception as e:
                return f"[Text file: {stored_file.name}] (read failed: {e})"


def _guess_mime_type(filename: str) -> str:
    """Guess MIME type from filename extension."""
    ext = os.path.splitext(filename)[1].lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".json": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
    }
    return mime_map.get(ext, "application/octet-stream")
