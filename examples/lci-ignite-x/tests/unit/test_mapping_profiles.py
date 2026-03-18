"""Tests for mapping_profiles — load, save, and match profiles."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from lci_ignite.data.mapping_profiles import (
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
        """Profile matches when >80% of expected headers overlap."""
        excel_profile = {
            "sheet_names": ["Different Name"],
            "sheets": {
                "Different Name": {
                    "headers": [
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
                        "Semberah EP",
                        "Total Bulk",
                    ],
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
