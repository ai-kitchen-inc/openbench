"""Unit tests for DocxReportGenerator."""

from __future__ import annotations

import json
from pathlib import Path

from lci_ignite.output.docx_generator import DocxReportGenerator


class TestDocxGeneratorProperties:
    def test_output_format(self):
        gen = DocxReportGenerator()
        assert gen.output_format == "docx"


class TestDocxGeneratorValidation:
    def test_validate_dict(self):
        gen = DocxReportGenerator()
        assert gen.validate({"narrative": "text"}) is True

    def test_validate_json_string(self):
        gen = DocxReportGenerator()
        assert gen.validate(json.dumps({"a": 1})) is True

    def test_validate_plain_string(self):
        gen = DocxReportGenerator()
        assert gen.validate("some text") is True

    def test_validate_empty_string(self):
        gen = DocxReportGenerator()
        assert gen.validate("") is False

    def test_validate_none(self):
        gen = DocxReportGenerator()
        assert gen.validate(None) is False


class TestDocxGeneratorGenerate:
    def test_generate_minimal(self, tmp_path):
        gen = DocxReportGenerator()
        output_path = str(tmp_path / "report.docx")

        result = gen.generate(
            content={"narrative": "Test report content"},
            output_path=output_path,
            title="Test Report",
        )

        assert result.format == "docx"
        assert result.file_path == output_path
        assert result.size_bytes > 0
        assert Path(output_path).exists()

    def test_generate_with_author(self, tmp_path):
        gen = DocxReportGenerator()
        output_path = str(tmp_path / "report.docx")

        result = gen.generate(
            content={"narrative": "Content"},
            output_path=output_path,
            title="Report",
            author="Test Author",
        )

        assert result.metadata["author"] == "Test Author"

    def test_generate_with_io_table(self, tmp_path):
        gen = DocxReportGenerator()
        output_path = str(tmp_path / "report.docx")

        content = {
            "io_table": {
                "Cement Production": {
                    "inputs": [
                        {
                            "flow": "Limestone",
                            "category": "Materials",
                            "amount": 1200,
                            "unit": "kg",
                        },
                    ],
                    "outputs": [
                        {"flow": "CO2", "category": "Emissions", "amount": 950, "unit": "kg"},
                    ],
                }
            }
        }

        result = gen.generate(content=content, output_path=output_path)
        assert result.size_bytes > 0
        assert "io_table" in result.metadata["sections"]

    def test_generate_with_hotspots(self, tmp_path):
        gen = DocxReportGenerator()
        output_path = str(tmp_path / "report.docx")

        content = {
            "hotspots": {
                "hotspots": [
                    {
                        "name": "CO2",
                        "amount": 950,
                        "unit": "kg",
                        "percentage": 80.0,
                        "cumulative_percentage": 80.0,
                    },
                ],
                "summary": "CO2 is the dominant emission.",
            }
        }

        result = gen.generate(content=content, output_path=output_path)
        assert "hotspots" in result.metadata["sections"]

    def test_generate_with_all_sections(self, tmp_path):
        gen = DocxReportGenerator()
        output_path = str(tmp_path / "report.docx")

        content = {
            "io_table": {"P1": {"inputs": [], "outputs": []}},
            "hotspots": {"hotspots": [], "summary": "None found"},
            "narrative": "## Summary\n\nNo significant impacts.",
            "proper_references": [
                {"title": "Ref 1", "content": "Reference content"},
            ],
            "appendix": {"Raw Data": "See attached CSV"},
        }

        result = gen.generate(
            content=content,
            output_path=output_path,
            title="Full Report",
            author="LCI Team",
        )

        assert result.size_bytes > 0
        assert len(result.metadata["sections"]) == 5

    def test_generate_from_json_string(self, tmp_path):
        gen = DocxReportGenerator()
        output_path = str(tmp_path / "report.docx")

        result = gen.generate(
            content=json.dumps({"narrative": "From JSON string"}),
            output_path=output_path,
        )

        assert result.size_bytes > 0

    def test_generate_from_plain_string(self, tmp_path):
        gen = DocxReportGenerator()
        output_path = str(tmp_path / "report.docx")

        result = gen.generate(
            content="Plain text report content",
            output_path=output_path,
        )

        assert result.size_bytes > 0

    def test_generate_creates_output_dir(self, tmp_path):
        gen = DocxReportGenerator()
        output_path = str(tmp_path / "nested" / "dir" / "report.docx")

        gen.generate(
            content={"narrative": "Content"},
            output_path=output_path,
        )

        assert Path(output_path).exists()

    def test_generate_metadata(self, tmp_path):
        gen = DocxReportGenerator()
        output_path = str(tmp_path / "report.docx")

        result = gen.generate(
            content={"narrative": "Content"},
            output_path=output_path,
            title="My Report",
        )

        assert result.metadata["title"] == "My Report"
        assert "narrative" in result.metadata["sections"]

    def test_generate_narrative_with_markdown(self, tmp_path):
        gen = DocxReportGenerator()
        output_path = str(tmp_path / "report.docx")

        narrative = (
            "## Executive Summary\n\n"
            "This is the summary.\n\n"
            "### Key Findings\n\n"
            "- Finding one\n"
            "- Finding two\n\n"
            "Regular paragraph text."
        )

        result = gen.generate(
            content={"narrative": narrative},
            output_path=output_path,
        )

        assert result.size_bytes > 0


class TestDocxGeneratorInvoke:
    def test_invoke(self, tmp_path):
        gen = DocxReportGenerator()

        result = gen.invoke(
            input={"narrative": "Content", "output_path": str(tmp_path / "report.docx")},
        )

        assert result.format == "docx"
