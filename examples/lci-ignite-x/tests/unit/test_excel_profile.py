"""Tests for ExcelProfile — deterministic Excel metadata extraction."""

from pathlib import Path

import pytest

from lci_ignite.data.excel_profile import ExcelProfile


class TestExcelProfileExtract:
    """Tests for ExcelProfile.extract()."""

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ExcelProfile.extract("/nonexistent/file.xlsx")

    def test_non_excel_extension(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b,c")
        with pytest.raises(ValueError, match="Not an Excel file"):
            ExcelProfile.extract(csv_file)

    def test_extract_returns_required_keys(self, tmp_path):
        """Test with a real minimal xlsx file."""
        xlsx_path = tmp_path / "test.xlsx"
        _create_test_xlsx(xlsx_path)

        profile = ExcelProfile.extract(xlsx_path)

        assert "file_name" in profile
        assert "sheet_names" in profile
        assert "sheets" in profile
        assert profile["file_name"] == "test.xlsx"
        assert isinstance(profile["sheet_names"], list)
        assert len(profile["sheet_names"]) > 0

    def test_sheet_profile_structure(self, tmp_path):
        xlsx_path = tmp_path / "test.xlsx"
        _create_test_xlsx(xlsx_path)

        profile = ExcelProfile.extract(xlsx_path)
        sheet_name = profile["sheet_names"][0]
        sheet = profile["sheets"][sheet_name]

        assert "name" in sheet
        assert "dimensions" in sheet
        assert "headers" in sheet
        assert "header_row" in sheet
        assert "sample_rows" in sheet
        assert "detected_units" in sheet
        assert "detected_categories" in sheet
        assert "empty_columns" in sheet

    def test_headers_extracted(self, tmp_path):
        xlsx_path = tmp_path / "test.xlsx"
        _create_test_xlsx(xlsx_path)

        profile = ExcelProfile.extract(xlsx_path)
        sheet = profile["sheets"][profile["sheet_names"][0]]

        assert "Process" in sheet["headers"]
        assert "Unit" in sheet["headers"]

    def test_sample_rows_limited_to_5(self, tmp_path):
        xlsx_path = tmp_path / "test.xlsx"
        _create_test_xlsx(xlsx_path, num_rows=20)

        profile = ExcelProfile.extract(xlsx_path)
        sheet = profile["sheets"][profile["sheet_names"][0]]

        assert len(sheet["sample_rows"]) <= 5


class TestExcelProfileExtractSheet:
    """Tests for ExcelProfile.extract_sheet()."""

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ExcelProfile.extract_sheet("/nonexistent/file.xlsx")

    def test_sheet_not_found(self, tmp_path):
        xlsx_path = tmp_path / "test.xlsx"
        _create_test_xlsx(xlsx_path)

        with pytest.raises(ValueError, match="not found"):
            ExcelProfile.extract_sheet(xlsx_path, "NonexistentSheet")

    def test_default_first_sheet(self, tmp_path):
        xlsx_path = tmp_path / "test.xlsx"
        _create_test_xlsx(xlsx_path)

        sheet = ExcelProfile.extract_sheet(xlsx_path)
        assert sheet["name"] is not None


class TestFindHeaderRow:
    """Tests for ExcelProfile._find_header_row()."""

    def test_first_row_is_header(self):
        rows = [
            ["Process", "Category", "Amount", "Unit"],
            ["Well Op", "Water", 100, "L"],
        ]
        assert ExcelProfile._find_header_row(rows) == 0

    def test_header_after_title_row(self):
        rows = [
            ["Company Report", None, None, None],
            ["Process", "Category", "Amount", "Unit"],
            ["Well Op", "Water", 100, "L"],
        ]
        assert ExcelProfile._find_header_row(rows) == 1

    def test_empty_rows(self):
        assert ExcelProfile._find_header_row([]) == 0

    def test_all_none_rows(self):
        rows = [[None, None, None]]
        assert ExcelProfile._find_header_row(rows) == 0


class TestSerializeCell:
    """Tests for ExcelProfile._serialize_cell()."""

    def test_none(self):
        assert ExcelProfile._serialize_cell(None) is None

    def test_int(self):
        assert ExcelProfile._serialize_cell(42) == 42

    def test_float(self):
        assert ExcelProfile._serialize_cell(3.14) == 3.14

    def test_string(self):
        assert ExcelProfile._serialize_cell("hello") == "hello"

    def test_bool(self):
        assert ExcelProfile._serialize_cell(True) is True


# ---------------------------------------------------------------------------
# Helper: create a minimal test xlsx
# ---------------------------------------------------------------------------


def _create_test_xlsx(path: Path, num_rows: int = 5, sheet_name: str = "LDI Master"):
    """Create a minimal xlsx for testing."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name

    headers = ["No", "Process", "Category", "Material", "Direction", "Amount", "Unit"]
    ws.append(headers)

    for i in range(1, num_rows + 1):
        ws.append([i, "Well Operation", "Water", f"Flow {i}", "Input", i * 100.0, "L"])

    wb.save(str(path))
