"""Unit tests for conversational tools (explain, compare, revise, export_filtered)."""

from __future__ import annotations

import json

import pytest

from lci_ignite.intelligence.tools import (
    _session_pipelines,
    _store_pipeline,
    clear_pipeline_data,
    clear_render_items,
    compare_products,
    explain_analysis,
    export_filtered,
    get_render_items,
    revise_pipeline,
    set_pipeline_session,
    set_upload_dir,
)

# ── Test Data ──

SAMPLE_FLOWS = [
    {
        "flow_name": "CO2 Flaring",
        "amount": 5000.0,
        "unit": "kg",
        "category": "Emisi CO2",
        "direction": "output",
        "process": "Flaring",
        "fu_per_mj_Gas": 0.05,
        "fu_per_mj_Minyak": 0.03,
        "pct_Gas": 60.0,
        "pct_Minyak": 55.0,
    },
    {
        "flow_name": "CO2 Gas Engine",
        "amount": 3000.0,
        "unit": "kg",
        "category": "Emisi CO2",
        "direction": "output",
        "process": "Gas Engine",
        "fu_per_mj_Gas": 0.03,
        "fu_per_mj_Minyak": 0.02,
        "pct_Gas": 30.0,
        "pct_Minyak": 35.0,
    },
    {
        "flow_name": "CH4 Venting",
        "amount": 200.0,
        "unit": "kg",
        "category": "Emisi CH4",
        "direction": "output",
        "process": "Venting",
        "fu_per_mj_Gas": 0.002,
        "fu_per_mj_Minyak": 0.001,
        "pct_Gas": 100.0,
        "pct_Minyak": 100.0,
    },
    {
        "flow_name": "Solar",
        "amount": 10000.0,
        "unit": "L",
        "category": "Energi",
        "direction": "input",
        "process": "Utility",
        "fu_per_mj_Gas": 0.1,
        "fu_per_mj_Minyak": 0.08,
        "pct_Gas": 100.0,
        "pct_Minyak": 100.0,
    },
]

SAMPLE_PIPELINE = {
    "flows": SAMPLE_FLOWS,
    "products": ["Gas", "Minyak"],
}


@pytest.fixture(autouse=True)
def _clear():
    """Clear state before and after each test."""
    clear_render_items()
    clear_pipeline_data()
    _session_pipelines.clear()
    yield
    clear_render_items()
    clear_pipeline_data()
    _session_pipelines.clear()


# ── Session Pipeline Persistence ──


class TestSessionPipelinePersistence:
    def test_set_pipeline_session_restores_data(self):
        """Pipeline data stored in session should be restored on next request."""
        # Simulate first request: store data
        set_pipeline_session("session-1")
        _store_pipeline(SAMPLE_PIPELINE)

        # Simulate clearing (new request context)
        clear_pipeline_data()

        # Simulate second request: restore from session
        set_pipeline_session("session-1")
        result = explain_analysis("what is the top CO2?")
        parsed = json.loads(result)
        assert "error" not in parsed
        assert parsed["flow_count"] > 0

    def test_different_sessions_are_independent(self):
        """Different session IDs should have independent pipeline data."""
        set_pipeline_session("session-a")
        _store_pipeline(SAMPLE_PIPELINE)

        # New session with no saved data — clear removes session-a data
        clear_pipeline_data()
        set_pipeline_session("session-b")
        # session-b has no saved pipeline, container was cleared
        result = explain_analysis("test")
        # _resolve_data returns plain error string when no pipeline data
        assert "Error" in result or "error" in result

    def test_no_session_clears_normally(self):
        """Without a session ID, clear_pipeline_data behaves normally."""
        _store_pipeline(SAMPLE_PIPELINE)
        clear_pipeline_data()
        result = explain_analysis("test")
        # _resolve_data returns plain error string when no pipeline data
        assert "Error" in result


# ── explain_analysis ──


class TestExplainAnalysis:
    def test_no_pipeline_data(self):
        result = explain_analysis("kenapa CO2 tinggi?")
        assert "Error" in result

    def test_category_detection_co2(self):
        _store_pipeline(SAMPLE_PIPELINE)
        result = json.loads(explain_analysis("kenapa CO2 paling tinggi?"))
        assert result["target_category"] == "Emisi CO2"
        assert result["flow_count"] == 2
        assert result["top_contributor"] == "CO2 Flaring"

    def test_category_detection_energi(self):
        _store_pipeline(SAMPLE_PIPELINE)
        result = json.loads(explain_analysis("jelaskan energi"))
        assert result["target_category"] == "Energi"
        assert result["flow_count"] == 1

    def test_no_category_match_returns_all(self):
        _store_pipeline(SAMPLE_PIPELINE)
        result = json.loads(explain_analysis("ringkasan hasil analisis"))
        assert result["target_category"] is None
        assert result["flow_count"] == 4

    def test_pushes_callout(self):
        _store_pipeline(SAMPLE_PIPELINE)
        explain_analysis("kenapa CO2?")
        items = get_render_items()
        callouts = [i for i in items if "calloutContent" in i]
        assert len(callouts) >= 1
        assert "CO2 Flaring" in callouts[-1]["calloutContent"]

    def test_percentages_sum_to_100(self):
        _store_pipeline(SAMPLE_PIPELINE)
        result = json.loads(explain_analysis("kenapa CO2?"))
        total_pct = sum(f["percentage"] for f in result["top_flows"])
        assert abs(total_pct - 100.0) < 0.1


# ── compare_products ──


class TestCompareProducts:
    def test_no_pipeline_data(self):
        result = compare_products()
        assert "Error" in result

    def test_no_fu_data(self):
        _store_pipeline({"flows": [{"flow_name": "X", "amount": 1, "category": "A"}]})
        result = json.loads(compare_products())
        assert "error" in result

    def test_compare_all(self):
        _store_pipeline(SAMPLE_PIPELINE)
        result = json.loads(compare_products(metric="all"))
        assert result["categories_compared"] == 3  # Emisi CO2, Emisi CH4, Energi
        assert "Gas" in result["products"]
        assert "Minyak" in result["products"]

    def test_compare_specific_category(self):
        _store_pipeline(SAMPLE_PIPELINE)
        result = json.loads(compare_products(metric="Emisi CO2"))
        assert result["categories_compared"] == 1
        assert result["comparison"][0]["category"] == "Emisi CO2"

    def test_delta_and_ratio(self):
        _store_pipeline(SAMPLE_PIPELINE)
        result = json.loads(compare_products(metric="Emisi CO2"))
        row = result["comparison"][0]
        assert "delta" in row
        assert "ratio" in row
        assert row["delta"] == round(row["Gas"] - row["Minyak"], 6)

    def test_pushes_table(self):
        _store_pipeline(SAMPLE_PIPELINE)
        compare_products()
        items = get_render_items()
        tables = [i for i in items if "headers" in i and "rows" in i]
        assert len(tables) >= 1
        assert "Category" in tables[-1]["headers"]


# ── revise_pipeline ──


class TestRevisePipeline:
    def test_no_pipeline_data(self):
        result = revise_pipeline("set_top_n", 10)
        assert "Error" in result

    def test_set_top_n(self):
        # Need enough flows per category to see difference
        many_flows = []
        for i in range(20):
            many_flows.append(
                {
                    "flow_name": f"Flow {i}",
                    "amount": 100.0 - i,
                    "unit": "kg",
                    "category": "Emisi CO2",
                    "direction": "output",
                    "process": "Process",
                }
            )
        _store_pipeline({"flows": many_flows})
        result = json.loads(revise_pipeline("set_top_n", 3))
        assert result["action"] == "set_top_n"
        assert result["new_value"] == 3
        # After top 3 + lainnya = 4
        assert result["after_flow_count"] == 4

    def test_unknown_action(self):
        _store_pipeline(SAMPLE_PIPELINE)
        result = json.loads(revise_pipeline("unknown_action", 5))
        assert "error" in result


# ── export_filtered ──


class TestExportFiltered:
    def test_no_pipeline_data(self):
        result = export_filtered(["Emisi CO2"])
        assert "Error" in result

    def test_filter_by_category(self, tmp_path):
        set_upload_dir(str(tmp_path))
        _store_pipeline(SAMPLE_PIPELINE)
        result = json.loads(export_filtered(["Emisi CO2"]))
        assert result["filtered_flow_count"] == 2
        assert "Emisi CO2" in result["exported_sections"]

    def test_emissions_shortcut(self, tmp_path):
        set_upload_dir(str(tmp_path))
        _store_pipeline(SAMPLE_PIPELINE)
        result = json.loads(export_filtered(["emissions"]))
        assert result["filtered_flow_count"] == 3  # 2 CO2 + 1 CH4
        assert "Emisi CO2" in result["exported_sections"]
        assert "Emisi CH4" in result["exported_sections"]

    def test_no_matching_sections(self):
        _store_pipeline(SAMPLE_PIPELINE)
        result = json.loads(export_filtered(["Nonexistent Section"]))
        assert "error" in result
        assert "available_categories" in result

    def test_pipeline_restored_after_export(self, tmp_path):
        set_upload_dir(str(tmp_path))
        _store_pipeline(SAMPLE_PIPELINE)
        export_filtered(["Emisi CO2"])
        # Pipeline should still have all 4 flows
        result = json.loads(explain_analysis("all"))
        assert result["flow_count"] == 4
