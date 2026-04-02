"""Tests for mapping_profiles — load, save, and match profiles."""

import json
from unittest.mock import patch

import pytest

from lci_ignite.data.mapping_profiles import (
    _normalize_column_mapping,
    _sanitize_profile_name,
    _verify_column_positions,
    list_profiles,
    load_profile,
    match_profile,
    save_profile,
)

# ---------------------------------------------------------------------------
# Shared test profile data
# ---------------------------------------------------------------------------

TEST_PROFILE = {
    "profile_name": "test_company_abc",
    "company": "PT Test Corp",
    "scope": "Test Scope (Zone 1)",
    "sheet_name": "LDI-Test Corp Zone-00001",
    "expected_headers": [
        "No",
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
        "Test Scope",
        "Total Bulk",
    ],
    "column_mapping": {
        "process": {"index": 1, "header": "Process Title"},
        "category": {"index": 2, "header": "LDI Category"},
        "flow_name": {"index": 3, "header": "Material Title"},
        "direction": {"index": 6, "header": "Input or Output"},
        "unit": {"index": 11, "header": "Unit"},
        "scope_value": {"index": 17, "header": "Test Scope"},
        "total_bulk": {"index": 18, "header": "Total Bulk"},
    },
    "products": [
        {
            "name": "Produk A",
            "column": "per_product_a",
            "fu_column": "fu_a",
            "total_energy_mj": 1000000,
            "fu_unit_factor": 1000,
            "output_unit": "ton",
        },
    ],
    "category_mapping": {
        "Raw Material from Nature": "Bahan Baku",
        "Water": "Air",
        "Electricity": "Listrik",
        "Product": "Produk",
        "Hazardous Waste": "Limbah B3",
        "Air Emissions": "Emisi Udara",
    },
    "unit_conversions": [
        {"from_unit": "ton", "to_unit": "kg", "factor": 1000, "applies_to": ["Emisi Udara"]},
        {"from_unit": "barrel", "to_unit": "L", "factor": 158.987, "applies_to": ["Air"]},
        {"from_unit": "m3", "to_unit": "L", "factor": 1000, "applies_to": ["Air"]},
    ],
}


@pytest.fixture
def profile_dir(tmp_path):
    """Create a temp dir with a test profile saved to it."""
    path = tmp_path / "test_company_abc.json"
    path.write_text(json.dumps(TEST_PROFILE, indent=2), encoding="utf-8")
    return tmp_path


class TestListProfiles:
    """Tests for list_profiles()."""

    def test_returns_list(self, profile_dir):
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            result = list_profiles()
        assert isinstance(result, list)

    def test_includes_saved_profile(self, profile_dir):
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            profiles = list_profiles()
        names = [p["profile_name"] for p in profiles]
        assert "test_company_abc" in names

    def test_profile_has_metadata(self, profile_dir):
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            profiles = list_profiles()
        profile = next(p for p in profiles if p["profile_name"] == "test_company_abc")
        assert profile["company"] == "PT Test Corp"
        assert profile["file_name"] == "test_company_abc.json"

    def test_empty_directory(self, tmp_path):
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", tmp_path):
            result = list_profiles()
        assert result == []


class TestLoadProfile:
    """Tests for load_profile()."""

    def test_load_existing_profile(self, profile_dir):
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            profile = load_profile("test_company_abc")
        assert profile["profile_name"] == "test_company_abc"
        assert "column_mapping" in profile
        assert "products" in profile
        assert "category_mapping" in profile

    def test_load_nonexistent_profile(self, profile_dir):
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            with pytest.raises(FileNotFoundError):
                load_profile("nonexistent_company")

    def test_column_mapping_structure(self, profile_dir):
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            profile = load_profile("test_company_abc")
        cm = profile["column_mapping"]
        required_keys = {"process", "category", "flow_name", "direction", "unit", "scope_value"}
        assert required_keys.issubset(set(cm.keys()))

    def test_products_structure(self, profile_dir):
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            profile = load_profile("test_company_abc")
        products = profile["products"]
        assert len(products) == 1
        assert products[0]["name"] == "Produk A"
        assert "total_energy_mj" in products[0]
        assert "column" in products[0]

    def test_unit_conversions_present(self, profile_dir):
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            profile = load_profile("test_company_abc")
        conversions = profile["unit_conversions"]
        assert len(conversions) >= 3
        for conv in conversions:
            assert "from_unit" in conv
            assert "to_unit" in conv
            assert "factor" in conv


class TestNormalizeColumnMapping:
    """Tests for _normalize_column_mapping() — handles LLM shorthand format."""

    def test_int_values_converted(self):
        profile = {"column_mapping": {"process": 0, "category": 1, "unit": 10}}
        result = _normalize_column_mapping(profile)
        assert result["column_mapping"]["process"] == {"index": 0}
        assert result["column_mapping"]["category"] == {"index": 1}
        assert result["column_mapping"]["unit"] == {"index": 10}

    def test_dict_values_unchanged(self):
        profile = {"column_mapping": {"process": {"index": 0, "header": "P"}}}
        result = _normalize_column_mapping(profile)
        assert result["column_mapping"]["process"] == {"index": 0, "header": "P"}

    def test_mixed_values(self):
        profile = {"column_mapping": {"process": 0, "category": {"index": 1}}}
        result = _normalize_column_mapping(profile)
        assert result["column_mapping"]["process"] == {"index": 0}
        assert result["column_mapping"]["category"] == {"index": 1}

    def test_load_profile_normalizes_ints(self, tmp_path):
        """Profiles saved with int column_mapping should be normalized on load."""
        int_profile = {
            "profile_name": "int_format",
            "column_mapping": {"process": 0, "category": 1, "unit": 5},
        }
        path = tmp_path / "int_format.json"
        path.write_text(json.dumps(int_profile), encoding="utf-8")

        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", tmp_path):
            loaded = load_profile("int_format")

        # Should be normalized to dict format
        assert loaded["column_mapping"]["process"] == {"index": 0}
        assert loaded["column_mapping"]["unit"] == {"index": 5}

    def test_match_profile_normalizes_ints(self, tmp_path):
        """Matched profile with int column_mapping should be normalized."""
        int_profile = {
            "profile_name": "int_match",
            "sheet_name": "Test Sheet",
            "column_mapping": {"process": 0, "category": 1},
            "expected_headers": [],
        }
        path = tmp_path / "int_match.json"
        path.write_text(json.dumps(int_profile), encoding="utf-8")

        excel_profile = {"sheet_names": ["Test Sheet"], "sheets": {}}
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", tmp_path):
            matched = match_profile(excel_profile)

        assert matched is not None
        assert matched["column_mapping"]["process"] == {"index": 0}


class TestSanitizeProfileName:
    """Tests for _sanitize_profile_name() — prevents path traversal."""

    def test_normal_name(self):
        assert _sanitize_profile_name("pertamina_pep_tanjung") == "pertamina_pep_tanjung"

    def test_path_traversal_dots(self):
        result = _sanitize_profile_name("../../etc/passwd")
        assert "/" not in result
        assert ".." not in result

    def test_path_traversal_backslash(self):
        result = _sanitize_profile_name("..\\..\\windows\\system32")
        assert "\\" not in result

    def test_spaces_and_special_chars(self):
        result = _sanitize_profile_name("PT Pupuk (Pusri) - Zone 1")
        assert " " not in result
        assert "(" not in result
        assert result == "pt_pupuk_pusri_-_zone_1"

    def test_empty_string(self):
        assert _sanitize_profile_name("") == "auto_generated"

    def test_only_special_chars(self):
        assert _sanitize_profile_name("../../../") == "auto_generated"

    def test_uppercase_lowered(self):
        assert _sanitize_profile_name("MyProfile") == "myprofile"

    def test_save_profile_sanitizes_name(self, tmp_path):
        """save_profile should sanitize the name before writing."""
        profile = {"profile_name": "../../evil", "column_mapping": {}}
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", tmp_path):
            path = save_profile("../../evil", profile)
        # File should be saved with sanitized name, inside tmp_path
        assert path.parent == tmp_path
        assert ".." not in path.name

    def test_save_profile_stays_in_dir(self, tmp_path):
        """Resolved path must stay within PROFILES_DIR."""
        profile = {"profile_name": "safe_name", "column_mapping": {}}
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", tmp_path):
            path = save_profile("safe_name", profile)
        assert str(path.resolve()).startswith(str(tmp_path.resolve()))


class TestSaveProfile:
    """Tests for save_profile()."""

    def test_save_and_load_roundtrip(self, tmp_path):
        test_profile = {
            "profile_name": "roundtrip_company",
            "company": "Roundtrip Corp",
            "scope": "Test Scope",
            "column_mapping": {"process": {"index": 0}},
        }

        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", tmp_path):
            save_profile("roundtrip_company", test_profile)
            loaded = load_profile("roundtrip_company")
        assert loaded["profile_name"] == "roundtrip_company"
        assert loaded["company"] == "Roundtrip Corp"


class TestMatchProfile:
    """Tests for match_profile()."""

    def test_match_by_sheet_name(self, profile_dir):
        excel_profile = {
            "sheet_names": ["LDI-Test Corp Zone-00001", "Other Sheet"],
            "sheets": {},
        }
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            result = match_profile(excel_profile)
        assert result is not None
        assert result["profile_name"] == "test_company_abc"

    def test_no_match_unknown_sheets(self, profile_dir):
        excel_profile = {
            "sheet_names": ["Unknown Sheet"],
            "sheets": {
                "Unknown Sheet": {
                    "headers": ["Col A", "Col B", "Col C"],
                }
            },
        }
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            result = match_profile(excel_profile)
        assert result is None

    def test_match_by_header_overlap(self, profile_dir):
        """Profile matches when >80% of expected headers overlap at correct positions."""
        headers = [None] * 19
        headers[0] = "No"
        headers[1] = "Process Title"
        headers[2] = "LDI Category"
        headers[3] = "Material Title"
        headers[4] = "Produced From"
        headers[5] = "Material Composition"
        headers[6] = "Input or Output"
        headers[7] = "Data Source"
        headers[8] = "Data Source Reference"
        headers[9] = "Sample Size"
        headers[10] = "Notes"
        headers[11] = "Unit"
        headers[12] = "PIC"
        headers[13] = "Abbreviation"
        headers[14] = "Parameter"
        headers[15] = "Is Amount Balanced"
        headers[16] = "Unallocated Amount Notes"
        headers[17] = "Test Scope"
        headers[18] = "Total Bulk"
        excel_profile = {
            "sheet_names": ["Different Name"],
            "sheets": {
                "Different Name": {
                    "headers": headers,
                }
            },
        }
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            result = match_profile(excel_profile)
        assert result is not None
        assert result["profile_name"] == "test_company_abc"

    def test_no_match_low_header_overlap(self, profile_dir):
        """No match when header overlap is <80%."""
        excel_profile = {
            "sheet_names": ["Different"],
            "sheets": {
                "Different": {
                    "headers": ["No", "Process Title", "Category"],
                }
            },
        }
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            result = match_profile(excel_profile)
        assert result is None

    def test_no_match_shifted_column_positions(self, profile_dir):
        """Reject profile when headers match but column positions are shifted."""
        excel_profile = {
            "sheet_names": ["LDI-Other"],
            "sheets": {
                "LDI-Other": {
                    "headers": [
                        # No "No" at index 0 -- everything shifted left by 1
                        "Process Title",  # idx 0 (profile expects at 1)
                        "LDI Category",  # idx 1 (profile expects at 2)
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
                        "Test Scope",
                        "Total Bulk",
                    ],
                }
            },
        }
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            result = match_profile(excel_profile)
        # Headers overlap >80% but column positions don't match
        assert result is None

    def test_no_match_empty_dir(self, tmp_path):
        """No profiles saved → no match."""
        excel_profile = {
            "sheet_names": ["Any Sheet"],
            "sheets": {},
        }
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", tmp_path):
            result = match_profile(excel_profile)
        assert result is None


class TestVerifyColumnPositions:
    """Tests for _verify_column_positions()."""

    def test_all_positions_match(self):
        headers = ["No", "Process Title", "LDI Category"]
        col_map = {
            "process": {"index": 1, "header": "Process Title"},
            "category": {"index": 2, "header": "LDI Category"},
        }
        assert _verify_column_positions(headers, col_map) is True

    def test_all_positions_shifted(self):
        headers = ["Process Title", "LDI Category", "Material Title"]
        col_map = {
            "process": {"index": 1, "header": "Process Title"},
            "category": {"index": 2, "header": "LDI Category"},
        }
        assert _verify_column_positions(headers, col_map) is False

    def test_no_header_in_spec(self):
        """Entries without 'header' key are skipped."""
        headers = ["A", "B"]
        col_map = {"field": {"index": 0}}
        assert _verify_column_positions(headers, col_map) is True

    def test_empty_column_mapping(self):
        assert _verify_column_positions(["A"], {}) is True

    def test_index_out_of_range(self):
        headers = ["A", "B"]
        col_map = {"field": {"index": 10, "header": "X"}}
        assert _verify_column_positions(headers, col_map) is False
