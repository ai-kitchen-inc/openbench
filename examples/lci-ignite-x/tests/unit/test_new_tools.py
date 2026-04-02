"""Tests for 7 new LCI data processing tools."""

import json
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pytest

from lci_ignite.intelligence.tools import (
    _read_pipeline,
    _store_pipeline,
    aggregate_flows,
    analyze_excel_structure,
    apply_unit_conversions,
    build_proper_io_table,
    calculate_functional_unit,
    clear_pipeline_data,
    clear_render_items,
    get_render_items,
    parse_ldi_sheet,
    select_pareto_items,
    validate_data_quality,
)


@pytest.fixture(autouse=True)
def _clear_render():
    clear_render_items()
    clear_pipeline_data()
    yield
    clear_render_items()
    clear_pipeline_data()


def _create_test_xlsx(path: Path, sheet_name: str = "LDI Master"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(["Process", "Category", "Material", "Direction", "Unit", "Amount"])
    ws.append(["Well Op", "Water", "Produced", "Input", "L", 1000.0])
    ws.append(["NSOP", "Electricity", "Pompa", "Input", "kWh", 500.0])
    wb.save(str(path))


_TEST_PROFILE_FOR_TOOLS = {
    "profile_name": "test_tools_profile",
    "company": "Test Tools Corp",
    "sheet_name": "LDI-Test Tools-00001",
    "expected_headers": ["No", "Process Title"],
    "column_mapping": {},
    "products": [],
    "category_mapping": {},
    "unit_conversions": [],
}


# ---------------------------------------------------------------------------
# analyze_excel_structure
# ---------------------------------------------------------------------------


class TestAnalyzeExcelStructure:
    def test_returns_json(self, tmp_path):
        xlsx = tmp_path / "test.xlsx"
        _create_test_xlsx(xlsx)
        result = analyze_excel_structure(str(xlsx))
        data = json.loads(result)
        assert "sheet_names" in data
        assert "sheets" in data
        assert "message" in data

    def test_file_not_found(self):
        result = analyze_excel_structure("/nonexistent/file.xlsx")
        assert "Error" in result

    def test_detects_known_profile(self, tmp_path):
        # Create a profile in a temp dir
        profile_dir = tmp_path / "profiles"
        profile_dir.mkdir()
        (profile_dir / "test_tools_profile.json").write_text(
            json.dumps(_TEST_PROFILE_FOR_TOOLS, indent=2), encoding="utf-8"
        )

        xlsx = tmp_path / "test.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "LDI-Test Tools-00001"
        ws.append(["No", "Process Title"])
        wb.save(str(xlsx))

        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", profile_dir):
            result = analyze_excel_structure(str(xlsx))
        data = json.loads(result)
        assert data["matched_profile"] == "test_tools_profile"

    def test_no_matching_profile(self, tmp_path):
        xlsx = tmp_path / "test.xlsx"
        _create_test_xlsx(xlsx, sheet_name="Unknown Company")
        # Patch to empty dir so no profiles exist
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", tmp_path / "empty_profiles"):
            (tmp_path / "empty_profiles").mkdir()
            result = analyze_excel_structure(str(xlsx))
        data = json.loads(result)
        assert data["matched_profile"] is None


# ---------------------------------------------------------------------------
# parse_ldi_sheet
# ---------------------------------------------------------------------------


class TestParseLdiSheet:
    def test_profile_not_found(self, tmp_path):
        xlsx = tmp_path / "test.xlsx"
        _create_test_xlsx(xlsx)
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", tmp_path):
            result = parse_ldi_sheet(str(xlsx), "nonexistent_profile")
        assert "Error" in result

    def test_auto_no_match(self, tmp_path):
        xlsx = tmp_path / "test.xlsx"
        _create_test_xlsx(xlsx, sheet_name="Unknown")
        # Patch to empty dir so no profiles match
        empty_dir = tmp_path / "empty_profiles"
        empty_dir.mkdir()
        with patch("lci_ignite.data.mapping_profiles.PROFILES_DIR", empty_dir):
            result = parse_ldi_sheet(str(xlsx), "auto")
        assert "No matching profile" in result


# ---------------------------------------------------------------------------
# apply_unit_conversions
# ---------------------------------------------------------------------------


class TestApplyUnitConversions:
    def test_basic_conversion(self):
        flows = [
            {"category": "Emisi Udara", "flow_name": "CO2", "amount": 19.607, "unit": "ton"},
        ]
        conversions = [
            {"from_unit": "ton", "to_unit": "kg", "factor": 1000, "applies_to": ["Emisi Udara"]},
        ]
        result = json.loads(apply_unit_conversions(json.dumps(flows), json.dumps(conversions)))
        assert result["conversions_applied"] == 1
        pipeline = _read_pipeline()
        assert pipeline["flows"][0]["amount"] == 19607.0
        assert pipeline["flows"][0]["unit"] == "kg"
        assert pipeline["flows"][0]["original_amount"] == 19.607

    def test_no_matching_conversion(self):
        flows = [{"category": "Listrik", "flow_name": "Pompa", "amount": 500, "unit": "kWh"}]
        conversions = [{"from_unit": "ton", "to_unit": "kg", "factor": 1000}]
        result = json.loads(apply_unit_conversions(json.dumps(flows), json.dumps(conversions)))
        assert result["conversions_applied"] == 0
        pipeline = _read_pipeline()
        assert pipeline["flows"][0]["amount"] == 500

    def test_applies_to_filter(self):
        flows = [
            {"category": "Air", "flow_name": "Water", "amount": 100, "unit": "barrel"},
            {"category": "Produk", "flow_name": "Oil", "amount": 100, "unit": "barrel"},
        ]
        conversions = [
            {"from_unit": "barrel", "to_unit": "L", "factor": 158.987, "applies_to": ["Air"]},
        ]
        result = json.loads(apply_unit_conversions(json.dumps(flows), json.dumps(conversions)))
        assert result["conversions_applied"] == 1
        pipeline = _read_pipeline()
        assert pipeline["flows"][0]["amount"] == pytest.approx(15898.7)
        assert pipeline["flows"][1]["amount"] == 100  # Produk not converted

    def test_invalid_json(self):
        result = apply_unit_conversions("bad json", "[]")
        assert "Error" in result

    def test_empty_flows(self):
        result = json.loads(apply_unit_conversions("[]", "[]"))
        assert result["total_flows"] == 0


# ---------------------------------------------------------------------------
# calculate_functional_unit
# ---------------------------------------------------------------------------


class TestCalculateFunctionalUnit:
    def test_basic_fu_calculation(self):
        flows = [
            {
                "category": "Air",
                "flow_name": "Water",
                "amount": 1000,
                "unit": "L",
                "per_product_Gas": 400,
                "per_product_Oil": 600,
            },
        ]
        products = [
            {"name": "Gas", "total_energy_mj": 1000},
            {"name": "Oil", "total_energy_mj": 2000},
        ]
        calculate_functional_unit(json.dumps(flows), json.dumps(products))
        pipeline = _read_pipeline()
        flow = pipeline["flows"][0]
        assert flow["fu_per_mj_Gas"] == pytest.approx(0.4)
        assert flow["fu_per_mj_Oil"] == pytest.approx(0.3)

    def test_percentage_calculation(self):
        flows = [
            {"category": "Air", "flow_name": "A", "amount": 100, "per_product_X": 60},
            {"category": "Air", "flow_name": "B", "amount": 50, "per_product_X": 40},
        ]
        products = [{"name": "X", "total_energy_mj": 100}]
        calculate_functional_unit(json.dumps(flows), json.dumps(products))
        pipeline = _read_pipeline()
        assert pipeline["flows"][0]["pct_X"] == 60.0
        assert pipeline["flows"][1]["pct_X"] == 40.0

    def test_no_products(self):
        result = calculate_functional_unit("[]", "[]")
        assert "Error" in result

    def test_zero_energy(self):
        flows = [{"category": "Air", "flow_name": "W", "amount": 100, "per_product_X": 50}]
        products = [{"name": "X", "total_energy_mj": 0}]
        calculate_functional_unit(json.dumps(flows), json.dumps(products))
        pipeline = _read_pipeline()
        assert (
            pipeline["flows"][0].get("fu_per_mj_X") is None
            or pipeline["flows"][0].get("fu_per_mj_X", 0) == 0
        )

    def test_invalid_json(self):
        result = calculate_functional_unit("bad", "[]")
        assert "Error" in result


# ---------------------------------------------------------------------------
# select_pareto_items
# ---------------------------------------------------------------------------


class TestSelectParetoItems:
    def test_basic_selection(self):
        flows = [
            {"category": "Air", "flow_name": f"Flow{i}", "amount": (10 - i) * 100} for i in range(8)
        ]
        result = json.loads(select_pareto_items(json.dumps(flows), top_n=3))
        assert result["total_selected"] == 4  # 3 top + 1 Lainnya

    def test_lainnya_aggregation(self):
        flows = [
            {"category": "Air", "flow_name": "A", "amount": 100, "unit": "L"},
            {"category": "Air", "flow_name": "B", "amount": 80, "unit": "L"},
            {"category": "Air", "flow_name": "C", "amount": 10, "unit": "L"},
            {"category": "Air", "flow_name": "D", "amount": 5, "unit": "L"},
        ]
        select_pareto_items(json.dumps(flows), top_n=2)
        pipeline = _read_pipeline()
        lainnya = [f for f in pipeline["flows"] if f["flow_name"] == "Lainnya"]
        assert len(lainnya) == 1
        assert lainnya[0]["amount"] == 15  # 10 + 5
        assert lainnya[0]["is_aggregated"] is True

    def test_custom_label(self):
        flows = [
            {"category": "Air", "flow_name": f"F{i}", "amount": 100 - i * 10} for i in range(5)
        ]
        select_pareto_items(json.dumps(flows), top_n=2, lainnya_label="Others")
        pipeline = _read_pipeline()
        others = [f for f in pipeline["flows"] if f["flow_name"] == "Others"]
        assert len(others) == 1

    def test_no_lainnya_when_within_topn(self):
        flows = [
            {"category": "Air", "flow_name": "A", "amount": 100},
            {"category": "Air", "flow_name": "B", "amount": 80},
        ]
        select_pareto_items(json.dumps(flows), top_n=5)
        pipeline = _read_pipeline()
        lainnya = [f for f in pipeline["flows"] if f.get("is_aggregated")]
        assert len(lainnya) == 0

    def test_multiple_categories(self):
        flows = [
            {"category": "Air", "flow_name": "W1", "amount": 100},
            {"category": "Air", "flow_name": "W2", "amount": 50},
            {"category": "Listrik", "flow_name": "E1", "amount": 200},
            {"category": "Listrik", "flow_name": "E2", "amount": 100},
        ]
        result = json.loads(select_pareto_items(json.dumps(flows), top_n=1))
        assert result["total_selected"] == 4  # 1 top + 1 lainnya per category
        assert "Air" in result["stats"]
        assert "Listrik" in result["stats"]

    def test_invalid_json(self):
        result = select_pareto_items("bad json")
        assert "Error" in result


# ---------------------------------------------------------------------------
# validate_data_quality
# ---------------------------------------------------------------------------


class TestValidateDataQuality:
    def test_clean_data(self):
        flows = [
            {"category": "Air", "flow_name": "Water", "amount": 1000, "unit": "L"},
        ]
        result = json.loads(validate_data_quality(json.dumps(flows)))
        assert result["critical"] == 0

    def test_detects_duplicate_emission_values(self):
        flows = [
            {"category": "Emisi NOx", "flow_name": "NOx Flaring", "amount": 8287.65, "unit": "kg"},
            {"category": "Emisi N2O", "flow_name": "N2O Flaring", "amount": 8287.65, "unit": "kg"},
        ]
        result = json.loads(validate_data_quality(json.dumps(flows)))
        assert result["critical"] >= 1

    def test_detects_small_kg_values(self):
        flows = [
            {"category": "Emisi TOC", "flow_name": "TOC Total", "amount": 0.31, "unit": "kg"},
        ]
        result = json.loads(validate_data_quality(json.dumps(flows)))
        assert result["critical"] >= 1

    def test_detects_zero_amounts(self):
        flows = [
            {"category": "Air", "flow_name": "Water", "amount": 0, "unit": "L"},
        ]
        result = json.loads(validate_data_quality(json.dumps(flows)))
        assert result["minor"] >= 1

    def test_detects_negative_amounts(self):
        flows = [
            {"category": "Air", "flow_name": "Water", "amount": -100, "unit": "L"},
        ]
        result = json.loads(validate_data_quality(json.dumps(flows)))
        assert result["moderate"] >= 1

    def test_pushes_callout_for_critical(self):
        flows = [
            {"category": "Emisi TOC", "flow_name": "TOC", "amount": 0.31, "unit": "kg"},
        ]
        validate_data_quality(json.dumps(flows))
        items = get_render_items()
        callouts = [i for i in items if "calloutContent" in i]
        assert len(callouts) >= 1

    def test_invalid_json(self):
        result = validate_data_quality("bad json")
        assert "Error" in result


# ---------------------------------------------------------------------------
# build_proper_io_table
# ---------------------------------------------------------------------------


class TestBuildProperIOTable:
    def test_basic_table(self):
        flows = [
            {
                "category": "Air",
                "flow_name": "Water",
                "amount": 1000,
                "unit": "L",
                "process": "Well Op",
            },
            {
                "category": "Listrik",
                "flow_name": "Pompa",
                "amount": 500,
                "unit": "kWh",
                "process": "NSOP",
            },
        ]
        config = {"products": [], "title": "Test IO Table"}
        result = build_proper_io_table(json.dumps(flows), json.dumps(config))
        assert "PROPER IO Table created" in result
        assert "2 sections" in result

    def test_renders_to_context(self):
        flows = [
            {"category": "Air", "flow_name": "Water", "amount": 1000, "unit": "L"},
        ]
        config = {"products": [], "title": "Test IO"}
        build_proper_io_table(json.dumps(flows), json.dumps(config))
        items = get_render_items()
        tables = [i for i in items if "headers" in i and "rows" in i]
        assert len(tables) == 1
        assert tables[0]["title"] == "Test IO"

    def test_with_products(self):
        flows = [
            {
                "category": "Air",
                "flow_name": "Water",
                "amount": 1000,
                "unit": "L",
                "fu_per_mj_Gas": 0.004,
                "pct_Gas": 60.0,
                "process": "Well Op",
            },
        ]
        config = {"products": [{"name": "Gas"}], "title": "IO with Products"}
        build_proper_io_table(json.dumps(flows), json.dumps(config))
        items = get_render_items()
        table = items[0]
        assert "Gas FU/MJ" in table["headers"][3]

    def test_section_ordering(self):
        flows = [
            {"category": "Listrik", "flow_name": "E1", "amount": 100, "unit": "kWh"},
            {"category": "Air", "flow_name": "W1", "amount": 200, "unit": "L"},
            {"category": "Produk", "flow_name": "Oil", "amount": 300, "unit": "Barrel"},
        ]
        config = {"products": [], "title": "Order Test"}
        build_proper_io_table(json.dumps(flows), json.dumps(config))
        items = get_render_items()
        rows = items[0]["rows"]
        # Air should come before Listrik, Produk after both
        section_headers = [r[0] for r in rows if r[0].startswith("**")]
        assert section_headers.index("**Air**") < section_headers.index("**Listrik**")
        assert section_headers.index("**Listrik**") < section_headers.index("**Produk**")

    def test_total_row_added(self):
        flows = [
            {"category": "Air", "flow_name": "W1", "amount": 100, "unit": "L"},
            {"category": "Air", "flow_name": "W2", "amount": 200, "unit": "L"},
        ]
        config = {"products": [], "title": "Total Test"}
        build_proper_io_table(json.dumps(flows), json.dumps(config))
        items = get_render_items()
        rows = items[0]["rows"]
        total_rows = [r for r in rows if r[0].startswith("Total")]
        assert len(total_rows) >= 1

    def test_invalid_json(self):
        result = build_proper_io_table("bad", "{}")
        assert "Error" in result


# ---------------------------------------------------------------------------
# Configurable Functional Unit (fu_mode) tests
# ---------------------------------------------------------------------------


class TestFUPerOutputUnit:
    """Test per_output_unit FU mode."""

    PRODUCTS = [
        {
            "name": "Gas",
            "total_energy_mj": 93776048,
            "fu_unit_factor": 1055055.85,
            "output_unit": "MMSCF",
        },
        {
            "name": "Minyak",
            "total_energy_mj": 2212001236,
            "fu_unit_factor": 5992.74,
            "output_unit": "Barrel",
        },
    ]

    FLOWS = [
        {
            "category": "Air",
            "flow_name": "Water",
            "amount": 1000,
            "unit": "L",
            "per_product_Gas": 400,
            "per_product_Minyak": 600,
        },
    ]

    def test_fu_per_output_unit(self):
        """Divisor should be total_energy_mj / fu_unit_factor."""
        calculate_functional_unit(
            json.dumps(self.FLOWS),
            json.dumps(self.PRODUCTS),
            fu_mode="per_output_unit",
        )
        pipeline = _read_pipeline()
        flow = pipeline["flows"][0]
        # Gas: 400 / (93776048 / 1055055.85) = 400 / 88.883...
        gas_divisor = 93776048 / 1055055.85
        assert flow["fu_per_mj_Gas"] == pytest.approx(400 / gas_divisor)
        # Minyak: 600 / (2212001236 / 5992.74) = 600 / 369178.7...
        minyak_divisor = 2212001236 / 5992.74
        assert flow["fu_per_mj_Minyak"] == pytest.approx(600 / minyak_divisor)

    def test_fu_mode_default_per_mj(self):
        """Default mode should divide by total_energy_mj."""
        calculate_functional_unit(
            json.dumps(self.FLOWS),
            json.dumps(self.PRODUCTS),
        )
        pipeline = _read_pipeline()
        flow = pipeline["flows"][0]
        assert flow["fu_per_mj_Gas"] == pytest.approx(400 / 93776048)
        assert flow["fu_per_mj_Minyak"] == pytest.approx(600 / 2212001236)

    def test_fu_per_output_unit_fallback(self):
        """When fu_unit_factor is 0, should fall back to per MJ."""
        products = [
            {
                "name": "X",
                "total_energy_mj": 1000,
                "fu_unit_factor": 0,
                "output_unit": "Barrel",
            },
        ]
        flows = [{"category": "Air", "flow_name": "W", "amount": 100, "per_product_X": 50}]
        calculate_functional_unit(
            json.dumps(flows),
            json.dumps(products),
            fu_mode="per_output_unit",
        )
        pipeline = _read_pipeline()
        # Falls back to per MJ since fu_unit_factor == 0
        assert pipeline["fu_unit_labels"]["X"] == "MJ"
        assert pipeline["flows"][0]["fu_per_mj_X"] == pytest.approx(50 / 1000)

    def test_fu_mode_stored_in_pipeline(self):
        """fu_mode and fu_unit_labels should be stored in pipeline state."""
        calculate_functional_unit(
            json.dumps(self.FLOWS),
            json.dumps(self.PRODUCTS),
            fu_mode="per_output_unit",
        )
        pipeline = _read_pipeline()
        assert pipeline["fu_mode"] == "per_output_unit"
        assert pipeline["fu_unit_labels"]["Gas"] == "MMSCF"
        assert pipeline["fu_unit_labels"]["Minyak"] == "Barrel"

    def test_products_stored_as_full_dicts(self):
        """Products in pipeline should be full dicts (not just names)."""
        calculate_functional_unit(
            json.dumps(self.FLOWS),
            json.dumps(self.PRODUCTS),
        )
        pipeline = _read_pipeline()
        assert isinstance(pipeline["products"][0], dict)
        assert "total_energy_mj" in pipeline["products"][0]


class TestProductsPropagation:
    """Test that products survive through pipeline steps."""

    def test_products_propagated_through_conversions(self):
        """Products should survive apply_unit_conversions."""
        data = {
            "flows": [
                {"category": "Air", "flow_name": "W", "amount": 100, "unit": "barrel"},
            ],
            "products": [{"name": "Gas", "total_energy_mj": 1000}],
        }
        _store_pipeline(data)
        apply_unit_conversions(
            data="auto",
            conversions=json.dumps(
                [{"from_unit": "barrel", "to_unit": "L", "factor": 158.987, "applies_to": ["Air"]}]
            ),
        )
        pipeline = _read_pipeline()
        assert "products" in pipeline
        assert pipeline["products"][0]["name"] == "Gas"

    def test_products_propagated_through_pareto(self):
        """Products + fu_mode + fu_unit_labels should survive select_pareto_items."""
        data = {
            "flows": [
                {"category": "Air", "flow_name": f"F{i}", "amount": 100 - i * 10} for i in range(5)
            ],
            "products": [{"name": "Gas", "total_energy_mj": 1000}],
            "fu_mode": "per_output_unit",
            "fu_unit_labels": {"Gas": "MMSCF"},
        }
        _store_pipeline(data)
        select_pareto_items(data="auto", top_n=3)
        pipeline = _read_pipeline()
        assert "products" in pipeline
        assert pipeline["fu_mode"] == "per_output_unit"
        assert pipeline["fu_unit_labels"]["Gas"] == "MMSCF"


# ---------------------------------------------------------------------------
# aggregate_flows
# ---------------------------------------------------------------------------


class TestAggregateFlows:
    def test_merges_same_flow(self):
        """3 CO2 rows with same category/name/unit -> 1 with summed amount."""
        flows = [
            {
                "category": "Emisi Udara",
                "flow_name": "CO2",
                "amount": 100,
                "unit": "kg",
                "process": "NSOP",
            },
            {
                "category": "Emisi Udara",
                "flow_name": "CO2",
                "amount": 200,
                "unit": "kg",
                "process": "NSOP",
            },
            {
                "category": "Emisi Udara",
                "flow_name": "CO2",
                "amount": 50,
                "unit": "kg",
                "process": "Warehouse",
            },
        ]
        result = json.loads(aggregate_flows(json.dumps(flows)))
        assert result["total_before"] == 3
        assert result["total_after"] == 1
        assert result["duplicates_merged"] == 2
        pipeline = _read_pipeline()
        assert len(pipeline["flows"]) == 1
        assert pipeline["flows"][0]["amount"] == 350

    def test_combines_processes(self):
        """Process names from different rows should be joined sorted."""
        flows = [
            {
                "category": "Air",
                "flow_name": "PDAM",
                "amount": 10,
                "unit": "L",
                "process": "Warehouse",
            },
            {"category": "Air", "flow_name": "PDAM", "amount": 20, "unit": "L", "process": "NSOP"},
            {
                "category": "Air",
                "flow_name": "PDAM",
                "amount": 5,
                "unit": "L",
                "process": "Warehouse",
            },
        ]
        aggregate_flows(json.dumps(flows))
        pipeline = _read_pipeline()
        flow = pipeline["flows"][0]
        assert flow["amount"] == 35
        # Should be sorted and deduplicated
        assert flow["process"] == "NSOP, Warehouse"

    def test_sums_per_product_fields(self):
        """per_product_* fields should be summed across duplicates."""
        flows = [
            {
                "category": "Emisi Udara",
                "flow_name": "CO2",
                "amount": 100,
                "unit": "kg",
                "per_product_Gas": 40,
                "per_product_Oil": 60,
            },
            {
                "category": "Emisi Udara",
                "flow_name": "CO2",
                "amount": 200,
                "unit": "kg",
                "per_product_Gas": 80,
                "per_product_Oil": 120,
            },
        ]
        aggregate_flows(json.dumps(flows))
        pipeline = _read_pipeline()
        flow = pipeline["flows"][0]
        assert flow["per_product_Gas"] == 120
        assert flow["per_product_Oil"] == 180
        assert flow["amount"] == 300

    def test_no_duplicates_passthrough(self):
        """Unique flows should pass through unchanged."""
        flows = [
            {"category": "Air", "flow_name": "PDAM", "amount": 10, "unit": "L"},
            {"category": "Listrik", "flow_name": "PLN", "amount": 500, "unit": "kWh"},
            {"category": "Emisi Udara", "flow_name": "CO2", "amount": 100, "unit": "kg"},
        ]
        result = json.loads(aggregate_flows(json.dumps(flows)))
        assert result["total_before"] == 3
        assert result["total_after"] == 3
        assert result["duplicates_merged"] == 0

    def test_preserves_products(self):
        """products and helper_data should be carried forward."""
        data = {
            "flows": [
                {"category": "Air", "flow_name": "W", "amount": 100, "unit": "L"},
            ],
            "products": [{"name": "Gas", "total_energy_mj": 1000}],
            "helper_data": {"some": "info"},
            "summary": {"total_flows": 1, "categories": ["Air"]},
        }
        _store_pipeline(data)
        aggregate_flows(data="auto")
        pipeline = _read_pipeline()
        assert "products" in pipeline
        assert pipeline["products"][0]["name"] == "Gas"
        assert pipeline["helper_data"]["some"] == "info"

    def test_auto_reads_pipeline(self):
        """data='auto' should read from pipeline state."""
        data = {
            "flows": [
                {"category": "Air", "flow_name": "W", "amount": 50, "unit": "L", "process": "A"},
                {"category": "Air", "flow_name": "W", "amount": 70, "unit": "L", "process": "B"},
            ],
        }
        _store_pipeline(data)
        result = json.loads(aggregate_flows(data="auto"))
        assert result["total_before"] == 2
        assert result["total_after"] == 1
        pipeline = _read_pipeline()
        assert pipeline["flows"][0]["amount"] == 120

    def test_no_pipeline_data_error(self):
        """Should return error when no pipeline data and data='auto'."""
        result = aggregate_flows(data="auto")
        assert "Error" in result

    def test_invalid_json(self):
        """Should return error for invalid JSON."""
        result = aggregate_flows(data="bad json")
        assert "Error" in result
