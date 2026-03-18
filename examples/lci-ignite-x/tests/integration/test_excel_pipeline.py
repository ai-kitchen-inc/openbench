"""Integration tests for Excel LDI pipeline.

Tests the full flow: upload → profile match → parse → unit conversion →
Pareto selection → IO Table build → DOCX export.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lci_ignite.data.attachment_handler import ChatAttachmentHandler
from lci_ignite.data.excel_profile import ExcelProfile
from lci_ignite.data.mapping_profiles import load_profile, match_profile
from lci_ignite.data.sources.excel_lci import ExcelLCISource
from lci_ignite.intelligence.tools import (
    _read_pipeline,
    apply_unit_conversions,
    build_proper_io_table,
    calculate_functional_unit,
    clear_pipeline_data,
    clear_render_items,
    export_to_docx,
    get_render_items,
    parse_ldi_sheet,
    select_pareto_items,
    set_upload_dir,
    validate_data_quality,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
LDI_FIXTURE = FIXTURES_DIR / "ldi_master_pertamina_mini.xlsx"


@pytest.fixture(autouse=True)
def _clear():
    clear_render_items()
    clear_pipeline_data()
    yield
    clear_render_items()
    clear_pipeline_data()


class TestProfileMatchPipeline:
    """Test: Excel upload → profile auto-match → parse → Standard LCI Schema."""

    def test_attachment_handler_detects_excel_profile(self):
        """ChatAttachmentHandler detects format as 'excel:pertamina_pep_tanjung'."""
        handler = ChatAttachmentHandler()
        fmt = handler.detect_format(str(LDI_FIXTURE))
        assert fmt == "excel:pertamina_pep_tanjung"

    def test_profile_match_by_sheet_name(self):
        """ExcelProfile extraction + match_profile finds pertamina_pep_tanjung."""
        excel_profile = ExcelProfile.extract(LDI_FIXTURE)
        assert "LDI-Pertamina Zona 9-00004" in excel_profile["sheet_names"]

        matched = match_profile(excel_profile)
        assert matched is not None
        assert matched["profile_name"] == "pertamina_pep_tanjung"

    def test_excel_lci_source_parse(self):
        """ExcelLCISource parses fixture into Standard LCI Schema flows."""
        profile = load_profile("pertamina_pep_tanjung")
        source = ExcelLCISource(LDI_FIXTURE, profile=profile)

        assert source.validate() is True
        raw = source.extract()

        content = raw.content
        flows = content["flows"]
        assert len(flows) > 0

        # Check categories were mapped correctly
        categories = {f["category"] for f in flows}
        assert "Bahan Baku" in categories  # Raw Material from Nature
        assert "Air" in categories  # Water
        assert "Listrik" in categories  # Electricity
        assert "Emisi Udara" in categories  # Air Emissions
        assert "Produk" in categories  # Product

        # Check excluded categories were filtered out
        original_cats = {f.get("original_category") for f in flows}
        assert "Raw Material from Processes" not in original_cats
        assert "Other Supporting Material" not in original_cats

        # Check helper data extracted
        helper = content["helper_data"]
        assert "Projected Lifetime of Infrastructure" in helper
        assert "Projected Lifetime of Land" in helper

        # Check products info
        products = content["products"]
        assert len(products) == 2
        assert products[0]["name"] == "Gas Bumi"
        assert products[1]["name"] == "Minyak Bumi"


class TestFullPipeline:
    """Test: parse → unit conversion → Pareto → FU → IO Table → DOCX."""

    @pytest.fixture
    def parsed_data(self) -> dict:
        """Parse the LDI fixture into Standard LCI Schema."""
        profile = load_profile("pertamina_pep_tanjung")
        source = ExcelLCISource(LDI_FIXTURE, profile=profile)
        raw = source.extract()
        return raw.content

    def test_parse_ldi_sheet_tool(self):
        """parse_ldi_sheet tool works with the fixture."""
        result = parse_ldi_sheet(str(LDI_FIXTURE), "pertamina_pep_tanjung")
        summary = json.loads(result)
        assert summary["status"] == "parsed"
        assert summary["total_flows"] > 0
        assert len(summary["categories"]) > 0
        # Full data stored in pipeline state
        pipeline = _read_pipeline()
        assert pipeline is not None
        assert len(pipeline["flows"]) > 0

    def test_unit_conversions(self, parsed_data):
        """apply_unit_conversions correctly converts ton→kg, barrel→L, etc."""
        profile = load_profile("pertamina_pep_tanjung")
        conversions = profile.get("unit_conversions", [])

        result_json = apply_unit_conversions(
            json.dumps(parsed_data),
            json.dumps(conversions),
        )
        result = json.loads(result_json)
        assert result["status"] == "converted"

        # Full data in pipeline state
        pipeline = _read_pipeline()
        flows = pipeline["flows"]

        # Find a Solid Supporting Material flow (ton→kg)
        cement_flows = [f for f in flows if f["flow_name"] == "Cement"]
        if cement_flows:
            cement = cement_flows[0]
            assert cement["unit"] == "kg"
            assert cement["amount"] == 25000.0  # 25 ton * 1000

        # Find Water flow (barrel→L)
        water_flows = [f for f in flows if f["flow_name"] == "Produced Water"]
        if water_flows:
            water = water_flows[0]
            assert water["unit"] == "L"
            assert abs(water["amount"] - 80000 * 158.987) < 1.0

    def test_pareto_selection(self, parsed_data):
        """select_pareto_items keeps top N + aggregates rest."""
        result_json = select_pareto_items(json.dumps(parsed_data), top_n=3)
        result = json.loads(result_json)
        assert result["status"] == "pareto_selected"

        # Full data in pipeline state
        pipeline = _read_pipeline()
        flows = pipeline["flows"]

        # Group by category
        by_cat: dict[str, list] = {}
        for f in flows:
            by_cat.setdefault(f["category"], []).append(f)

        # Categories with > 3 items should have been reduced
        for cat, cat_flows in by_cat.items():
            assert len(cat_flows) <= 4  # top_n=3 + possible "Lainnya"

    def test_data_quality_validation(self, parsed_data):
        """validate_data_quality returns issues list."""
        result_json = validate_data_quality(json.dumps(parsed_data))
        result = json.loads(result_json)
        assert "issues" in result
        # Issues may or may not be present depending on data

    def test_build_io_table(self, parsed_data):
        """build_proper_io_table creates table with render items."""
        clear_render_items()

        profile = load_profile("pertamina_pep_tanjung")
        config = {
            "products": profile["products"],
            "title": "Test IO Table",
        }
        result = build_proper_io_table(json.dumps(parsed_data), json.dumps(config))

        # Should return summary text
        assert "IO Table" in result or "section" in result.lower()

        # Should push render items (table)
        items = get_render_items()
        assert len(items) >= 1

    def test_full_pipeline_to_docx(self, parsed_data, tmp_path):
        """Full pipeline: parse → convert → Pareto → FU → IO Table → DOCX.

        Uses pipeline auto-chaining (same as live app).
        """
        clear_render_items()
        clear_pipeline_data()
        set_upload_dir(str(tmp_path))

        profile = load_profile("pertamina_pep_tanjung")

        # Step 1: Parse (stores in pipeline)
        parse_result = parse_ldi_sheet(str(LDI_FIXTURE), "pertamina_pep_tanjung")
        assert "parsed" in parse_result

        # Step 2: Unit conversions (auto-reads pipeline)
        conversions = profile.get("unit_conversions", [])
        apply_unit_conversions(conversions=json.dumps(conversions))

        # Step 3: Pareto selection (auto-reads pipeline)
        select_pareto_items(top_n=5)

        # Step 4: Calculate functional unit (auto-reads pipeline + products)
        calculate_functional_unit()

        # Step 5: Build IO Table (auto-reads pipeline)
        clear_render_items()
        build_proper_io_table()

        io_items = get_render_items()
        assert len(io_items) >= 1

        # Step 6: Validate data quality (auto-reads pipeline)
        quality_json = validate_data_quality()
        quality = json.loads(quality_json)
        assert "issues" in quality

        # Step 7: Export to DOCX
        clear_render_items()
        report_content = json.dumps(
            {
                "narrative": "## Summary\nIntegration test LCA report.\n\n## Findings\nAll good.",
            }
        )
        result = export_to_docx("Integration Test Report", report_content)

        assert "bytes" in result
        docx_path = tmp_path / "lca_report.docx"
        assert docx_path.exists()
        assert docx_path.stat().st_size > 0


class TestUnknownExcelFormat:
    """Test: unknown Excel → structure extraction (no profile match)."""

    def test_unknown_excel_extracts_structure(self, tmp_path):
        """ExcelLCISource without profile returns structural metadata."""
        # Create a non-Pertamina Excel file
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Custom LDI Data"
        ws.append(["ID", "Nama Proses", "Kategori", "Nama Aliran", "Jumlah", "Satuan", "Arah"])
        ws.append([1, "Proses A", "Bahan Baku", "Air", 100, "L", "Input"])
        ws.append([2, "Proses A", "Emisi", "CO2", 50, "kg", "Output"])

        custom_file = tmp_path / "custom_ldi.xlsx"
        wb.save(str(custom_file))

        # No profile should match
        excel_profile = ExcelProfile.extract(custom_file)
        matched = match_profile(excel_profile)
        assert matched is None

        # ExcelLCISource without profile → structure extraction
        source = ExcelLCISource(custom_file)
        raw = source.extract()

        assert raw.content_type == "excel_profile"
        assert raw.content["mode"] == "structure_extraction"
        profile = raw.content["excel_profile"]
        assert "Custom LDI Data" in profile["sheet_names"]
        assert len(profile["sheets"]["Custom LDI Data"]["headers"]) >= 7

    def test_attachment_handler_unknown_format(self, tmp_path):
        """ChatAttachmentHandler returns 'excel_unknown' for unknown Excel."""
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Different Format"
        ws.append(["Col1", "Col2", "Col3"])
        ws.append([1, 2, 3])

        unknown_file = tmp_path / "unknown.xlsx"
        wb.save(str(unknown_file))

        handler = ChatAttachmentHandler()
        fmt = handler.detect_format(str(unknown_file))
        assert fmt == "excel_unknown"
