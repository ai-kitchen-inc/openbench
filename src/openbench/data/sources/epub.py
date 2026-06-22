"""EPUB data source for extracting text from EPUB e-books."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openbench.core.abstractions import DataSource, RawData
from openbench.data.exceptions import (
    ExtractionError,
    FileNotFoundError,
    UnsupportedFormatError,
    ValidationError,
)

if TYPE_CHECKING:
    from openbench.core.context import ProjectContext


class EPUBSource(DataSource):
    """Data source for extracting text from EPUB e-books.

    Walks the book's document spine, strips HTML, and emits one markdown
    section per chapter. Uses ``ebooklib`` + ``beautifulsoup4`` (install via
    the ``[epub]`` extra). Both imports are lazy so importing this module never
    requires the optional dependencies.

    Example:
        source = EPUBSource(path="./book.epub")
        data = source.extract()
    """

    def __init__(
        self,
        path: str | Path,
        project: ProjectContext | None = None,
    ):
        """Initialize EPUB source.

        Args:
            path: Path to a single ``.epub`` file.
            project: Optional project context for multi-tenancy.
        """
        self.path = Path(path)
        self.project = project
        self._metadata: dict[str, Any] | None = None

    @property
    def source_type(self) -> str:
        """Return source type identifier."""
        return "epub"

    @property
    def source_id(self) -> str:
        """Return unique identifier based on path."""
        path_str = str(self.path.absolute())
        hash_suffix = hashlib.md5(path_str.encode()).hexdigest()[:8]
        return f"epub_{hash_suffix}"

    def validate(self) -> bool:
        """Validate that the EPUB source is accessible.

        Returns:
            True if source is valid.

        Raises:
            ValidationError: If the source is not a readable ``.epub`` file.
        """
        if not self.path.exists():
            raise ValidationError(f"Path does not exist: {self.path}")
        if not self.path.is_file():
            raise ValidationError(f"Not a file: {self.path}")
        if self.path.suffix.lower() != ".epub":
            raise ValidationError(f"Not an EPUB file: {self.path}")
        return True

    def get_metadata(self) -> dict[str, Any]:
        """Get metadata about the EPUB source.

        Returns:
            Dict with file info: path, size, title (when available).
        """
        if self._metadata is not None:
            return self._metadata

        self._metadata = {
            "path": str(self.path),
            "file_name": self.path.name,
            "size_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }
        if self.project:
            self._metadata["project_id"] = self.project.project_id
            self._metadata["project_name"] = self.project.name
        return self._metadata

    def _extract_chapters(self) -> tuple[list[str], dict[str, Any]]:
        """Extract per-chapter markdown text and book metadata.

        Returns:
            Tuple of (chapter texts, book metadata).
        """
        try:
            import ebooklib
            from ebooklib import epub
        except ImportError:
            raise ExtractionError(
                "ebooklib is required for EPUB extraction. "
                "Install with: pip install 'openbench[epub]'"
            ) from None

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            raise ExtractionError(
                "beautifulsoup4 is required for EPUB extraction. "
                "Install with: pip install 'openbench[epub]'"
            ) from None

        try:
            book = epub.read_epub(str(self.path))
        except Exception as e:
            raise ExtractionError(f"Failed to read EPUB {self.path}: {e}") from e

        chapters: list[str] = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            text = soup.get_text(separator="\n").strip()
            if text:
                chapters.append(text)

        title = ""
        try:
            title_meta = book.get_metadata("DC", "title")
            if title_meta:
                title = str(title_meta[0][0])
        except Exception:
            title = ""

        return chapters, {"title": title, "chapter_count": len(chapters)}

    def extract(self) -> RawData:
        """Extract text from the EPUB file.

        Returns:
            RawData containing the book text as markdown (one section per
            chapter).

        Raises:
            FileNotFoundError: If the file does not exist.
            UnsupportedFormatError: If the file is not an ``.epub``.
            ExtractionError: If extraction fails or yields no text.
        """
        if not self.path.exists():
            raise FileNotFoundError(f"Path does not exist: {self.path}")
        if self.path.suffix.lower() != ".epub":
            raise UnsupportedFormatError(f"Not an EPUB file: {self.path}")

        chapters, book_meta = self._extract_chapters()
        if not chapters:
            raise ExtractionError(f"No text content could be extracted from {self.path.name}")

        parts = [f"## Chapter {i}\n\n{text}" for i, text in enumerate(chapters, start=1)]
        content = "\n\n---\n\n".join(parts)

        metadata = {**self.get_metadata(), **book_meta}
        if self.project:
            metadata["project_context"] = self.project.to_dict()

        return RawData(
            content=content,
            content_type="text",
            metadata=metadata,
            source=self,
        )

    async def aextract(self) -> RawData:
        """Async version of extract (runs sync extraction in executor)."""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.extract)
