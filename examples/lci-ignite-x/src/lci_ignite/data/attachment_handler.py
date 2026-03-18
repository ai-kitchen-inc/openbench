"""Chat attachment handler for LCI files (CSV + Excel).

Detects the format of uploaded files and creates the appropriate
DataSource instance. Supports easyLCA CSV, SimaPro CSV, and Excel LDI.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from openbench.core.abstractions import DataSource

from lci_ignite.data.excel_profile import ExcelProfile
from lci_ignite.data.mapping_profiles import match_profile
from lci_ignite.data.sources.easylca import REQUIRED_COLUMNS, EasyLCASource
from lci_ignite.data.sources.excel_lci import ExcelLCISource
from lci_ignite.data.sources.simapro_csv import ALL_SECTIONS, PROCESS_START, SimaProCSVSource

logger = logging.getLogger(__name__)


class UnsupportedFormatError(Exception):
    """Raised when a file format cannot be detected."""


class ChatAttachmentHandler:
    """Detects file format and creates the appropriate DataSource.

    Supports:
        - easyLCA CSV: column-based format with Process, Flow, Category, etc.
        - SimaPro CSV: block-based format with section markers.
        - Excel LDI (.xlsx): any company LDI Master with MappingProfile.
    """

    def detect_format(self, file_path: str, mime_type: str = "") -> str:
        """Detect the format of an uploaded file.

        Args:
            file_path: Path to the file.
            mime_type: Optional MIME type hint.

        Returns:
            Format string:
                - "easylca" -- easyLCA CSV
                - "simapro" -- SimaPro CSV
                - "excel:<profile_name>" -- known Excel format (profile matched)
                - "excel_unknown" -- Excel but no profile found
                - "unknown" -- unrecognized format
        """
        path = Path(file_path)

        if not path.exists():
            return "unknown"

        suffix = path.suffix.lower()

        # Excel files (.xlsx, .xls)
        if suffix in (".xlsx", ".xls"):
            return self._detect_excel_format(path)

        # CSV/text files
        if suffix in (".csv", ".txt", ""):
            if self._is_easylca(path):
                return "easylca"
            if self._is_simapro(path):
                return "simapro"

        return "unknown"

    def create_source(self, file_path: str, encoding: str = "utf-8") -> DataSource:
        """Create a DataSource from an uploaded file.

        Args:
            file_path: Path to the file.
            encoding: File encoding (for CSV files).

        Returns:
            Appropriate DataSource instance.

        Raises:
            UnsupportedFormatError: If the format cannot be detected.
        """
        fmt = self.detect_format(file_path)

        if fmt == "easylca":
            return EasyLCASource(path=file_path, encoding=encoding)
        elif fmt == "simapro":
            return SimaProCSVSource(path=file_path, encoding=encoding)
        elif fmt.startswith("excel:"):
            profile = self._find_matching_profile(Path(file_path))
            return ExcelLCISource(path=file_path, profile=profile)
        elif fmt == "excel_unknown":
            return ExcelLCISource(path=file_path, profile=None)
        else:
            raise UnsupportedFormatError(
                f"Cannot detect format for '{file_path}'. "
                "Supported formats: easyLCA CSV, SimaPro CSV, Excel LDI (.xlsx)."
            )

    def _detect_excel_format(self, path: Path) -> str:
        """Detect Excel format and match against saved profiles."""
        profile = self._find_matching_profile(path)
        if profile:
            return f"excel:{profile.get('profile_name', 'matched')}"
        return "excel_unknown"

    def _find_matching_profile(self, path: Path) -> dict | None:
        """Try to match an Excel file against saved MappingProfiles."""
        try:
            excel_profile = ExcelProfile.extract(path)
            return match_profile(excel_profile)
        except Exception as exc:
            logger.warning("Failed to extract Excel profile: %s", exc)
            return None

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
                for i, line in enumerate(f):
                    if i >= 50:
                        break
                    stripped = line.strip().rstrip(";").strip()
                    if stripped in ALL_SECTIONS or stripped == PROCESS_START:
                        return True
        except Exception:
            pass
        return False
