"""PDF data source for extracting text from PDF files."""

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from openbench.core.abstractions import DataSource, RawData
from openbench.core.context import ProjectContext
from openbench.data.exceptions import (
    ExtractionError,
    FileNotFoundError,
    UnsupportedFormatError,
    ValidationError,
)


class PDFSource(DataSource):
    """Data source for extracting text from PDF files.

    Supports single PDF files or directories containing PDFs.
    Uses pypdf for extraction (lightweight, pure Python).

    Example:
        # Single file
        source = PDFSource(path="./report.pdf")
        data = source.extract()

        # Directory
        source = PDFSource(path="./documents/")
        data = source.extract()  # Extracts all PDFs

        # With project context
        project = ProjectContext(name="Q1 Report")
        source = PDFSource(path="./report.pdf", project=project)
    """

    def __init__(
        self,
        path: Union[str, Path],
        project: Optional[ProjectContext] = None,
        recursive: bool = True,
        encoding: str = "utf-8",
    ):
        """Initialize PDF source.

        Args:
            path: Path to PDF file or directory containing PDFs
            project: Optional project context for multi-tenancy
            recursive: If path is directory, search recursively (default: True)
            encoding: Text encoding for extracted content (default: utf-8)
        """
        self.path = Path(path)
        self.project = project
        self.recursive = recursive
        self.encoding = encoding
        self._files: Optional[List[Path]] = None
        self._metadata: Optional[Dict[str, Any]] = None

    @property
    def source_type(self) -> str:
        """Return source type identifier."""
        return "pdf"

    @property
    def source_id(self) -> str:
        """Return unique identifier based on path."""
        path_str = str(self.path.absolute())
        hash_suffix = hashlib.md5(path_str.encode()).hexdigest()[:8]
        return f"pdf_{hash_suffix}"

    def _get_pdf_files(self) -> List[Path]:
        """Get list of PDF files to process."""
        if self._files is not None:
            return self._files

        if self.path.is_file():
            if self.path.suffix.lower() != ".pdf":
                raise UnsupportedFormatError(f"Not a PDF file: {self.path}")
            self._files = [self.path]
        elif self.path.is_dir():
            pattern = "**/*.pdf" if self.recursive else "*.pdf"
            self._files = sorted(self.path.glob(pattern))
        else:
            raise FileNotFoundError(f"Path does not exist: {self.path}")

        return self._files

    def validate(self) -> bool:
        """Validate that the PDF source is accessible.

        Returns:
            True if source is valid

        Raises:
            ValidationError: If source is not valid
        """
        if not self.path.exists():
            raise ValidationError(f"Path does not exist: {self.path}")

        try:
            files = self._get_pdf_files()
            if not files:
                raise ValidationError(f"No PDF files found in: {self.path}")
            return True
        except (FileNotFoundError, UnsupportedFormatError) as e:
            raise ValidationError(str(e))

    def get_metadata(self) -> Dict[str, Any]:
        """Get metadata about the PDF source.

        Returns:
            Dict with file info: path, files, total_size, etc.
        """
        if self._metadata is not None:
            return self._metadata

        files = self._get_pdf_files()
        total_size = sum(f.stat().st_size for f in files)

        self._metadata = {
            "path": str(self.path),
            "is_directory": self.path.is_dir(),
            "file_count": len(files),
            "total_size_bytes": total_size,
            "files": [str(f) for f in files],
        }

        if self.project:
            self._metadata["project_id"] = self.project.project_id
            self._metadata["project_name"] = self.project.name

        return self._metadata

    def _extract_text_from_pdf(self, pdf_path: Path) -> Dict[str, Any]:
        """Extract text from a single PDF file.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Dict with text content and metadata
        """
        try:
            import pypdf
        except ImportError:
            raise ExtractionError(
                "pypdf is required for PDF extraction. "
                "Install with: pip install pypdf"
            )

        try:
            with open(pdf_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                text_parts = []

                for page_num, page in enumerate(reader.pages):
                    page_text = page.extract_text() or ""
                    text_parts.append(page_text)

                return {
                    "text": "\n\n".join(text_parts),
                    "page_count": len(reader.pages),
                    "file_path": str(pdf_path),
                    "file_name": pdf_path.name,
                    "pdf_metadata": dict(reader.metadata) if reader.metadata else {},
                }
        except Exception as e:
            raise ExtractionError(f"Failed to extract text from {pdf_path}: {e}")

    def extract(self) -> RawData:
        """Extract text from PDF file(s).

        Returns:
            RawData containing extracted text content

        Raises:
            ExtractionError: If extraction fails
        """
        files = self._get_pdf_files()

        if not files:
            raise ExtractionError(f"No PDF files found in: {self.path}")

        extracted = []
        total_pages = 0
        errors = []

        for pdf_file in files:
            try:
                result = self._extract_text_from_pdf(pdf_file)
                extracted.append(result)
                total_pages += result["page_count"]
            except ExtractionError as e:
                errors.append(str(e))

        if not extracted:
            raise ExtractionError(
                f"Failed to extract any PDFs. Errors: {'; '.join(errors)}"
            )

        # Combine content from all files
        if len(extracted) == 1:
            content = extracted[0]["text"]
        else:
            content = "\n\n---\n\n".join(
                f"# {e['file_name']}\n\n{e['text']}" for e in extracted
            )

        metadata = {
            **self.get_metadata(),
            "total_pages": total_pages,
            "extracted_files": len(extracted),
            "extraction_errors": errors if errors else None,
            "documents": [
                {
                    "file": e["file_name"],
                    "pages": e["page_count"],
                    "pdf_metadata": e["pdf_metadata"],
                }
                for e in extracted
            ],
        }

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
