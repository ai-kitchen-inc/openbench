"""Tests for generate_mapping_profile tool (Layer 3 — LLM auto-mapping)."""

import json
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pytest

from lci_ignite.intelligence.tools import (
    _normalize_generated_profile,
    _validate_generated_profile,
    clear_pipeline_data,
    clear_render_items,
    generate_mapping_profile,
)


@pytest.fixture(autouse=True)
def _clear():
    clear_render_items()
    clear_pipeline_data()
    yield
    clear_render_items()
    clear_pipeline_data()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_PROFILE = {
    "profile_name": "pusri_pupuk_urea",
    "company": "PT Pupuk Sriwidjaja",
    "scope": "Pusri IB",
    "sheet_name": "LDI-Pupuk Sriwidjaja (Pusri)-00",
    "expected_headers": [
        "Process Title",
        "LDI Category",
        "Material Title",
        "Produced From",
        "Material Composition",
        "Input or Output",
        "Unit",
    ],
    "column_mapping": {
        "process": {"index": 0, "header": "Process Title"},
        "category": {"index": 1, "header": "LDI Category"},
        "flow_name": {"index": 2, "header": "Material Title"},
        "direction": {"index": 5, "header": "Input or Output"},
        "unit": {"index": 10, "header": "Unit"},
        "scope_value": {"index": 16, "header": "Pusri IB"},
        "total_bulk": {"index": 17, "header": "Total Bulk"},
    },
    "header_row": 1,
    "products": [
        {
            "name": "Pupuk Urea",
            "column": "per_product_urea",
            "fu_column": "fu_urea",
            "total_energy_mj": 0,
            "fu_unit_factor": 0,
            "output_unit": "Ton/year",
        },
    ],
    "category_mapping": {
        "Raw Material from Nature": "Bahan Baku",
        "Water": "Air",
        "Solid Supporting Material": "Bahan Pendukung Padatan",
        "Liquid Supporting Material": "Bahan Pendukung Cairan",
        "Electricity": "Listrik",
        "Product": "Produk",
        "Hazardous Waste": "Limbah B3",
        "Air Emissions": "Emisi Udara",
    },
    "unit_conversions": [
        {"from_unit": "ton", "to_unit": "kg", "factor": 1000, "applies_to": ["Emisi Udara"]},
    ],
    "study_period": {"years": 1, "description": "Annual study period"},
}


def _create_pusri_xlsx(path: Path):
    """Create a Pusri-like Excel file (no 'No' column, single product)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "LDI-Pupuk Sriwidjaja (Pusri)-00"
    headers = [
        "Process Title",
        "LDI Category",
        "Material Title",
        "Produced From",
        "Material Composition",
        "Input or Output",
        "Data Source",
        "Data Source Reference",
        "Sample Size",
        "Notes",
        "Unit",
        "PIC",
        "Abbreviation",
        "Parameter",
        "Is Amount Balanced",
        "Unallocated Amount Notes",
        "Pusri IB",
        "Total Bulk",
    ]
    ws.append(headers)
    ws.append(
        [
            "Feed Treating Unit",
            "Solid Supporting Material",
            "Catalyst",
            "CoMo",
            None,
            "Input",
            None,
            None,
            None,
            None,
            "ton",
            None,
            None,
            None,
            None,
            None,
            2673.0,
            2673.0,
        ]
    )
    ws.append(
        [
            "Feed Treating Unit",
            "Raw Material from Nature",
            "Natural Gas",
            None,
            None,
            "Input",
            None,
            None,
            None,
            None,
            "Ton/year",
            None,
            None,
            None,
            None,
            None,
            186614.0,
            186614.0,
        ]
    )
    wb.save(str(path))


# ---------------------------------------------------------------------------
# Tests: _validate_generated_profile
# ---------------------------------------------------------------------------


class TestValidateGeneratedProfile:
    def test_valid_profile(self):
        errors = _validate_generated_profile(VALID_PROFILE)
        assert errors == []

    def test_missing_profile_name(self):
        profile = {k: v for k, v in VALID_PROFILE.items() if k != "profile_name"}
        errors = _validate_generated_profile(profile)
        assert any("profile_name" in e for e in errors)

    def test_missing_column_mapping(self):
        profile = {k: v for k, v in VALID_PROFILE.items() if k != "column_mapping"}
        errors = _validate_generated_profile(profile)
        assert any("column_mapping" in e for e in errors)

    def test_missing_required_columns(self):
        profile = dict(VALID_PROFILE)
        profile["column_mapping"] = {"process": {"index": 0}}
        errors = _validate_generated_profile(profile)
        assert any("missing required fields" in e for e in errors)

    def test_column_missing_index(self):
        profile = dict(VALID_PROFILE)
        profile["column_mapping"] = dict(VALID_PROFILE["column_mapping"])
        profile["column_mapping"]["process"] = {"header": "Process Title"}  # no index
        errors = _validate_generated_profile(profile)
        assert any("missing 'index'" in e for e in errors)

    def test_products_not_list(self):
        profile = dict(VALID_PROFILE)
        profile["products"] = "not a list"
        errors = _validate_generated_profile(profile)
        assert any("products must be a list" in e for e in errors)

    def test_product_missing_name(self):
        profile = dict(VALID_PROFILE)
        profile["products"] = [{"column": "x"}]
        errors = _validate_generated_profile(profile)
        assert any("missing 'name'" in e for e in errors)

    def test_not_a_dict(self):
        errors = _validate_generated_profile("not a dict")
        assert errors == ["Profile must be a JSON object"]


# ---------------------------------------------------------------------------
# Tests: _normalize_generated_profile
# ---------------------------------------------------------------------------


class TestNormalizeGeneratedProfile:
    def test_int_column_mapping(self):
        """LLM returns column_mapping values as ints → normalized to dicts."""
        profile = {
            "profile_name": "test",
            "sheet_name": "Sheet1",
            "column_mapping": {
                "process": 0,
                "category": 1,
                "flow_name": 2,
                "direction": 5,
                "unit": 10,
            },
        }
        result = _normalize_generated_profile(profile)
        assert result["column_mapping"]["process"] == {"index": 0}
        assert result["column_mapping"]["unit"] == {"index": 10}

    def test_dict_column_mapping_unchanged(self):
        """Already-correct format should pass through unchanged."""
        profile = {
            "profile_name": "test",
            "column_mapping": {
                "process": {"index": 0, "header": "Process Title"},
            },
        }
        result = _normalize_generated_profile(profile)
        assert result["column_mapping"]["process"] == {"index": 0, "header": "Process Title"}

    def test_mixed_column_mapping(self):
        """Mix of int and dict values → all normalized."""
        profile = {
            "profile_name": "test",
            "column_mapping": {
                "process": 0,
                "category": {"index": 1, "header": "LDI Category"},
                "flow_name": 2,
            },
        }
        result = _normalize_generated_profile(profile)
        assert result["column_mapping"]["process"] == {"index": 0}
        assert result["column_mapping"]["category"] == {"index": 1, "header": "LDI Category"}
        assert result["column_mapping"]["flow_name"] == {"index": 2}

    def test_products_get_defaults(self):
        """Products should get default total_energy_mj, fu_unit_factor, output_unit."""
        profile = {
            "profile_name": "test",
            "column_mapping": {},
            "products": [{"name": "Urea"}],
        }
        result = _normalize_generated_profile(profile)
        assert result["products"][0]["total_energy_mj"] == 0
        assert result["products"][0]["fu_unit_factor"] == 0
        assert result["products"][0]["output_unit"] == ""

    def test_not_a_dict_passthrough(self):
        """Non-dict input should pass through (validation catches it)."""
        assert _normalize_generated_profile("not a dict") == "not a dict"

    def test_successful_generation_with_int_mapping(self, tmp_path):
        """End-to-end: LLM returns int column_mapping → still works."""
        xlsx = tmp_path / "test.xlsx"
        _create_pusri_xlsx(xlsx)

        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()

        # LLM returns shorthand int format
        int_profile = dict(VALID_PROFILE)
        int_profile["column_mapping"] = {
            "process": 0,
            "category": 1,
            "flow_name": 2,
            "direction": 5,
            "unit": 10,
            "scope_value": 16,
            "total_bulk": 17,
        }

        with (
            patch(
                "lci_ignite.intelligence.tools._call_llm_for_profile",
                return_value=(json.dumps(int_profile), None),
            ),
            patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir),
        ):
            result = json.loads(generate_mapping_profile(str(xlsx)))

        assert result["status"] == "profile_generated"

        # Verify saved profile has normalized column_mapping
        saved = json.loads((profile_dir / f"{result['profile_name']}.json").read_text())
        assert saved["column_mapping"]["process"] == {"index": 0}


# ---------------------------------------------------------------------------
# Tests: generate_mapping_profile
# ---------------------------------------------------------------------------


class TestGenerateMappingProfile:
    def test_file_not_found(self):
        result = json.loads(generate_mapping_profile("/nonexistent/file.xlsx"))
        assert "error" in result

    def test_successful_generation(self, tmp_path):
        """Mock LLM returns valid profile → saved and returned."""
        xlsx = tmp_path / "test.xlsx"
        _create_pusri_xlsx(xlsx)

        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()

        with (
            patch(
                "lci_ignite.intelligence.tools._call_llm_for_profile",
                return_value=(json.dumps(VALID_PROFILE), None),
            ),
            patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir),
        ):
            result = json.loads(generate_mapping_profile(str(xlsx)))

        assert result["status"] == "profile_generated"
        assert result["profile_name"] == "pusri_pupuk_urea"
        assert "Pupuk Urea" in result["products"]

        # Verify profile was saved to disk
        saved_path = profile_dir / "pusri_pupuk_urea.json"
        assert saved_path.exists()
        saved = json.loads(saved_path.read_text())
        assert saved["company"] == "PT Pupuk Sriwidjaja"

    def test_llm_error(self, tmp_path):
        """LLM returns an error → propagated."""
        xlsx = tmp_path / "test.xlsx"
        _create_pusri_xlsx(xlsx)

        with patch(
            "lci_ignite.intelligence.tools._call_llm_for_profile",
            return_value=("", "GOOGLE_API_KEY not set. Cannot generate profile."),
        ):
            result = json.loads(generate_mapping_profile(str(xlsx)))

        assert "error" in result
        assert "GOOGLE_API_KEY" in result["error"]

    def test_invalid_llm_json(self, tmp_path):
        """LLM returns invalid JSON → error with raw response."""
        xlsx = tmp_path / "test.xlsx"
        _create_pusri_xlsx(xlsx)

        with patch(
            "lci_ignite.intelligence.tools._call_llm_for_profile",
            return_value=("This is not JSON at all", None),
        ):
            result = json.loads(generate_mapping_profile(str(xlsx)))

        assert "error" in result
        assert "invalid JSON" in result["error"]

    def test_llm_returns_invalid_profile(self, tmp_path):
        """LLM returns valid JSON but missing required fields → validation error."""
        xlsx = tmp_path / "test.xlsx"
        _create_pusri_xlsx(xlsx)

        bad_profile = {"some_field": "some_value"}

        with patch(
            "lci_ignite.intelligence.tools._call_llm_for_profile",
            return_value=(json.dumps(bad_profile), None),
        ):
            result = json.loads(generate_mapping_profile(str(xlsx)))

        assert "error" in result
        assert "validation_errors" in result

    def test_path_traversal_sanitized(self, tmp_path):
        """LLM returns profile_name with path traversal → sanitized before save."""
        xlsx = tmp_path / "test.xlsx"
        _create_pusri_xlsx(xlsx)

        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()

        evil_profile = dict(VALID_PROFILE)
        evil_profile["profile_name"] = "../../etc/evil_payload"

        with (
            patch(
                "lci_ignite.intelligence.tools._call_llm_for_profile",
                return_value=(json.dumps(evil_profile), None),
            ),
            patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir),
        ):
            result = json.loads(generate_mapping_profile(str(xlsx)))

        assert result["status"] == "profile_generated"
        # Name should be sanitized — no path separators
        assert "/" not in result["profile_name"]
        assert ".." not in result["profile_name"]
        # File saved inside profile_dir, not escaped
        saved_files = list(profile_dir.glob("*.json"))
        assert len(saved_files) == 1
        assert saved_files[0].parent == profile_dir


# ---------------------------------------------------------------------------
# Tests: parse_ldi_sheet auto-trigger
# ---------------------------------------------------------------------------


class TestParseLdiSheetAutoTrigger:
    """Test that parse_ldi_sheet with 'auto' triggers generate_mapping_profile."""

    def test_auto_triggers_generation_on_no_match(self, tmp_path):
        """When no profile matches, parse_ldi_sheet should auto-generate one."""
        from lci_ignite.intelligence.tools import parse_ldi_sheet

        xlsx = tmp_path / "test.xlsx"
        _create_pusri_xlsx(xlsx)

        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()

        with (
            patch(
                "lci_ignite.intelligence.tools._call_llm_for_profile",
                return_value=(json.dumps(VALID_PROFILE), None),
            ),
            patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir),
        ):
            result = parse_ldi_sheet(str(xlsx), "auto")

        # Should have parsed successfully (not an error)
        parsed = json.loads(result)
        assert parsed["status"] == "parsed"
        assert parsed["total_flows"] > 0

    def test_auto_returns_error_when_generation_fails(self, tmp_path):
        """When LLM fails, parse_ldi_sheet should return a clear error."""
        from lci_ignite.intelligence.tools import parse_ldi_sheet

        xlsx = tmp_path / "test.xlsx"
        _create_pusri_xlsx(xlsx)

        empty_dir = tmp_path / "empty_profiles"
        empty_dir.mkdir()

        with (
            patch(
                "lci_ignite.intelligence.tools._call_llm_for_profile",
                return_value=("", "GOOGLE_API_KEY not set. Cannot generate profile."),
            ),
            patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", empty_dir),
        ):
            result = parse_ldi_sheet(str(xlsx), "auto")

        assert "Error" in result
        assert "auto-generation failed" in result
