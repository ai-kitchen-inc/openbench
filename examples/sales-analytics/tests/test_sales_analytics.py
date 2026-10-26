"""Tests for sales-analytics example.

Proves that OpenBench SDK skills work for a NON-LCI domain without
any project skills, aliases.yaml, or domain-specific config.
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")


@pytest.fixture
def profile_dir(tmp_path):
    d = tmp_path / "profiles"
    d.mkdir()
    os.environ["OPENBENCH_PROFILE_DIR"] = str(d)
    yield d
    os.environ.pop("OPENBENCH_PROFILE_DIR", None)


@pytest.fixture
def sales_csv(tmp_path):
    """Create a small sales CSV file."""
    import pandas as pd

    df = pd.DataFrame(
        {
            "Region": ["APAC", "APAC", "EMEA", "EMEA", "Americas", "Americas"],
            "Product": ["Widget A", "Widget B", "Widget A", "Widget C", "Widget B", "Widget C"],
            "Revenue": [120000.0, 85000.0, 95000.0, 110000.0, 200000.0, 75000.0],
            "Units Sold": [400, 300, 280, 350, 600, 250],
            "Quarter": ["Q1", "Q1", "Q1", "Q2", "Q2", "Q2"],
        }
    )
    path = tmp_path / "sales_q1q2_2026.csv"
    df.to_csv(path, index=False)
    return str(path)


@pytest.fixture
def sales_xlsx(tmp_path):
    """Create a small sales Excel file with site-specific column names."""
    import pandas as pd

    df = pd.DataFrame(
        {
            "Sales Rep": ["Alice", "Bob", "Carol", "Dave"],
            "Territory": ["West", "East", "West", "East"],
            "Deal Size USD": [50000.0, 120000.0, 75000.0, 90000.0],
            "Win Rate %": [0.65, 0.42, 0.78, 0.55],
            "Pipeline Stage": ["Closed Won", "Negotiation", "Closed Won", "Proposal"],
        }
    )
    path = tmp_path / "pipeline_q2.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Pipeline", index=False)
    return str(path)


# ---------------------------------------------------------------------------
# Agent creation
# ---------------------------------------------------------------------------


class TestAgentCreation:
    def test_creates_agent_with_persona(self):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()
        assert agent._persona is not None
        assert "Sales Analytics" in agent._persona.soul

    def test_sdk_skills_auto_discovered(self):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()
        assert agent._skill_registry is not None
        names = {s.name for s in agent._skill_registry.all()}
        # All 5 SDK skills should be present — no project skills
        assert "data-context-extractor" in names
        assert "query-explorer" in names
        assert "data-visualization" in names
        assert "export-excel" in names
        assert "web-search" in names

    def test_no_project_skills(self):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()
        summary = agent._skill_registry.summary()
        assert len(summary["project_skills"]) == 0

    def test_sdk_tools_registered(self):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()
        tool_names = set(agent.tools._tools.keys())
        # Key tools that should be available
        assert "extract_file_context" in tool_names
        assert "filter_records" in tool_names
        assert "create_bar_chart" in tool_names
        assert "export_to_excel" in tool_names
        assert "web_search" in tool_names
        assert "save_column_profile" in tool_names


# ---------------------------------------------------------------------------
# SDK skill tools — direct invocation (no LLM)
# ---------------------------------------------------------------------------


class TestExtractFileContext:
    def test_csv_schema_detected(self, sales_csv):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()
        result = agent.tools.execute("extract_file_context", path=sales_csv)

        assert result["format"] == "csv"
        assert result["row_count"] >= 5  # extract reads _SAMPLE_ROWS by default
        col_names = {c["name"] for c in result["columns"]}
        assert "Region" in col_names
        assert "Revenue" in col_names
        assert "Units Sold" in col_names

    def test_xlsx_schema_detected(self, sales_xlsx):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()
        result = agent.tools.execute("extract_file_context", path=sales_xlsx)

        assert result["format"] == "xlsx"
        col_names = {c["name"] for c in result["columns"]}
        assert "Deal Size USD" in col_names
        assert "Win Rate %" in col_names

    def test_profile_status_needs_mapping(self, sales_csv, profile_dir):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()
        result = agent.tools.execute("extract_file_context", path=sales_csv)

        assert result["profile_status"] == "needs_mapping"
        # Revenue and Units Sold are numeric → should be in unmapped
        assert "Revenue" in result["unmapped_columns"]
        assert "Units Sold" in result["unmapped_columns"]


class TestColumnProfile:
    def test_save_and_retrieve(self, sales_csv, profile_dir):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()

        # Save profile
        result = agent.tools.execute(
            "save_column_profile",
            path=sales_csv,
            mappings=[
                {"column": "Region", "role": "category"},
                {"column": "Product", "role": "label"},
                {"column": "Revenue", "role": "amount"},
                {"column": "Units Sold", "role": "metric"},
                {"column": "Quarter", "role": "timestamp"},
            ],
        )
        assert result["saved"]

        # Now extract_file_context should return cached
        context = agent.tools.execute("extract_file_context", path=sales_csv)
        assert context["profile_status"] == "cached"
        assert context["column_roles"]["Revenue"] == "amount"
        assert context["column_roles"]["Region"] == "category"

    def test_profile_works_for_xlsx(self, sales_xlsx, profile_dir):
        """Column profiling works for Excel files too — not just CSV."""
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()
        agent.tools.execute(
            "save_column_profile",
            path=sales_xlsx,
            mappings=[
                {"column": "Deal Size USD", "role": "amount"},
                {"column": "Win Rate %", "role": "metric"},
                {"column": "Territory", "role": "category"},
            ],
        )
        context = agent.tools.execute("extract_file_context", path=sales_xlsx)
        assert context["profile_status"] == "cached"
        assert context["column_roles"]["Deal Size USD"] == "amount"

    def test_user_correction(self, sales_csv, profile_dir):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()
        agent.tools.execute(
            "save_column_profile",
            path=sales_csv,
            mappings=[{"column": "Revenue", "role": "amount"}],
        )
        # User corrects: "Revenue is actually a metric, not amount"
        agent.tools.execute(
            "update_column_profile",
            path=sales_csv,
            column="Revenue",
            role="metric",
            description="Quarterly revenue — use as metric not primary amount",
        )
        got = agent.tools.execute("get_column_profile", path=sales_csv)
        cols = got["profile"]["sheets"]["default"]["columns"]
        rev = next(c for c in cols if c["physical_name"] == "Revenue")
        assert rev["role"] == "metric"


class TestQueryExplorer:
    def test_filter_by_region(self, sales_csv):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()
        # Read the CSV first
        data = agent.tools.execute("read_csv_file", path=sales_csv, full=True)
        records = data["records"]

        # Filter APAC
        result = agent.tools.execute(
            "filter_records",
            records=records,
            conditions=[{"column": "Region", "op": "eq", "value": "APAC"}],
        )
        assert result["count"] == 2
        assert all(r["Region"] == "APAC" for r in result["records"])

    def test_group_revenue_by_region(self, sales_csv):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()
        data = agent.tools.execute("read_csv_file", path=sales_csv, full=True)

        result = agent.tools.execute(
            "group_and_aggregate",
            records=data["records"],
            group_by="Region",
            aggregate="sum",
            aggregate_column="Revenue",
        )
        by_region = {g["Region"]: g["sum_Revenue"] for g in result["groups"]}
        assert by_region["Americas"] == 275000.0  # 200000 + 75000
        assert by_region["APAC"] == 205000.0  # 120000 + 85000

    def test_top_n_by_revenue(self, sales_csv):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()
        data = agent.tools.execute("read_csv_file", path=sales_csv, full=True)

        result = agent.tools.execute(
            "top_n_records",
            records=data["records"],
            by="Revenue",
            n=3,
        )
        assert len(result["records"]) == 3
        assert result["records"][0]["Revenue"] == 200000.0  # Americas Widget B


class TestDataVisualization:
    def test_bar_chart_output(self):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()
        result = agent.tools.execute(
            "create_bar_chart",
            title="Revenue by Region",
            data=[
                {"name": "APAC", "value": 205000},
                {"name": "EMEA", "value": 205000},
                {"name": "Americas", "value": 275000},
            ],
        )
        assert result["type"] == "bar"
        assert result["title"] == "Revenue by Region"
        assert len(result["data"]) == 3

    def test_chart_detected_by_renderer(self):
        from sales_analytics import create_analyst_agent

        from openbench.chat.renderers.chart import ChartRenderer

        agent = create_analyst_agent()
        result = agent.tools.execute(
            "create_pie_chart",
            title="Product Mix",
            data=[
                {"name": "Widget A", "value": 215000},
                {"name": "Widget B", "value": 285000},
                {"name": "Widget C", "value": 185000},
            ],
        )
        assert ChartRenderer().detect(result)


class TestExportExcel:
    def test_export_produces_file(self, tmp_path):
        from sales_analytics import create_analyst_agent

        os.environ["OPENBENCH_EXPORT_DIR"] = str(tmp_path)
        agent = create_analyst_agent()

        result = agent.tools.execute(
            "export_to_excel",
            records=[
                {"Region": "APAC", "Revenue": 205000},
                {"Region": "Americas", "Revenue": 275000},
            ],
            filename="sales_summary.xlsx",
        )
        assert "error" not in result
        assert result["name"].startswith("sales_summary-")
        assert result["name"].endswith(".xlsx")

        os.environ.pop("OPENBENCH_EXPORT_DIR", None)


class TestEndToEndNoDomainConfig:
    """The whole point: no aliases.yaml, no xql, no domain config.
    Everything works via SDK skills + column profiling."""

    def test_full_analysis_flow(self, sales_csv, profile_dir):
        from sales_analytics import create_analyst_agent

        agent = create_analyst_agent()

        # Step 1: Extract file context
        context = agent.tools.execute("extract_file_context", path=sales_csv)
        assert context["profile_status"] == "needs_mapping"
        assert "Revenue" in context["unmapped_columns"]

        # Step 2: Save column profile (LLM would infer this)
        agent.tools.execute(
            "save_column_profile",
            path=sales_csv,
            mappings=[
                {"column": "Region", "role": "category"},
                {"column": "Product", "role": "label"},
                {"column": "Revenue", "role": "amount"},
                {"column": "Units Sold", "role": "metric"},
                {"column": "Quarter", "role": "timestamp"},
            ],
        )

        # Step 3: Read data
        data = agent.tools.execute("read_csv_file", path=sales_csv, full=True)
        records = data["records"]

        # Step 4: Analyze — group by region
        grouped = agent.tools.execute(
            "group_and_aggregate",
            records=records,
            group_by="Region",
            aggregate="sum",
            aggregate_column="Revenue",
        )
        by_region = {g["Region"]: g["sum_Revenue"] for g in grouped["groups"]}

        # Step 5: Visualize
        chart_data = [{"name": k, "value": v} for k, v in by_region.items()]
        chart = agent.tools.execute(
            "create_bar_chart",
            title="Q1-Q2 2026 Revenue by Region",
            data=chart_data,
        )
        assert chart["type"] == "bar"

        # Step 6: Verify profile cached for next time
        context2 = agent.tools.execute("extract_file_context", path=sales_csv)
        assert context2["profile_status"] == "cached"
        assert context2["column_roles"]["Revenue"] == "amount"

        # DONE: Full analytics workflow — zero domain config needed
