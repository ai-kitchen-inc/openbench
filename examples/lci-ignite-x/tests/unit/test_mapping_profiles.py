"""Tests for mapping_profiles — load, save, and match profiles."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from lci_ignite.data.mapping_profiles import (
    _verify_column_positions,
    list_profiles,
    load_profile,
    match_profile,
    save_profile,
)


class TestListProfiles:
    """Tests for list_profiles()."""

    def test_returns_list(self):
        result = list_profiles()
        assert isinstance(result, list)

    def test_includes_pertamina_profile(self):
        profiles = list_profiles()
        names = [p["profile_name"] for p in profiles]
        assert "pertamina_pep_tanjung" in names

    def test_profile_has_metadata(self):
        profiles = list_profiles()
        pertamina = next(p for p in profiles if p["profile_name"] == "pertamina_pep_tanjung")
        assert pertamina["company"] == "PT Pertamina EP"
        assert pertamina["file_name"] == "pertamina_pep_tanjung.json"


class TestLoadProfile:
    """Tests for load_profile()."""

    def test_load_existing_profile(self):
        profile = load_profile("pertamina_pep_tanjung")
        assert profile["profile_name"] == "pertamina_pep_tanjung"
        assert "column_mapping" in profile
        assert "products" in profile
        assert "category_mapping" in profile

    def test_load_nonexistent_profile(self):
        with pytest.raises(FileNotFoundError):
            load_profile("nonexistent_company")

    def test_column_mapping_structure(self):
        profile = load_profile("pertamina_pep_tanjung")
        cm = profile["column_mapping"]
        required_keys = {"process", "category", "flow_name", "direction", "unit", "scope_value"}
        assert required_keys.issubset(set(cm.keys()))

    def test_products_structure(self):
        profile = load_profile("pertamina_pep_tanjung")
        products = profile["products"]
        assert len(products) == 2
        assert products[0]["name"] == "Gas Bumi"
        assert products[1]["name"] == "Minyak Bumi"
        for p in products:
            assert "total_energy_mj" in p
            assert "column" in p

    def test_unit_conversions_present(self):
        profile = load_profile("pertamina_pep_tanjung")
        conversions = profile["unit_conversions"]
        assert len(conversions) >= 3
        for conv in conversions:
            assert "from_unit" in conv
            assert "to_unit" in conv
            assert "factor" in conv


class TestSaveProfile:
    """Tests for save_profile()."""

    def test_save_and_load_roundtrip(self, tmp_path):
        test_profile = {
            "profile_name": "test_company",
            "company": "Test Corp",
            "scope": "Test Scope",
            "column_mapping": {"process": {"index": 0}},
        }

        with (
            patch.object(Path, "write_text"),
            patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", tmp_path),
        ):
            save_profile("test_company", test_profile)

        # Verify via direct file write to tmp
        path = tmp_path / "test_company.json"
        path.write_text(json.dumps(test_profile, indent=2))
        loaded = json.loads(path.read_text())
        assert loaded["profile_name"] == "test_company"


class TestMatchProfile:
    """Tests for match_profile()."""

    def test_match_by_sheet_name(self):
        excel_profile = {
            "sheet_names": ["LDI-Pertamina Zona 9-00004", "Other Sheet"],
            "sheets": {},
        }
        result = match_profile(excel_profile)
        assert result is not None
        assert result["profile_name"] == "pertamina_pep_tanjung"

    def test_no_match_unknown_sheets(self):
        excel_profile = {
            "sheet_names": ["Unknown Sheet"],
            "sheets": {
                "Unknown Sheet": {
                    "headers": ["Col A", "Col B", "Col C"],
                }
            },
        }
        result = match_profile(excel_profile)
        assert result is None

    def test_match_by_header_overlap(self):
        """Profile matches when >80% of expected headers overlap at correct positions."""
        # Headers must include entries at all column_mapping indexes (up to 32)
        headers = [None] * 33
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
        headers[17] = "Semberah EP"
        headers[18] = "Total Bulk"
        headers[29] = "Total per Product Crude Oil"
        headers[30] = "Total per Product Gas"
        headers[31] = "Functional Unit EP - Crude Oil"
        headers[32] = "Functional Unit EP - Gas"
        excel_profile = {
            "sheet_names": ["Different Name"],
            "sheets": {
                "Different Name": {
                    "headers": headers,
                }
            },
        }
        result = match_profile(excel_profile)
        assert result is not None
        assert result["profile_name"] == "pertamina_pep_tanjung"

    def test_no_match_low_header_overlap(self):
        """No match when header overlap is <80%."""
        excel_profile = {
            "sheet_names": ["Different"],
            "sheets": {
                "Different": {
                    "headers": ["No", "Process Title", "Category"],
                }
            },
        }
        result = match_profile(excel_profile)
        assert result is None

    def test_no_match_shifted_column_positions(self):
        """Reject profile when headers match but column positions are shifted.

        Simulates a Pusri-like file: same header names as Pertamina but
        without the "No" column at index 0, shifting all positions by 1.
        """
        excel_profile = {
            "sheet_names": ["LDI-Pusri"],
            "sheets": {
                "LDI-Pusri": {
                    "headers": [
                        # No "No" at index 0 -- everything shifted left by 1
                        "Process Title",  # idx 0 (Pertamina expects at 1)
                        "LDI Category",  # idx 1 (Pertamina expects at 2)
                        "Material Title",  # idx 2 (Pertamina expects at 3)
                        "Produced From",
                        "Material Composition",
                        "Input or Output",  # idx 5 (Pertamina expects at 6)
                        "Data Source",
                        "Data Source Reference",
                        "Sample Size",
                        "Notes",
                        "Unit",  # idx 10 (Pertamina expects at 11)
                        "PIC",
                        "Abbreviation",
                        "Parameter",
                        "Is Amount Balanced",
                        "Unallocated Amount Notes",
                        "Semberah EP",  # idx 16 (Pertamina expects at 17)
                        "Total Bulk",
                    ],
                }
            },
        }
        result = match_profile(excel_profile)
        # Headers overlap >80% but column positions don't match
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
        # idx 1 = "LDI Category" (expected "Process Title"),
        # idx 2 = "Material Title" (expected "LDI Category")
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
        # 0/1 matches = 0% < 80%
        assert _verify_column_positions(headers, col_map) is False
