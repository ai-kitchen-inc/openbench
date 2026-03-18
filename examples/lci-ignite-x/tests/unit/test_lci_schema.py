"""Tests for lci_schema module — categories, normalization, and validation."""

from lci_ignite.data.lci_schema import (
    EMISSION_DETAIL_SECTIONS,
    EXCLUDED_LDI_CATEGORIES,
    HELPER_LDI_CATEGORIES,
    INPUT_CATEGORIES,
    IO_TABLE_SECTION_ORDER,
    OUTPUT_CATEGORIES,
    STANDARD_CATEGORIES,
    category_direction,
    is_excluded_ldi,
    is_helper_ldi,
    normalize_category,
    normalize_unit,
    validate_lci_schema,
)


class TestStandardCategories:
    """Tests for the STANDARD_CATEGORIES constant."""

    def test_has_17_categories(self):
        assert len(STANDARD_CATEGORIES) == 17

    def test_all_have_required_fields(self):
        for key, info in STANDARD_CATEGORIES.items():
            assert "direction" in info, f"{key} missing 'direction'"
            assert "ldi_number" in info, f"{key} missing 'ldi_number'"
            assert "english" in info, f"{key} missing 'english'"
            assert "aliases" in info, f"{key} missing 'aliases'"

    def test_direction_values(self):
        for key, info in STANDARD_CATEGORIES.items():
            assert info["direction"] in ("input", "output"), (
                f"{key} has invalid direction: {info['direction']}"
            )

    def test_input_output_split(self):
        inputs = [k for k, v in STANDARD_CATEGORIES.items() if v["direction"] == "input"]
        outputs = [k for k, v in STANDARD_CATEGORIES.items() if v["direction"] == "output"]
        assert len(inputs) == 11
        assert len(outputs) == 6


class TestCategorySets:
    """Tests for INPUT_CATEGORIES, OUTPUT_CATEGORIES, etc."""

    def test_input_categories_count(self):
        assert len(INPUT_CATEGORIES) == 11

    def test_output_categories_count(self):
        assert len(OUTPUT_CATEGORIES) == 6

    def test_no_overlap(self):
        assert not INPUT_CATEGORIES & OUTPUT_CATEGORIES

    def test_excluded_categories(self):
        assert "Raw Material from Processes" in EXCLUDED_LDI_CATEGORIES
        assert "Other Supporting Material" in EXCLUDED_LDI_CATEGORIES

    def test_helper_categories(self):
        assert "Projected Lifetime of Infrastructure" in HELPER_LDI_CATEGORIES
        assert "Projected Lifetime of Land" in HELPER_LDI_CATEGORIES


class TestIOTableSectionOrder:
    """Tests for IO_TABLE_SECTION_ORDER."""

    def test_has_26_sections(self):
        assert len(IO_TABLE_SECTION_ORDER) == 26

    def test_starts_with_inputs(self):
        assert IO_TABLE_SECTION_ORDER[0] == "Bahan Baku"

    def test_ends_with_emission_detail(self):
        assert IO_TABLE_SECTION_ORDER[-1] == "Emisi TOC"

    def test_produk_is_first_output(self):
        assert IO_TABLE_SECTION_ORDER[11] == "Produk"

    def test_sampah_replaces_limbah_nonb3(self):
        assert "Sampah" in IO_TABLE_SECTION_ORDER
        assert "Limbah Non-B3" not in IO_TABLE_SECTION_ORDER

    def test_emisi_co_in_order(self):
        assert "Emisi CO" in IO_TABLE_SECTION_ORDER

    def test_emisi_particulate_material(self):
        assert "Emisi Particulate Material" in IO_TABLE_SECTION_ORDER
        assert "Emisi PM" not in IO_TABLE_SECTION_ORDER

    def test_emission_details_last(self):
        for section in EMISSION_DETAIL_SECTIONS:
            assert section in IO_TABLE_SECTION_ORDER


class TestNormalizeCategory:
    """Tests for normalize_category()."""

    def test_exact_match(self):
        assert normalize_category("Bahan Baku") == "Bahan Baku"

    def test_case_insensitive(self):
        assert normalize_category("bahan baku") == "Bahan Baku"
        assert normalize_category("LISTRIK") == "Listrik"

    def test_english_alias(self):
        assert normalize_category("Water") == "Air"
        assert normalize_category("Electricity") == "Listrik"
        assert normalize_category("Infrastructure") == "Infrastruktur"

    def test_sampah_aliases(self):
        assert normalize_category("Sampah") == "Sampah"
        assert normalize_category("limbah non-b3") == "Sampah"
        assert normalize_category("non-hazardous waste") == "Sampah"

    def test_abbreviation_alias(self):
        assert normalize_category("B.P. Cairan") == "Bahan Pendukung Cairan"
        assert normalize_category("b.p.padatan") == "Bahan Pendukung Padatan"
        assert normalize_category("B.B. Cair") == "Bahan Bakar Cair"

    def test_unknown_returns_none(self):
        assert normalize_category("Unknown Category") is None
        assert normalize_category("") is None

    def test_whitespace_handling(self):
        assert normalize_category("  Air  ") == "Air"


class TestCategoryDirection:
    """Tests for category_direction()."""

    def test_input_category(self):
        assert category_direction("Bahan Baku") == "input"
        assert category_direction("Listrik") == "input"

    def test_output_category(self):
        assert category_direction("Produk") == "output"
        assert category_direction("Limbah B3") == "output"

    def test_unknown_returns_none(self):
        assert category_direction("not-a-category") is None


class TestExcludedAndHelper:
    """Tests for is_excluded_ldi() and is_helper_ldi()."""

    def test_excluded(self):
        assert is_excluded_ldi("Raw Material from Processes") is True
        assert is_excluded_ldi("Other Supporting Material") is True
        assert is_excluded_ldi("Water") is False

    def test_helper(self):
        assert is_helper_ldi("Projected Lifetime of Infrastructure") is True
        assert is_helper_ldi("Projected Lifetime of Land") is True
        assert is_helper_ldi("Infrastructure") is False


class TestNormalizeUnit:
    """Tests for normalize_unit()."""

    def test_standard_units(self):
        assert normalize_unit("kg") == "kg"
        assert normalize_unit("L") == "L"
        assert normalize_unit("kWh") == "kWh"

    def test_alias_resolution(self):
        assert normalize_unit("kilogram") == "kg"
        assert normalize_unit("liter") == "L"
        assert normalize_unit("tonne") == "ton"
        assert normalize_unit("bbl") == "barrel"
        assert normalize_unit("m³") == "m3"
        assert normalize_unit("m²a") == "m2a"

    def test_case_insensitive(self):
        assert normalize_unit("KWH") == "kWh"
        assert normalize_unit("Mmscf") == "MMSCF"

    def test_unknown_passthrough(self):
        assert normalize_unit("custom_unit") == "custom_unit"

    def test_empty(self):
        assert normalize_unit("") == ""

    def test_whitespace(self):
        assert normalize_unit("  kg  ") == "kg"


class TestValidateLCISchema:
    """Tests for validate_lci_schema()."""

    def test_valid_data(self):
        data = {
            "flows": [
                {
                    "category": "Air",
                    "flow_name": "Water Produced",
                    "amount": 1000.0,
                    "unit": "L",
                    "direction": "input",
                    "process": "Well Operation",
                }
            ]
        }
        errors = validate_lci_schema(data)
        assert errors == []

    def test_missing_flows(self):
        errors = validate_lci_schema({"not_flows": []})
        assert len(errors) == 1
        assert "flows" in errors[0]

    def test_not_dict(self):
        errors = validate_lci_schema("not a dict")
        assert len(errors) == 1

    def test_missing_required_field(self):
        data = {"flows": [{"category": "Air"}]}
        errors = validate_lci_schema(data)
        assert len(errors) == 4  # missing flow_name, amount, unit, direction

    def test_unknown_category(self):
        data = {
            "flows": [
                {
                    "category": "Unknown",
                    "flow_name": "test",
                    "amount": 1.0,
                    "unit": "kg",
                    "direction": "input",
                }
            ]
        }
        errors = validate_lci_schema(data)
        assert any("unknown category" in e.lower() for e in errors)

    def test_invalid_direction(self):
        data = {
            "flows": [
                {
                    "category": "Air",
                    "flow_name": "test",
                    "amount": 1.0,
                    "unit": "L",
                    "direction": "sideways",
                }
            ]
        }
        errors = validate_lci_schema(data)
        assert any("direction" in e for e in errors)

    def test_invalid_amount_type(self):
        data = {
            "flows": [
                {
                    "category": "Air",
                    "flow_name": "test",
                    "amount": "not-a-number",
                    "unit": "L",
                    "direction": "input",
                }
            ]
        }
        errors = validate_lci_schema(data)
        assert any("amount" in e for e in errors)

    def test_emission_detail_section_accepted(self):
        data = {
            "flows": [
                {
                    "category": "Emisi CO2",
                    "flow_name": "Flaring CO2",
                    "amount": 100.0,
                    "unit": "kg",
                    "direction": "output",
                }
            ]
        }
        errors = validate_lci_schema(data)
        assert errors == []
