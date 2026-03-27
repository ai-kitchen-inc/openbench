"""Tests for chart generation tools (auto-read pipeline data)."""

from __future__ import annotations

import json

import pytest

from lci_ignite.intelligence.tools import (
    _store_pipeline,
    clear_pipeline_data,
    clear_render_items,
    generate_category_chart,
    generate_emission_chart,
    generate_product_chart,
    get_render_items,
)


@pytest.fixture(autouse=True)
def _clear():
    clear_render_items()
    clear_pipeline_data()
    yield
    clear_render_items()
    clear_pipeline_data()


def _set_pipeline(flows, products=None):
    """Inject pipeline data for the tool."""
    data = {"flows": flows}
    if products is not None:
        data["products"] = products
    _store_pipeline(data)


# ── Sample flows ──

SAMPLE_FLOWS = [
    {
        "flow_name": "Crude Oil",
        "category": "Bahan Baku",
        "direction": "input",
        "amount": 5000,
        "unit": "kg",
    },
    {
        "flow_name": "Well Water",
        "category": "Air",
        "direction": "input",
        "amount": 3000,
        "unit": "L",
    },
    {
        "flow_name": "Diesel Fuel",
        "category": "Bahan Bakar Cair",
        "direction": "input",
        "amount": 1500,
        "unit": "L",
    },
    {
        "flow_name": "CO2 from combustion",
        "category": "Emisi Udara",
        "direction": "output",
        "amount": 800,
        "unit": "kg",
    },
    {
        "flow_name": "CH4 leak",
        "category": "Emisi Udara",
        "direction": "output",
        "amount": 120,
        "unit": "kg",
    },
    {
        "flow_name": "NOx from engine",
        "category": "Emisi Udara",
        "direction": "output",
        "amount": 30,
        "unit": "kg",
    },
    {
        "flow_name": "Solid Waste",
        "category": "Sampah",
        "direction": "output",
        "amount": 200,
        "unit": "kg",
    },
]

SAMPLE_FLOWS_WITH_PRODUCTS = [
    {
        "flow_name": "Crude Oil",
        "category": "Bahan Baku",
        "direction": "input",
        "amount": 5000,
        "unit": "kg",
        "per_product_Gas": 3000,
        "per_product_Minyak": 2000,
    },
    {
        "flow_name": "Well Water",
        "category": "Air",
        "direction": "input",
        "amount": 3000,
        "unit": "L",
        "per_product_Gas": 1500,
        "per_product_Minyak": 1500,
    },
    {
        "flow_name": "CO2 from combustion",
        "category": "Emisi Udara",
        "direction": "output",
        "amount": 800,
        "unit": "kg",
        "per_product_Gas": 500,
        "per_product_Minyak": 300,
    },
]


# ── generate_category_chart ──


class TestGenerateCategoryChart:
    def test_creates_bar_chart(self):
        _set_pipeline(SAMPLE_FLOWS)
        result = generate_category_chart()
        data = json.loads(result)
        assert data["status"] == "chart_created"
        assert data["categories"] > 0

        items = get_render_items()
        assert len(items) == 1
        assert items[0]["type"] == "bar"
        assert items[0]["title"] == "IO Table by Category"
        assert items[0]["options"]["xKey"] == "category"

    def test_separates_input_output(self):
        _set_pipeline(SAMPLE_FLOWS)
        generate_category_chart()
        items = get_render_items()
        chart_data = items[0]["data"]

        # Find Bahan Baku (input) and Emisi Udara (output)
        bahan_baku = next(d for d in chart_data if d["category"] == "Bahan Baku")
        assert "input" in bahan_baku
        assert "output" not in bahan_baku

        emisi = next(d for d in chart_data if d["category"] == "Emisi Udara")
        assert "output" in emisi
        assert "input" not in emisi

    def test_custom_title(self):
        _set_pipeline(SAMPLE_FLOWS)
        result = generate_category_chart(title="My Custom Chart")
        data = json.loads(result)
        assert data["title"] == "My Custom Chart"

        items = get_render_items()
        assert items[0]["title"] == "My Custom Chart"

    def test_no_pipeline_data(self):
        result = generate_category_chart()
        assert "Error" in result

    def test_empty_flows(self):
        _set_pipeline([])
        result = generate_category_chart()
        data = json.loads(result)
        assert "error" in data

    def test_replaces_chart_same_title(self):
        _set_pipeline(SAMPLE_FLOWS)
        generate_category_chart(title="Same")
        generate_category_chart(title="Same")
        items = get_render_items()
        assert len(items) == 1

    def test_keeps_charts_different_titles(self):
        _set_pipeline(SAMPLE_FLOWS)
        generate_category_chart(title="Chart A")
        generate_category_chart(title="Chart B")
        items = get_render_items()
        assert len(items) == 2

    def test_section_order(self):
        """Categories should follow IO_TABLE_SECTION_ORDER."""
        _set_pipeline(SAMPLE_FLOWS)
        generate_category_chart()
        items = get_render_items()
        categories = [d["category"] for d in items[0]["data"]]
        # Bahan Baku should come before Air in PROPER order
        assert categories.index("Bahan Baku") < categories.index("Air")
        # Input categories should come before output categories
        assert categories.index("Air") < categories.index("Emisi Udara")

    def test_infers_direction_from_schema(self):
        """When direction is missing, should infer from STANDARD_CATEGORIES."""
        flows = [
            {"flow_name": "Water", "category": "Air", "amount": 100, "unit": "L"},
            {"flow_name": "Waste", "category": "Sampah", "amount": 50, "unit": "kg"},
        ]
        _set_pipeline(flows)
        generate_category_chart()
        items = get_render_items()
        chart_data = items[0]["data"]

        air = next(d for d in chart_data if d["category"] == "Air")
        assert "input" in air

        sampah = next(d for d in chart_data if d["category"] == "Sampah")
        assert "output" in sampah

    def test_explicit_json_data(self):
        """Should accept explicit JSON data instead of auto."""
        flows_json = json.dumps({"flows": SAMPLE_FLOWS})
        result = generate_category_chart(data=flows_json)
        data = json.loads(result)
        assert data["status"] == "chart_created"

    def test_series_config(self):
        _set_pipeline(SAMPLE_FLOWS)
        generate_category_chart()
        items = get_render_items()
        series = items[0]["options"]["series"]
        assert len(series) == 2
        keys = {s["dataKey"] for s in series}
        assert keys == {"input", "output"}


# ── generate_emission_chart ──


class TestGenerateEmissionChart:
    def test_creates_pie_chart(self):
        _set_pipeline(SAMPLE_FLOWS)
        result = generate_emission_chart()
        data = json.loads(result)
        assert data["status"] == "chart_created"
        assert data["pollutants"] > 0
        assert data["total_kg"] > 0

        items = get_render_items()
        assert len(items) == 1
        assert items[0]["type"] == "pie"
        assert items[0]["title"] == "Emission Breakdown"

    def test_classifies_pollutants(self):
        _set_pipeline(SAMPLE_FLOWS)
        generate_emission_chart()
        items = get_render_items()
        chart_data = items[0]["data"]
        pollutant_names = {d["name"] for d in chart_data}
        assert "CO2" in pollutant_names
        assert "CH4" in pollutant_names
        assert "NOx" in pollutant_names

    def test_percentages_sum_to_100(self):
        _set_pipeline(SAMPLE_FLOWS)
        generate_emission_chart()
        items = get_render_items()
        chart_data = items[0]["data"]
        total_pct = sum(d["percentage"] for d in chart_data)
        assert abs(total_pct - 100.0) < 0.1

    def test_sorted_by_value_descending(self):
        _set_pipeline(SAMPLE_FLOWS)
        generate_emission_chart()
        items = get_render_items()
        chart_data = items[0]["data"]
        values = [d["value"] for d in chart_data]
        assert values == sorted(values, reverse=True)

    def test_custom_title(self):
        _set_pipeline(SAMPLE_FLOWS)
        generate_emission_chart(title="Air Emissions")
        items = get_render_items()
        assert items[0]["title"] == "Air Emissions"

    def test_no_pipeline_data(self):
        result = generate_emission_chart()
        assert "Error" in result

    def test_no_emission_flows(self):
        flows = [
            {"flow_name": "Water", "category": "Air", "amount": 100, "unit": "L"},
        ]
        _set_pipeline(flows)
        result = generate_emission_chart()
        data = json.loads(result)
        assert "error" in data
        assert "Emisi Udara" in data["error"]

    def test_unclassified_emissions_as_other(self):
        flows = [
            {
                "flow_name": "Unknown gas XYZ",
                "category": "Emisi Udara",
                "direction": "output",
                "amount": 50,
                "unit": "kg",
            },
        ]
        _set_pipeline(flows)
        generate_emission_chart()
        items = get_render_items()
        chart_data = items[0]["data"]
        assert chart_data[0]["name"] == "Other"

    def test_mixed_pollutants(self):
        """Multiple flows of same pollutant should be summed."""
        flows = [
            {
                "flow_name": "CO2 from boiler",
                "category": "Emisi Udara",
                "direction": "output",
                "amount": 500,
                "unit": "kg",
            },
            {
                "flow_name": "CO2 from engine",
                "category": "Emisi Udara",
                "direction": "output",
                "amount": 300,
                "unit": "kg",
            },
            {
                "flow_name": "CH4 from vent",
                "category": "Emisi Udara",
                "direction": "output",
                "amount": 100,
                "unit": "kg",
            },
        ]
        _set_pipeline(flows)
        generate_emission_chart()
        items = get_render_items()
        chart_data = items[0]["data"]
        co2 = next(d for d in chart_data if d["name"] == "CO2")
        assert co2["value"] == 800.0

    def test_replaces_chart_same_title(self):
        _set_pipeline(SAMPLE_FLOWS)
        generate_emission_chart(title="Same")
        generate_emission_chart(title="Same")
        items = get_render_items()
        assert len(items) == 1

    def test_zero_amount_emissions(self):
        flows = [
            {
                "flow_name": "CO2 zero",
                "category": "Emisi Udara",
                "direction": "output",
                "amount": 0,
                "unit": "kg",
            },
        ]
        _set_pipeline(flows)
        result = generate_emission_chart()
        data = json.loads(result)
        assert "error" in data
        assert "zero" in data["error"]


# ── generate_product_chart ──


class TestGenerateProductChart:
    def test_creates_grouped_bar_chart(self):
        _set_pipeline(SAMPLE_FLOWS_WITH_PRODUCTS)
        result = generate_product_chart()
        data = json.loads(result)
        assert data["status"] == "chart_created"
        assert data["categories"] > 0
        assert set(data["products"]) == {"Gas", "Minyak"}

        items = get_render_items()
        assert len(items) == 1
        assert items[0]["type"] == "bar"
        assert items[0]["options"]["xKey"] == "category"

    def test_series_per_product(self):
        _set_pipeline(SAMPLE_FLOWS_WITH_PRODUCTS)
        generate_product_chart()
        items = get_render_items()
        series = items[0]["options"]["series"]
        series_keys = {s["dataKey"] for s in series}
        assert series_keys == {"Gas", "Minyak"}

    def test_sums_per_product_amounts(self):
        _set_pipeline(SAMPLE_FLOWS_WITH_PRODUCTS)
        generate_product_chart()
        items = get_render_items()
        chart_data = items[0]["data"]

        bahan_baku = next(d for d in chart_data if d["category"] == "Bahan Baku")
        assert bahan_baku["Gas"] == 3000.0
        assert bahan_baku["Minyak"] == 2000.0

    def test_custom_title(self):
        _set_pipeline(SAMPLE_FLOWS_WITH_PRODUCTS)
        generate_product_chart(title="My Products")
        items = get_render_items()
        assert items[0]["title"] == "My Products"

    def test_no_pipeline_data(self):
        result = generate_product_chart()
        assert "Error" in result

    def test_no_product_data(self):
        """Flows without per_product_ keys should error."""
        flows = [
            {"flow_name": "Water", "category": "Air", "amount": 100, "unit": "L"},
        ]
        _set_pipeline(flows)
        result = generate_product_chart()
        data = json.loads(result)
        assert "error" in data
        assert "product" in data["error"].lower()

    def test_fallback_to_pipeline_products(self):
        """When flows lack per_product_ keys, check pipeline products list."""
        flows = [
            {
                "flow_name": "Water",
                "category": "Air",
                "amount": 100,
                "unit": "L",
                "per_product_Gas": 60,
                "per_product_Minyak": 40,
            },
        ]
        _set_pipeline(flows, products=[{"name": "Gas"}, {"name": "Minyak"}])
        result = generate_product_chart()
        data = json.loads(result)
        assert data["status"] == "chart_created"

    def test_replaces_chart_same_title(self):
        _set_pipeline(SAMPLE_FLOWS_WITH_PRODUCTS)
        generate_product_chart(title="Same")
        generate_product_chart(title="Same")
        items = get_render_items()
        assert len(items) == 1

    def test_section_order(self):
        """Categories should follow IO_TABLE_SECTION_ORDER."""
        _set_pipeline(SAMPLE_FLOWS_WITH_PRODUCTS)
        generate_product_chart()
        items = get_render_items()
        categories = [d["category"] for d in items[0]["data"]]
        # Bahan Baku should come before Air
        assert categories.index("Bahan Baku") < categories.index("Air")

    def test_explicit_json_data(self):
        flows_json = json.dumps({"flows": SAMPLE_FLOWS_WITH_PRODUCTS})
        result = generate_product_chart(data=flows_json)
        data = json.loads(result)
        assert data["status"] == "chart_created"
