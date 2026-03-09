"""Unit tests for SimaProCSVSource."""

from __future__ import annotations

import pytest

from lci_ignite.data.sources.simapro_csv import SimaProCSVSource


class TestSimaProSourceProperties:
    def test_source_type(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        assert source.source_type == "simapro_csv"

    def test_source_id_is_stable(self, simapro_sample_path):
        s1 = SimaProCSVSource(path=simapro_sample_path)
        s2 = SimaProCSVSource(path=simapro_sample_path)
        assert s1.source_id == s2.source_id
        assert s1.source_id.startswith("simapro_")

    def test_source_id_differs_for_different_files(self, simapro_sample_path, simapro_process_path):
        s1 = SimaProCSVSource(path=simapro_sample_path)
        s2 = SimaProCSVSource(path=simapro_process_path)
        assert s1.source_id != s2.source_id


class TestSimaProSourceMetadata:
    def test_metadata_contains_path(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        meta = source.get_metadata()
        assert meta["path"] == str(simapro_sample_path)
        assert meta["format"] == "simapro_csv"

    def test_metadata_includes_size(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        meta = source.get_metadata()
        assert "size_bytes" in meta
        assert meta["size_bytes"] > 0

    def test_metadata_includes_version(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        meta = source.get_metadata()
        assert "format_version" in meta
        assert meta["format_version"] == "9.x"

    def test_metadata_no_size_for_missing_file(self):
        source = SimaProCSVSource(path="/nonexistent/file.csv")
        meta = source.get_metadata()
        assert "size_bytes" not in meta


class TestSimaProSourceValidation:
    def test_validate_valid_file(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        assert source.validate() is True

    def test_validate_simple_process(self, simapro_process_path):
        source = SimaProCSVSource(path=simapro_process_path)
        assert source.validate() is True

    def test_validate_missing_file(self):
        source = SimaProCSVSource(path="/nonexistent/file.csv")
        assert source.validate() is False

    def test_validate_no_section_markers(self, simapro_malformed_path):
        source = SimaProCSVSource(path=simapro_malformed_path)
        assert source.validate() is False

    def test_validate_empty_file(self, tmp_path):
        empty = tmp_path / "empty.csv"
        empty.write_text("")
        source = SimaProCSVSource(path=empty)
        assert source.validate() is False

    def test_validate_too_short_file(self, tmp_path):
        short = tmp_path / "short.csv"
        short.write_text("a\nb\n")
        source = SimaProCSVSource(path=short)
        assert source.validate() is False


class TestSimaProSourceVersionDetection:
    def test_detect_v9(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        lines = source._read_lines()
        assert source._detect_format_version(lines) == "9.x"

    def test_detect_v8(self, tmp_path):
        content = "{SimaPro 8.4.0.0}\nProcess\nTest\n\nEnd\n"
        f = tmp_path / "v8.csv"
        f.write_text(content)
        source = SimaProCSVSource(path=f)
        lines = source._read_lines()
        assert source._detect_format_version(lines) == "8.x"

    def test_detect_unknown(self, simapro_process_path):
        source = SimaProCSVSource(path=simapro_process_path)
        lines = source._read_lines()
        assert source._detect_format_version(lines) == "unknown"


class TestSimaProSourceExtract:
    def test_extract_sample(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        result = source.extract()

        assert result.content_type == "structured"
        assert result.source is source
        assert "processes" in result.content
        assert "summary" in result.content

    def test_extract_processes(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        result = source.extract()
        processes = result.content["processes"]

        assert "Cement Production" in processes
        assert "Steel Manufacturing" in processes
        assert len(processes) == 2

    def test_extract_inputs_outputs(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        result = source.extract()
        cement = result.content["processes"]["Cement Production"]

        # Materials/fuels (3) + Electricity/heat (1) = 4 inputs
        assert len(cement["inputs"]) == 4
        # Products (1) + Emissions to air (3) + Emissions to water (1) = 5 outputs
        assert len(cement["outputs"]) == 5

    def test_extract_flow_data_structure(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        result = source.extract()
        cement_inputs = result.content["processes"]["Cement Production"]["inputs"]

        limestone = next(f for f in cement_inputs if f["flow"] == "Limestone")
        assert limestone["amount"] == 1200.5
        assert limestone["unit"] == "kg"
        assert limestone["section"] == "Materials/fuels"

    def test_extract_flow_with_comment(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        result = source.extract()
        cement_outputs = result.content["processes"]["Cement Production"]["outputs"]

        co2 = next(f for f in cement_outputs if f["flow"] == "Carbon dioxide")
        assert "comment" in co2
        assert "CO2 emission" in co2["comment"]

    def test_extract_sections_found(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        result = source.extract()
        sections = result.content["summary"]["sections_found"]

        assert "Materials/fuels" in sections
        assert "Emissions to air" in sections
        assert "Products" in sections

    def test_extract_simple_process(self, simapro_process_path):
        source = SimaProCSVSource(path=simapro_process_path)
        result = source.extract()
        processes = result.content["processes"]

        assert len(processes) == 1
        proc = list(processes.values())[0]
        assert len(proc["inputs"]) == 1  # Material X
        assert len(proc["outputs"]) == 2  # Product A + CO2

    def test_extract_metadata(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        result = source.extract()

        assert result.metadata["process_count"] == 2
        assert result.metadata["total_flows"] > 0
        assert result.metadata["format_version"] == "9.x"

    def test_extract_raises_for_invalid_file(self, simapro_malformed_path):
        source = SimaProCSVSource(path=simapro_malformed_path)
        with pytest.raises(ValueError, match="Invalid SimaPro CSV"):
            source.extract()

    def test_extract_raises_for_missing_file(self):
        source = SimaProCSVSource(path="/nonexistent/file.csv")
        with pytest.raises(ValueError, match="Invalid SimaPro CSV"):
            source.extract()


class TestSimaProSourceBlockParsing:
    def test_parse_blocks_handles_semicolons(self, tmp_path):
        content = (
            "Process\n"
            "My Process;\n"
            "Category type;material;\n"
            "\n"
            "Products\n"
            "Output;kg;100;;;\n"
            "\n"
            "Materials/fuels\n"
            "Input A;kg;50;;;\n"
            "\n"
            "End\n"
        )
        f = tmp_path / "semicolons.csv"
        f.write_text(content)
        source = SimaProCSVSource(path=f)
        result = source.extract()
        processes = result.content["processes"]
        assert len(processes) == 1

    def test_parse_blocks_comma_decimal(self, tmp_path):
        content = "Process\nComma Test\n\nMaterials/fuels\nWater;L;1000,5;;;\n\nEnd\n"
        f = tmp_path / "comma_decimal.csv"
        f.write_text(content)
        source = SimaProCSVSource(path=f)
        result = source.extract()
        proc = list(result.content["processes"].values())[0]
        assert proc["inputs"][0]["amount"] == 1000.5


class TestSimaProSourceInvoke:
    def test_invoke_calls_extract(self, simapro_sample_path):
        source = SimaProCSVSource(path=simapro_sample_path)
        result = source.invoke()

        assert result.content_type == "structured"
        assert "processes" in result.content
