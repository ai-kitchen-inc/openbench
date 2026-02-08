"""Tests for PDF data source."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openbench.core.context import ProjectContext
from openbench.data.exceptions import (
    ExtractionError,
    FileNotFoundError,
    UnsupportedFormatError,
    ValidationError,
)
from openbench.data.sources.pdf import PDFSource


class TestPDFSourceInit(unittest.TestCase):
    """Tests for PDFSource initialization."""

    def test_init_with_path_string(self):
        """Test initialization with string path."""
        source = PDFSource(path="/path/to/file.pdf")
        self.assertEqual(source.path, Path("/path/to/file.pdf"))

    def test_init_with_path_object(self):
        """Test initialization with Path object."""
        path = Path("/path/to/file.pdf")
        source = PDFSource(path=path)
        self.assertEqual(source.path, path)

    def test_init_with_project(self):
        """Test initialization with project context."""
        project = ProjectContext(name="Test Project")
        source = PDFSource(path="/path/to/file.pdf", project=project)
        self.assertEqual(source.project, project)

    def test_init_default_values(self):
        """Test default values."""
        source = PDFSource(path="/path/to/file.pdf")
        self.assertTrue(source.recursive)
        self.assertEqual(source.encoding, "utf-8")
        self.assertIsNone(source.project)


class TestPDFSourceProperties(unittest.TestCase):
    """Tests for PDFSource properties."""

    def test_source_type(self):
        """Test source_type property."""
        source = PDFSource(path="/path/to/file.pdf")
        self.assertEqual(source.source_type, "pdf")

    def test_source_id_format(self):
        """Test source_id format."""
        source = PDFSource(path="/path/to/file.pdf")
        self.assertTrue(source.source_id.startswith("pdf_"))
        self.assertEqual(len(source.source_id), 12)  # pdf_ + 8 hex chars

    def test_source_id_unique_for_different_paths(self):
        """Test source_id is different for different paths."""
        source1 = PDFSource(path="/path/to/file1.pdf")
        source2 = PDFSource(path="/path/to/file2.pdf")
        self.assertNotEqual(source1.source_id, source2.source_id)

    def test_source_id_same_for_same_path(self):
        """Test source_id is consistent for same path."""
        source1 = PDFSource(path="/path/to/file.pdf")
        source2 = PDFSource(path="/path/to/file.pdf")
        self.assertEqual(source1.source_id, source2.source_id)


class TestPDFSourceValidation(unittest.TestCase):
    """Tests for PDFSource validation."""

    def test_validate_nonexistent_path(self):
        """Test validation fails for nonexistent path."""
        source = PDFSource(path="/nonexistent/path/file.pdf")
        with self.assertRaises(ValidationError):
            source.validate()

    def test_validate_non_pdf_file(self):
        """Test validation fails for non-PDF file."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"not a pdf")
            temp_path = f.name

        try:
            source = PDFSource(path=temp_path)
            with self.assertRaises(ValidationError):
                source.validate()
        finally:
            Path(temp_path).unlink()

    def test_validate_empty_directory(self):
        """Test validation fails for directory with no PDFs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source = PDFSource(path=temp_dir)
            with self.assertRaises(ValidationError):
                source.validate()


class TestPDFSourceGetMetadata(unittest.TestCase):
    """Tests for PDFSource metadata."""

    def test_get_metadata_with_project(self):
        """Test metadata includes project info."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 test")
            temp_path = f.name

        try:
            project = ProjectContext(name="Test Project")
            source = PDFSource(path=temp_path, project=project)

            # Mock _get_pdf_files to return the temp file
            source._files = [Path(temp_path)]

            metadata = source.get_metadata()
            self.assertEqual(metadata["project_id"], project.project_id)
            self.assertEqual(metadata["project_name"], project.name)
        finally:
            Path(temp_path).unlink()

    def test_get_metadata_caching(self):
        """Test metadata is cached."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 test")
            temp_path = f.name

        try:
            source = PDFSource(path=temp_path)
            source._files = [Path(temp_path)]

            metadata1 = source.get_metadata()
            metadata2 = source.get_metadata()
            self.assertIs(metadata1, metadata2)
        finally:
            Path(temp_path).unlink()


class TestPDFSourceExtraction(unittest.TestCase):
    """Tests for PDFSource extraction with mocked pypdf."""

    def test_extract_missing_pypdf(self):
        """Test extraction raises error when pypdf not installed."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 test")
            temp_path = f.name

        try:
            source = PDFSource(path=temp_path)
            source._files = [Path(temp_path)]

            with (
                patch.dict("sys.modules", {"pypdf": None}),
                patch(
                    "openbench.data.sources.pdf.PDFSource._extract_text_from_pdf"
                ) as mock_extract,
            ):
                mock_extract.side_effect = ExtractionError("pypdf is required for PDF extraction")
                with self.assertRaises(ExtractionError) as ctx:
                    source.extract()
                self.assertIn("pypdf", str(ctx.exception))
        finally:
            Path(temp_path).unlink()

    @patch("openbench.data.sources.pdf.PDFSource._extract_text_from_pdf")
    def test_extract_single_file(self, mock_extract):
        """Test extraction of single PDF file."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 test")
            temp_path = f.name

        try:
            mock_extract.return_value = {
                "text": "Hello World",
                "page_count": 1,
                "file_path": temp_path,
                "file_name": Path(temp_path).name,
                "pdf_metadata": {},
            }

            source = PDFSource(path=temp_path)
            source._files = [Path(temp_path)]
            result = source.extract()

            self.assertEqual(result.content, "Hello World")
            self.assertEqual(result.content_type, "text")
            self.assertEqual(result.metadata["total_pages"], 1)
        finally:
            Path(temp_path).unlink()

    @patch("openbench.data.sources.pdf.PDFSource._extract_text_from_pdf")
    def test_extract_multiple_files(self, mock_extract):
        """Test extraction of multiple PDF files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            files = []
            for i in range(3):
                path = Path(temp_dir) / f"file{i}.pdf"
                path.write_bytes(b"%PDF-1.4 test")
                files.append(path)

            def mock_extract_impl(pdf_path):
                return {
                    "text": f"Content of {pdf_path.name}",
                    "page_count": 2,
                    "file_path": str(pdf_path),
                    "file_name": pdf_path.name,
                    "pdf_metadata": {},
                }

            mock_extract.side_effect = mock_extract_impl

            source = PDFSource(path=temp_dir)
            source._files = files
            result = source.extract()

            self.assertIn("file0.pdf", result.content)
            self.assertIn("file1.pdf", result.content)
            self.assertIn("file2.pdf", result.content)
            self.assertEqual(result.metadata["total_pages"], 6)
            self.assertEqual(result.metadata["extracted_files"], 3)

    @patch("openbench.data.sources.pdf.PDFSource._extract_text_from_pdf")
    def test_extract_with_project_context(self, mock_extract):
        """Test extraction includes project context in metadata."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 test")
            temp_path = f.name

        try:
            mock_extract.return_value = {
                "text": "Content",
                "page_count": 1,
                "file_path": temp_path,
                "file_name": Path(temp_path).name,
                "pdf_metadata": {},
            }

            project = ProjectContext(name="Test Project")
            source = PDFSource(path=temp_path, project=project)
            source._files = [Path(temp_path)]
            result = source.extract()

            self.assertIn("project_context", result.metadata)
            self.assertEqual(
                result.metadata["project_context"]["project_id"],
                project.project_id,
            )
        finally:
            Path(temp_path).unlink()

    @patch("openbench.data.sources.pdf.PDFSource._extract_text_from_pdf")
    def test_extract_partial_failure(self, mock_extract):
        """Test extraction continues when some files fail."""
        with tempfile.TemporaryDirectory() as temp_dir:
            files = []
            for i in range(3):
                path = Path(temp_dir) / f"file{i}.pdf"
                path.write_bytes(b"%PDF-1.4 test")
                files.append(path)

            def mock_extract_impl(pdf_path):
                if "file1" in str(pdf_path):
                    raise ExtractionError(f"Failed: {pdf_path}")
                return {
                    "text": f"Content of {pdf_path.name}",
                    "page_count": 1,
                    "file_path": str(pdf_path),
                    "file_name": pdf_path.name,
                    "pdf_metadata": {},
                }

            mock_extract.side_effect = mock_extract_impl

            source = PDFSource(path=temp_dir)
            source._files = files
            result = source.extract()

            self.assertEqual(result.metadata["extracted_files"], 2)
            self.assertIsNotNone(result.metadata["extraction_errors"])
            self.assertEqual(len(result.metadata["extraction_errors"]), 1)

    def test_extract_no_files(self):
        """Test extraction raises error when no files found."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source = PDFSource(path=temp_dir)
            source._files = []
            with self.assertRaises(ExtractionError):
                source.extract()


class TestPDFSourceChainable(unittest.TestCase):
    """Tests for PDFSource chainable interface."""

    @patch("openbench.data.sources.pdf.PDFSource._extract_text_from_pdf")
    def test_invoke_calls_extract(self, mock_extract):
        """Test invoke calls extract."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 test")
            temp_path = f.name

        try:
            mock_extract.return_value = {
                "text": "Content",
                "page_count": 1,
                "file_path": temp_path,
                "file_name": Path(temp_path).name,
                "pdf_metadata": {},
            }

            source = PDFSource(path=temp_path)
            source._files = [Path(temp_path)]
            result = source.invoke()

            self.assertEqual(result.content, "Content")
        finally:
            Path(temp_path).unlink()


class TestPDFSourceDirectoryHandling(unittest.TestCase):
    """Tests for directory handling."""

    def test_get_pdf_files_single_file(self):
        """Test _get_pdf_files with single file."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 test")
            temp_path = f.name

        try:
            source = PDFSource(path=temp_path)
            files = source._get_pdf_files()
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0], Path(temp_path))
        finally:
            Path(temp_path).unlink()

    def test_get_pdf_files_directory(self):
        """Test _get_pdf_files with directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            for i in range(3):
                path = Path(temp_dir) / f"file{i}.pdf"
                path.write_bytes(b"%PDF-1.4 test")

            source = PDFSource(path=temp_dir)
            files = source._get_pdf_files()
            self.assertEqual(len(files), 3)

    def test_get_pdf_files_recursive(self):
        """Test recursive directory search."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create files in root and subdirectory
            Path(temp_dir, "root.pdf").write_bytes(b"%PDF-1.4")
            subdir = Path(temp_dir) / "subdir"
            subdir.mkdir()
            Path(subdir, "nested.pdf").write_bytes(b"%PDF-1.4")

            source = PDFSource(path=temp_dir, recursive=True)
            files = source._get_pdf_files()
            self.assertEqual(len(files), 2)

    def test_get_pdf_files_non_recursive(self):
        """Test non-recursive directory search."""
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "root.pdf").write_bytes(b"%PDF-1.4")
            subdir = Path(temp_dir) / "subdir"
            subdir.mkdir()
            Path(subdir, "nested.pdf").write_bytes(b"%PDF-1.4")

            source = PDFSource(path=temp_dir, recursive=False)
            files = source._get_pdf_files()
            self.assertEqual(len(files), 1)

    def test_get_pdf_files_nonexistent(self):
        """Test _get_pdf_files with nonexistent path."""
        source = PDFSource(path="/nonexistent/path")
        with self.assertRaises(FileNotFoundError):
            source._get_pdf_files()

    def test_get_pdf_files_non_pdf(self):
        """Test _get_pdf_files with non-PDF file."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"not a pdf")
            temp_path = f.name

        try:
            source = PDFSource(path=temp_path)
            with self.assertRaises(UnsupportedFormatError):
                source._get_pdf_files()
        finally:
            Path(temp_path).unlink()


if __name__ == "__main__":
    unittest.main()
