"""Tests for ChatAttachmentHandler -- format detection and source creation."""

import json
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pandas as pd
import pytest

from lci_ignite.data.attachment_handler import ChatAttachmentHandler, UnsupportedFormatError
from lci_ignite.data.sources.easylca import EasyLCASource
from lci_ignite.data.sources.excel_lci import ExcelLCISource
from lci_ignite.data.sources.simapro_csv import SimaProCSVSource


@pytest.fixture
def handler():
    return ChatAttachmentHandler()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_PROFILE = {
    "profile_name": "test_handler_profile",
    "company": "Test Handler Corp",
    "scope": "Test",
    "sheet_name": "LDI-Test Handler-00001",
    "expected_headers": [
        "No",
        "Process Title",
        "LDI Category",
        "Material Title",
        "Input or Output",
        "Unit",
    ],
    "column_mapping": {
        "process": {"index": 1, "header": "Process Title"},
        "category": {"index": 2, "header": "LDI Category"},
        "flow_name": {"index": 3, "header": "Material Title"},
        "direction": {"index": 4, "header": "Input or Output"},
        "unit": {"index": 5, "header": "Unit"},
    },
    "products": [],
    "category_mapping": {},
    "unit_conversions": [],
}


def _create_easylca_csv(path: Path):
    df = pd.DataFrame(
        {
            "Process": ["Well Op"],
            "Flow": ["Water"],
            "Category": ["Water"],
            "Amount": [100.0],
            "Unit": ["L"],
            "Direction": ["Input"],
        }
    )
    df.to_csv(path, index=False)


def _create_simapro_csv(path: Path):
    path.write_text("{SimaPro 9}\nProcess\nCategory type: waste treatment\n")


def _create_known_xlsx(path: Path):
    """Create xlsx that matches the test profile (by sheet name)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "LDI-Test Handler-00001"
    ws.append(["No", "Process Title", "LDI Category", "Material Title", "Input or Output", "Unit"])
    ws.append([1, "Well Op", "Water", "PDAM", "Input", "L"])
    wb.save(str(path))


def _create_unknown_xlsx(path: Path):
    """Create xlsx with no matching profile."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Unknown Company Data"
    ws.append(["Col A", "Col B", "Col C"])
    ws.append([1, 2, 3])
    wb.save(str(path))


@pytest.fixture
def profile_dir(tmp_path):
    """Save a test profile to a temp dir for matching."""
    profile_path = tmp_path / "profiles"
    profile_path.mkdir()
    (profile_path / "test_handler_profile.json").write_text(
        json.dumps(_TEST_PROFILE, indent=2), encoding="utf-8"
    )
    return profile_path


# ---------------------------------------------------------------------------
# Tests: detect_format
# ---------------------------------------------------------------------------


class TestDetectFormat:
    def test_easylca_csv(self, handler, tmp_path):
        csv_file = tmp_path / "data.csv"
        _create_easylca_csv(csv_file)
        assert handler.detect_format(str(csv_file)) == "easylca"

    def test_simapro_csv(self, handler, tmp_path):
        csv_file = tmp_path / "data.csv"
        _create_simapro_csv(csv_file)
        assert handler.detect_format(str(csv_file)) == "simapro"

    def test_known_excel(self, handler, tmp_path, profile_dir):
        xlsx = tmp_path / "data.xlsx"
        _create_known_xlsx(xlsx)
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            fmt = handler.detect_format(str(xlsx))
        assert fmt.startswith("excel:")
        assert "test_handler_profile" in fmt

    def test_unknown_excel(self, handler, tmp_path, profile_dir):
        xlsx = tmp_path / "data.xlsx"
        _create_unknown_xlsx(xlsx)
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            assert handler.detect_format(str(xlsx)) == "excel_unknown"

    def test_nonexistent_file(self, handler):
        assert handler.detect_format("/no/such/file.csv") == "unknown"

    def test_unsupported_extension(self, handler, tmp_path):
        pdf = tmp_path / "doc.pdf"
        pdf.write_text("not a pdf")
        assert handler.detect_format(str(pdf)) == "unknown"


# ---------------------------------------------------------------------------
# Tests: create_source
# ---------------------------------------------------------------------------


class TestCreateSource:
    def test_creates_easylca_source(self, handler, tmp_path):
        csv_file = tmp_path / "data.csv"
        _create_easylca_csv(csv_file)
        source = handler.create_source(str(csv_file))
        assert isinstance(source, EasyLCASource)

    def test_creates_simapro_source(self, handler, tmp_path):
        csv_file = tmp_path / "data.csv"
        _create_simapro_csv(csv_file)
        source = handler.create_source(str(csv_file))
        assert isinstance(source, SimaProCSVSource)

    def test_creates_excel_source_known(self, handler, tmp_path, profile_dir):
        xlsx = tmp_path / "data.xlsx"
        _create_known_xlsx(xlsx)
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            source = handler.create_source(str(xlsx))
        assert isinstance(source, ExcelLCISource)

    def test_creates_excel_source_unknown(self, handler, tmp_path, profile_dir):
        xlsx = tmp_path / "data.xlsx"
        _create_unknown_xlsx(xlsx)
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            source = handler.create_source(str(xlsx))
        assert isinstance(source, ExcelLCISource)

    def test_raises_for_unsupported(self, handler, tmp_path):
        pdf = tmp_path / "doc.pdf"
        pdf.write_text("not a pdf")
        with pytest.raises(UnsupportedFormatError):
            handler.create_source(str(pdf))
