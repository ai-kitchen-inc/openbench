"""Chat attachment handler for LCI CSV files.

Detects the format of uploaded CSV files and creates the appropriate
DataSource instance.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from openbench.core.abstractions import DataSource

from lci_ignite.data.sources.easylca import REQUIRED_COLUMNS, EasyLCASource
from lci_ignite.data.sources.simapro_csv import ALL_SECTIONS, PROCESS_START, SimaProCSVSource

logger = logging.getLogger(__name__)


class UnsupportedFormatError(Exception):
    """Raised when a CSV file format cannot be detected."""


class ChatAttachmentHandler:
    """Detects CSV format and creates the appropriate DataSource.

    Supports:
        - easyLCA CSV: column-based format with Process, Flow, Category, etc.
        - SimaPro CSV: block-based format with section markers.
    """

    def detect_format(self, file_path: str, mime_type: str = "") -> str:
        """Detect the CSV format of a file.

        Args:
            file_path: Path to the CSV file.
            mime_type: Optional MIME type hint (not used for detection logic,
                but checked for non-CSV types).

        Returns:
            Format string: "easylca", "simapro", or "unknown".
        """
        path = Path(file_path)

        if not path.exists():
            return "unknown"

        # Check file extension
        suffix = path.suffix.lower()
        if suffix not in (".csv", ".txt", ""):
            return "unknown"

        # Try easyLCA detection first (simpler format)
        if self._is_easylca(path):
            return "easylca"

        # Try SimaPro detection
        if self._is_simapro(path):
            return "simapro"

        return "unknown"

    def create_source(self, file_path: str, encoding: str = "utf-8") -> DataSource:
        """Create a DataSource from a CSV file path.

        Args:
            file_path: Path to the CSV file.
            encoding: File encoding.

        Returns:
            EasyLCASource or SimaProCSVSource.

        Raises:
            UnsupportedFormatError: If the format cannot be detected.
        """
        fmt = self.detect_format(file_path)

        if fmt == "easylca":
            return EasyLCASource(path=file_path, encoding=encoding)
        elif fmt == "simapro":
            return SimaProCSVSource(path=file_path, encoding=encoding)
        else:
            raise UnsupportedFormatError(
                f"Cannot detect CSV format for '{file_path}'. "
                "Supported formats: easyLCA CSV, SimaPro CSV."
            )

    def _is_easylca(self, path: Path) -> bool:
        """Check if a file matches easyLCA CSV format."""
        try:
            df = pd.read_csv(path, nrows=0)
            actual_columns = set(df.columns.str.strip())
            return REQUIRED_COLUMNS.issubset(actual_columns)
        except Exception:
            return False

    def _is_simapro(self, path: Path) -> bool:
        """Check if a file matches SimaPro CSV format."""
        try:
            with open(path, encoding="utf-8") as f:
                # Check first 50 lines for section markers
                for i, line in enumerate(f):
                    if i >= 50:
                        break
                    stripped = line.strip().rstrip(";").strip()
                    if stripped in ALL_SECTIONS or stripped == PROCESS_START:
                        return True
        except Exception:
            pass
        return False
