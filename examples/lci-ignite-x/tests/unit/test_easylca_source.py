"""Unit tests for EasyLCASource."""

from __future__ import annotations

import pytest

from lci_ignite.data.sources.easylca import EasyLCASource


class TestEasyLCASourceProperties:
    def test_source_type(self, easylca_sample_path):
        source = EasyLCASource(path=easylca_sample_path)
        assert source.source_type == "easylca_csv"

    def test_source_id_is_stable(self, easylca_sample_path):
        s1 = EasyLCASource(path=easylca_sample_path)
        s2 = EasyLCASource(path=easylca_sample_path)
        assert s1.source_id == s2.source_id
        assert s1.source_id.startswith("easylca_")

    def test_source_id_differs_for_different_files(self, easylca_sample_path, easylca_minimal_path):
        s1 = EasyLCASource(path=easylca_sample_path)
        s2 = EasyLCASource(path=easylca_minimal_path)
        assert s1.source_id != s2.source_id


class TestEasyLCASourceMetadata:
    def test_metadata_contains_path(self, easylca_sample_path):
        source = EasyLCASource(path=easylca_sample_path)
        meta = source.get_metadata()
        assert meta["path"] == str(easylca_sample_path)
        assert meta["format"] == "easylca_csv"
        assert meta["encoding"] == "utf-8"

    def test_metadata_includes_size_for_existing_file(self, easylca_sample_path):
        source = EasyLCASource(path=easylca_sample_path)
        meta = source.get_metadata()
        assert "size_bytes" in meta
        assert meta["size_bytes"] > 0

    def test_metadata_no_size_for_missing_file(self):
        source = EasyLCASource(path="/nonexistent/file.csv")
        meta = source.get_metadata()
        assert "size_bytes" not in meta


class TestEasyLCASourceValidation:
    def test_validate_valid_file(self, easylca_sample_path):
        source = EasyLCASource(path=easylca_sample_path)
        assert source.validate() is True

    def test_validate_minimal_file(self, easylca_minimal_path):
        source = EasyLCASource(path=easylca_minimal_path)
        assert source.validate() is True

    def test_validate_missing_file(self):
        source = EasyLCASource(path="/nonexistent/file.csv")
        assert source.validate() is False

    def test_validate_missing_columns(self, easylca_malformed_path):
        source = EasyLCASource(path=easylca_malformed_path)
        assert source.validate() is False

    def test_validate_empty_file(self, tmp_path):
        empty = tmp_path / "empty.csv"
        empty.write_text("")
        source = EasyLCASource(path=empty)
        assert source.validate() is False


class TestEasyLCASourceExtract:
    def test_extract_sample(self, easylca_sample_path):
        source = EasyLCASource(path=easylca_sample_path)
        result = source.extract()

        assert result.content_type == "structured"
        assert result.source is source

        content = result.content
        assert "processes" in content
        assert "summary" in content

    def test_extract_processes(self, easylca_sample_path):
        source = EasyLCASource(path=easylca_sample_path)
        result = source.extract()
        processes = result.content["processes"]

        assert "Cement Production" in processes
        assert "Steel Manufacturing" in processes
        assert "Transport" in processes
        assert len(processes) == 3

    def test_extract_inputs_outputs_separated(self, easylca_sample_path):
        source = EasyLCASource(path=easylca_sample_path)
        result = source.extract()
        cement = result.content["processes"]["Cement Production"]

        assert len(cement["inputs"]) == 4  # Limestone, Clay, Electricity, Natural gas
        assert len(cement["outputs"]) == 4  # CO2, SO2, NOx, Cement

    def test_extract_flow_data_structure(self, easylca_sample_path):
        source = EasyLCASource(path=easylca_sample_path)
        result = source.extract()
        cement_inputs = result.content["processes"]["Cement Production"]["inputs"]

        limestone = next(f for f in cement_inputs if f["flow"] == "Limestone")
        assert limestone["category"] == "Raw materials"
        assert limestone["amount"] == 1200.5
        assert limestone["unit"] == "kg"

    def test_extract_optional_compartment(self, easylca_sample_path):
        source = EasyLCASource(path=easylca_sample_path)
        result = source.extract()
        cement_outputs = result.content["processes"]["Cement Production"]["outputs"]

        co2 = next(f for f in cement_outputs if f["flow"] == "CO2")
        assert co2.get("compartment") == "Air"

    def test_extract_optional_sub_compartment(self, easylca_sample_path):
        source = EasyLCASource(path=easylca_sample_path)
        result = source.extract()
        transport_outputs = result.content["processes"]["Transport"]["outputs"]

        pm25 = next(f for f in transport_outputs if f["flow"] == "PM2.5")
        assert pm25.get("sub_compartment") == "Low population density"

    def test_extract_summary(self, easylca_sample_path):
        source = EasyLCASource(path=easylca_sample_path)
        result = source.extract()
        summary = result.content["summary"]

        assert summary["total_rows"] == 18
        assert len(summary["processes"]) == 3
        assert "Cement Production" in summary["processes"]
        assert len(summary["categories"]) > 0

    def test_extract_metadata(self, easylca_sample_path):
        source = EasyLCASource(path=easylca_sample_path)
        result = source.extract()

        assert result.metadata["rows_parsed"] == 18
        assert result.metadata["process_count"] == 3
        assert "categories" in result.metadata

    def test_extract_minimal(self, easylca_minimal_path):
        source = EasyLCASource(path=easylca_minimal_path)
        result = source.extract()
        processes = result.content["processes"]

        assert "Single Process" in processes
        assert len(processes["Single Process"]["inputs"]) == 1
        assert len(processes["Single Process"]["outputs"]) == 1

    def test_extract_raises_for_invalid_file(self, easylca_malformed_path):
        source = EasyLCASource(path=easylca_malformed_path)
        with pytest.raises(ValueError, match="Invalid easyLCA CSV"):
            source.extract()

    def test_extract_raises_for_missing_file(self):
        source = EasyLCASource(path="/nonexistent/file.csv")
        with pytest.raises(ValueError, match="Invalid easyLCA CSV"):
            source.extract()


class TestEasyLCASourceEncoding:
    def test_custom_encoding(self, tmp_path):
        csv_content = (
            "Process,Flow,Category,Amount,Unit,Direction\n"
            "Proc\u00e9ss,Fl\u00f6w,Cat,100.0,kg,Input\n"
        )
        csv_file = tmp_path / "encoded.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        source = EasyLCASource(path=csv_file, encoding="utf-8")
        result = source.extract()
        processes = result.content["processes"]
        assert "Proc\u00e9ss" in processes


class TestEasyLCASourceInvoke:
    def test_invoke_calls_extract(self, easylca_sample_path):
        source = EasyLCASource(path=easylca_sample_path)
        result = source.invoke()

        assert result.content_type == "structured"
        assert "processes" in result.content
