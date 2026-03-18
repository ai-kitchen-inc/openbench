"""Tests for ChatAttachmentHandler -- format detection and source creation."""

from pathlib import Path

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
    """Create xlsx that matches the pertamina profile (by sheet name)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "LDI-Pertamina Zona 9-00004"
    ws.append(["No", "Process Title", "LDI Category"])
    ws.append([1, "Well Op", "Water"])
    wb.save(str(path))


def _create_unknown_xlsx(path: Path):
    """Create xlsx with no matching profile."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Unknown Company Data"
    ws.append(["Col A", "Col B", "Col C"])
    ws.append([1, 2, 3])
    wb.save(str(path))


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

    def test_known_excel(self, handler, tmp_path):
        xlsx = tmp_path / "data.xlsx"
        _create_known_xlsx(xlsx)
        fmt = handler.detect_format(str(xlsx))
        assert fmt.startswith("excel:")
        assert "pertamina" in fmt

    def test_unknown_excel(self, handler, tmp_path):
        xlsx = tmp_path / "data.xlsx"
        _create_unknown_xlsx(xlsx)
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

    def test_creates_excel_source_known(self, handler, tmp_path):
        xlsx = tmp_path / "data.xlsx"
        _create_known_xlsx(xlsx)
        source = handler.create_source(str(xlsx))
        assert isinstance(source, ExcelLCISource)

    def test_creates_excel_source_unknown(self, handler, tmp_path):
        xlsx = tmp_path / "data.xlsx"
        _create_unknown_xlsx(xlsx)
        source = handler.create_source(str(xlsx))
        assert isinstance(source, ExcelLCISource)

    def test_raises_for_unsupported(self, handler, tmp_path):
        pdf = tmp_path / "doc.pdf"
        pdf.write_text("not a pdf")
        with pytest.raises(UnsupportedFormatError):
            handler.create_source(str(pdf))
