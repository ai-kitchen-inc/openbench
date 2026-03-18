"""Unit tests for LCA agent tools."""

from __future__ import annotations

import json

import pytest

from lci_ignite.intelligence.tools import (
    aggregate_by_category,
    calculate_pareto,
    clear_render_items,
    create_hotspot_callout,
    create_hotspot_table,
    create_io_table,
    create_io_table_chart,
    create_narrative_callout,
    create_narrative_markdown,
    create_pareto_chart,
    export_to_docx,
    get_render_items,
    get_uploaded_files,
    set_attachments,
    set_upload_dir,
    validate_units,
)


@pytest.fixture(autouse=True)
def _clear_render():
    """Clear render items before and after each test."""
    clear_render_items()
    yield
    clear_render_items()


class TestCreateIOTable:
    def test_creates_table(self):
        data = json.dumps(
            {
                "inputs": [
                    {"flow": "Water", "category": "Resources", "amount": 100, "unit": "L"},
                ],
                "outputs": [
                    {"flow": "CO2", "category": "Emissions", "amount": 50, "unit": "kg"},
                ],
            }
        )
        result = create_io_table("Test IO Table", "Process A", data)

        assert "2 total rows" in result
        items = get_render_items()
        assert len(items) == 1
        assert items[0]["title"] == "Test IO Table"
        assert len(items[0]["rows"]) == 2
        assert items[0]["rows"][0][0] == "Input"
        assert items[0]["rows"][1][0] == "Output"

    def test_replaces_table_with_same_title(self):
        data = json.dumps({"inputs": [], "outputs": []})
        create_io_table("Same Title", "P1", data)
        create_io_table("Same Title", "P1", data)

        items = get_render_items()
        assert len(items) == 1

    def test_keeps_tables_with_different_titles(self):
        data = json.dumps({"inputs": [], "outputs": []})
        create_io_table("Table A", "P1", data)
        create_io_table("Table B", "P2", data)

        items = get_render_items()
        assert len(items) == 2

    def test_invalid_json(self):
        result = create_io_table("T", "P", "not json")
        assert "Error" in result

    def test_simapro_section_field(self):
        data = json.dumps(
            {
                "inputs": [
                    {"flow": "Coal", "section": "Materials/fuels", "amount": 100, "unit": "kg"},
                ],
                "outputs": [],
            }
        )
        create_io_table("SimaPro IO", "P", data)
        items = get_render_items()
        assert items[0]["rows"][0][2] == "Materials/fuels"


class TestAggregateByCategory:
    def test_aggregation(self):
        flows = [
            {"flow": "A", "category": "Energy", "amount": 100, "unit": "kWh"},
            {"flow": "B", "category": "Energy", "amount": 50, "unit": "kWh"},
            {"flow": "C", "category": "Materials", "amount": 200, "unit": "kg"},
        ]
        result = json.loads(aggregate_by_category(json.dumps(flows)))
        assert result["Energy"]["total"] == 150
        assert result["Energy"]["count"] == 2
        assert result["Materials"]["total"] == 200

    def test_empty_data(self):
        result = json.loads(aggregate_by_category(json.dumps([])))
        assert result == {}

    def test_invalid_json(self):
        result = aggregate_by_category("bad json")
        assert "Error" in result


class TestValidateUnits:
    def test_consistent_units(self):
        flows = [
            {"flow": "A", "category": "Energy", "amount": 100, "unit": "kWh"},
            {"flow": "B", "category": "Energy", "amount": 50, "unit": "kWh"},
        ]
        result = validate_units(json.dumps(flows))
        assert "consistent" in result.lower()

    def test_mixed_units(self):
        flows = [
            {"flow": "A", "category": "Energy", "amount": 100, "unit": "kWh"},
            {"flow": "B", "category": "Energy", "amount": 50, "unit": "MJ"},
        ]
        result = validate_units(json.dumps(flows))
        assert "mixed units" in result.lower()
        assert "Energy" in result

    def test_invalid_json(self):
        result = validate_units("not json")
        assert "Error" in result


class TestCreateIOTableChart:
    def test_creates_chart(self):
        data = json.dumps(
            [
                {"category": "Energy", "amount": 150},
                {"category": "Materials", "amount": 200},
            ]
        )
        result = create_io_table_chart("IO Chart", data)

        assert "2 data points" in result
        items = get_render_items()
        assert len(items) == 1
        assert items[0]["type"] == "bar"

    def test_invalid_json(self):
        result = create_io_table_chart("Chart", "bad")
        assert "Error" in result


class TestCalculatePareto:
    def test_basic_pareto(self):
        impacts = [
            {"name": "CO2", "amount": 800, "unit": "kg", "category": "Air"},
            {"name": "SO2", "amount": 100, "unit": "kg", "category": "Air"},
            {"name": "NOx", "amount": 50, "unit": "kg", "category": "Air"},
            {"name": "PM2.5", "amount": 30, "unit": "kg", "category": "Air"},
            {"name": "VOC", "amount": 20, "unit": "kg", "category": "Air"},
        ]
        result = json.loads(calculate_pareto(json.dumps(impacts)))

        assert result["hotspot_count"] >= 1
        assert result["total"] == 1000
        assert result["threshold"] == 80.0
        # CO2 alone is 80%, so it should be the only hotspot
        assert result["hotspots"][0]["name"] == "CO2"

    def test_custom_threshold(self):
        impacts = [
            {"name": "A", "amount": 50, "unit": "kg"},
            {"name": "B", "amount": 30, "unit": "kg"},
            {"name": "C", "amount": 20, "unit": "kg"},
        ]
        result = json.loads(calculate_pareto(json.dumps(impacts), threshold=90.0))
        assert result["threshold"] == 90.0

    def test_single_item(self):
        impacts = [{"name": "A", "amount": 100, "unit": "kg"}]
        result = json.loads(calculate_pareto(json.dumps(impacts)))
        assert result["hotspot_count"] == 1
        assert result["hotspots"][0]["percentage"] == 100.0

    def test_equal_values(self):
        impacts = [
            {"name": "A", "amount": 25, "unit": "kg"},
            {"name": "B", "amount": 25, "unit": "kg"},
            {"name": "C", "amount": 25, "unit": "kg"},
            {"name": "D", "amount": 25, "unit": "kg"},
        ]
        result = json.loads(calculate_pareto(json.dumps(impacts)))
        # Each is 25%, so 80% threshold needs at least 3 items
        assert result["hotspot_count"] >= 3

    def test_empty_data(self):
        result = calculate_pareto(json.dumps([]))
        assert "Error" in result

    def test_zero_total(self):
        impacts = [{"name": "A", "amount": 0, "unit": "kg"}]
        result = calculate_pareto(json.dumps(impacts))
        assert "Error" in result

    def test_invalid_json(self):
        result = calculate_pareto("bad json")
        assert "Error" in result


class TestCreateParetoChart:
    def test_creates_chart(self):
        data = json.dumps(
            [
                {"name": "CO2", "percentage": 80, "cumulative_percentage": 80},
                {"name": "SO2", "percentage": 20, "cumulative_percentage": 100},
            ]
        )
        result = create_pareto_chart("Pareto", data)

        assert "2 items" in result
        items = get_render_items()
        assert len(items) == 1
        assert items[0]["type"] == "bar"
        assert items[0]["options"]["xKey"] == "name"


class TestCreateHotspotTable:
    def test_creates_table(self):
        headers = ["Rank", "Flow", "Impact %"]
        rows = [["1", "CO2", "80%"], ["2", "SO2", "10%"]]
        result = create_hotspot_table("Hotspots", headers, rows)

        assert "3 columns" in result
        assert "2 rows" in result
        items = get_render_items()
        assert len(items) == 1


class TestCreateHotspotCallout:
    def test_creates_callout(self):
        create_hotspot_callout("Critical finding!", "warning", "Warning")

        items = get_render_items()
        assert len(items) == 1
        assert items[0]["calloutContent"] == "Critical finding!"
        assert items[0]["variant"] == "warning"

    def test_replaces_previous_callout(self):
        create_hotspot_callout("First")
        create_hotspot_callout("Second")

        items = get_render_items()
        assert len(items) == 1
        assert items[0]["calloutContent"] == "Second"


class TestCreateNarrativeMarkdown:
    def test_returns_markdown(self):
        result = create_narrative_markdown("Section Title", "Some **content**")
        assert "## Section Title" in result
        assert "Some **content**" in result

    def test_no_render_items(self):
        create_narrative_markdown("Title", "Content")
        items = get_render_items()
        assert len(items) == 0  # Markdown goes through streaming, not render items


class TestCreateNarrativeCallout:
    def test_creates_callout(self):
        create_narrative_callout("Recommendation", "info", "Tip")

        items = get_render_items()
        assert len(items) == 1
        assert items[0]["variant"] == "info"

    def test_allows_multiple_callouts(self):
        create_narrative_callout("First")
        create_narrative_callout("Second")

        items = get_render_items()
        assert len(items) == 2  # Narrative allows multiple (unlike hotspot)


class TestExportToDocx:
    def test_creates_file_card(self, tmp_path):
        set_upload_dir(str(tmp_path))
        content = json.dumps({"narrative": "Test narrative content."})
        result = export_to_docx("Report", content)

        assert "lca_report.docx" in result
        assert "bytes" in result
        items = get_render_items()
        assert len(items) == 1
        assert items[0]["name"] == "lca_report.docx"
        assert items[0]["size"] > 0
        # Verify actual file was created
        assert (tmp_path / "lca_report.docx").exists()

    def test_custom_filename(self, tmp_path):
        set_upload_dir(str(tmp_path))
        export_to_docx("Report", json.dumps({"narrative": "test"}), filename="custom.docx")

        items = get_render_items()
        assert items[0]["name"] == "custom.docx"
        assert (tmp_path / "custom.docx").exists()

    def test_generates_with_sections(self, tmp_path):
        set_upload_dir(str(tmp_path))
        content = json.dumps(
            {
                "io_table": {
                    "Process A": {
                        "inputs": [
                            {"flow": "Water", "category": "Air", "amount": 100, "unit": "L"}
                        ],
                        "outputs": [],
                    }
                },
                "narrative": "## Summary\nTest analysis.",
            }
        )
        result = export_to_docx("LCA Report", content)

        assert "bytes" in result
        assert (tmp_path / "lca_report.docx").exists()
        assert (tmp_path / "lca_report.docx").stat().st_size > 0

    def test_plain_text_content(self, tmp_path):
        set_upload_dir(str(tmp_path))
        result = export_to_docx("Report", "Simple text content")

        assert "bytes" in result
        assert (tmp_path / "lca_report.docx").exists()


class TestGetUploadedFiles:
    """Tests for get_uploaded_files tool."""

    def test_no_files(self):
        set_attachments(None)
        result = json.loads(get_uploaded_files())
        assert result["files"] == []
        assert "No files" in result["message"]

    def test_with_files(self):
        files = [
            {
                "name": "test.xlsx",
                "path": "/uploads/abc_test.xlsx",
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        ]
        set_attachments(files)
        result = json.loads(get_uploaded_files())
        assert result["count"] == 1
        assert result["files"][0]["name"] == "test.xlsx"
        assert result["files"][0]["path"] == "/uploads/abc_test.xlsx"
        # Cleanup
        set_attachments(None)

    def test_multiple_files(self):
        files = [
            {
                "name": "a.xlsx",
                "path": "/uploads/a.xlsx",
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
            {"name": "b.csv", "path": "/uploads/b.csv", "mime_type": "text/csv"},
        ]
        set_attachments(files)
        result = json.loads(get_uploaded_files())
        assert result["count"] == 2
        set_attachments(None)
