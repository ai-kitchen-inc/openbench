from __future__ import annotations

from pathlib import Path

import pytest


def test_fastmcp_server_builds_when_sdk_is_installed():
    pytest.importorskip("mcp.server.fastmcp")

    from app.mcp_server import build_mcp

    server = build_mcp()

    assert server.name == "dashboard_generator_mcp"


def test_generate_dashboard_schema_prefers_canonical_view_model():
    from app.dashboard_tools import GENERATE_DASHBOARD_SCHEMA

    function = GENERATE_DASHBOARD_SCHEMA["function"]
    assert "canonical OpenBench shape" in function["description"]
    assert "x_field" in function["parameters"]["properties"]["view_model"]["description"]


def test_dashboard_service_generates_a2ui_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("pandas")

    from app.service import get_service

    source = tmp_path / "sales.csv"
    source.write_text(
        "tanggal,produk,pendapatan\n"
        "2026-06-01,Latte,1250000\n"
        "2026-06-02,Americano,980000\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBENCH_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("OPENBENCH_EXPORT_URL_BASE", "/downloads")
    monkeypatch.setenv("DASHBOARD_RENDER_ADAPTER", "default")

    service = get_service()
    metadata = service.extract_metadata(str(source))
    assert metadata["row_count"] == 2

    aggregate = service.aggregate_data(
        str(source),
        'SELECT "tanggal", SUM("pendapatan") AS pendapatan '
        'FROM data GROUP BY "tanggal" ORDER BY pendapatan DESC',
        dataset_id="top_days",
    )
    assert aggregate["errors"] == []
    assert aggregate["datasets"][0]["records"][0]["tanggal"] == "2026-06-01"

    result = service.generate_dashboard(
        {
            "title": "Dashboard Penjualan Kopi",
            "datasets": {"top_days": aggregate["datasets"][0]["records"]},
            "sections": [
                {
                    "title": "Tabel",
                    "items": [
                        {
                            "type": "table",
                            "title": "5 Hari dengan Pendapatan Tertinggi",
                            "dataset": "top_days",
                            "columns": [
                                {"key": "tanggal", "label": "Tanggal"},
                                {"field": "pendapatan", "header": "Pendapatan"},
                            ],
                        }
                    ],
                }
            ],
        }
    )

    assert result["type"] == "dashboard"
    assert result["render_mode"] == "a2ui"
    assert Path(result["path"]).exists()
    assert result["datasets"]["top_days"][0]["pendapatan"] == 1250000


def test_dashboard_service_generates_with_uploaded_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pytest.importorskip("pandas")

    from app.service import get_service

    template = (
        Path(__file__).resolve().parents[3]
        / "examples"
        / "general-chat"
        / "template-dashboard-sample"
        / "template.html"
    )
    monkeypatch.setenv("OPENBENCH_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("OPENBENCH_EXPORT_URL_BASE", "/downloads")
    monkeypatch.setenv("DASHBOARD_RENDER_ADAPTER", "default")
    monkeypatch.setenv("OPENBENCH_DASHBOARD_STATE_PATH", str(tmp_path / "dashboard_state.json"))

    result = get_service().generate_dashboard(
        {
            "title": "MCP Template Dashboard",
            "kpis": [{"label": "Revenue", "value": 100}],
            "sections": [],
        },
        template_path=str(template),
    )

    html = Path(result["path"]).read_text(encoding="utf-8")
    assert result["render_mode"] == "a2ui"
    assert result["customTemplate"]["format"] == "html"
    assert result["templateSource"] == "user"
    assert result["templateFormat"] == "html"
    assert 'data-custom-template="executive-html"' in html
    assert "MCP Template Dashboard" in html


def test_dashboard_service_hydrates_cached_aggregate_dataset_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pytest.importorskip("pandas")

    from app.service import get_service

    source = tmp_path / "coffee.csv"
    source.write_text(
        "coffee_name,money\nLatte,10\nLatte,15\nEspresso,5\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBENCH_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("OPENBENCH_EXPORT_URL_BASE", "/downloads")
    monkeypatch.setenv("DASHBOARD_RENDER_ADAPTER", "default")

    service = get_service()
    aggregate = service.aggregate_data(
        str(source),
        [
            {
                "name": "revenue_by_coffee",
                "sql": (
                    "SELECT coffee_name, SUM(money) AS revenue "
                    "FROM data GROUP BY coffee_name ORDER BY revenue DESC"
                ),
            }
        ],
    )
    assert aggregate["errors"] == []
    assert aggregate["datasets"][0]["id"] == "revenue_by_coffee"

    result = service.generate_dashboard(
        {
            "title": "Coffee Sales",
            "components": [
                {"type": "kpi", "content": {"title": "Total Revenue", "value": 30}},
                {
                    "type": "chart",
                    "content": {
                        "title": "Revenue by Coffee",
                        "type": "bar",
                        "data": "revenue_by_coffee",
                        "x": "coffee_name",
                        "y": "revenue",
                    },
                },
            ],
        }
    )

    html = Path(result["path"]).read_text(encoding="utf-8")
    assert result["datasets"]["revenue_by_coffee"][0]["coffee_name"] == "Latte"
    assert result["kpis"][0]["label"] == "Total Revenue"
    assert "Revenue by Coffee" in html
    assert "Latte" in html
    assert "No chart data available." not in html


def test_dashboard_service_hydrates_placeholder_charts_from_cached_aggregates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pytest.importorskip("pandas")

    from app.service import get_service

    source = tmp_path / "coffee.csv"
    source.write_text(
        "coffee_name,month,money\nLatte,Jan,10\nLatte,Feb,15\nEspresso,Jan,5\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBENCH_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("OPENBENCH_EXPORT_URL_BASE", "/downloads")
    monkeypatch.setenv("DASHBOARD_RENDER_ADAPTER", "default")

    service = get_service()
    aggregate = service.aggregate_data(
        str(source),
        [
            {
                "name": "revenue_by_coffee_type",
                "sql": (
                    "SELECT coffee_name, SUM(money) AS revenue "
                    "FROM data GROUP BY coffee_name ORDER BY revenue DESC"
                ),
            },
            {
                "name": "monthly_sales",
                "sql": "SELECT month, SUM(money) AS sales FROM data GROUP BY month ORDER BY month",
            },
        ],
    )
    assert aggregate["errors"] == []

    result = service.generate_dashboard(
        {
            "title": "Coffee Sales Executive Dashboard",
            "kpis": [{"label": "Total Revenue", "value": 30}],
            "sections": [
                {
                    "title": "Dashboard",
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "bar",
                            "title": "Revenue by Coffee Type",
                            "data": [],
                            "x_field": "name",
                            "y_field": "value",
                        },
                        {
                            "type": "chart",
                            "chart_type": "line",
                            "title": "Monthly Sales Trend",
                            "data": [],
                            "x_field": "name",
                            "y_field": "value",
                        },
                    ],
                }
            ],
        }
    )

    html = Path(result["path"]).read_text(encoding="utf-8")
    items = result["viewModel"]["sections"][0]["items"]
    assert items[0]["dataset"] == "revenue_by_coffee_type"
    assert items[0]["x_field"] == "coffee_name"
    assert items[0]["y_field"] == "revenue"
    assert items[1]["dataset"] == "monthly_sales"
    assert items[1]["x_field"] == "month"
    assert items[1]["y_field"] == "sales"
    assert "Latte" in html
    assert "Jan" in html
    assert "No chart data available." not in html


def test_dashboard_service_hydrates_placeholder_charts_from_last_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pytest.importorskip("pandas")

    from app import dashboard_tools
    from app.service import get_service

    source = tmp_path / "coffee.csv"
    source.write_text(
        "sale_date,coffee_name,Time_of_Day,cash_type,money\n"
        "2026-01-01,Latte,Morning,card,10\n"
        "2026-01-01,Espresso,Night,cash,5\n"
        "2026-01-02,Latte,Night,card,15\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBENCH_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("OPENBENCH_EXPORT_URL_BASE", "/downloads")
    monkeypatch.setenv("DASHBOARD_RENDER_ADAPTER", "default")

    service = get_service()
    metadata = service.extract_metadata(str(source))
    assert "error" not in metadata
    dashboard_tools._LAST_AGGREGATE_DATASETS.clear()
    dashboard_tools._LAST_SOURCE_CONTEXT.clear()

    result = service.generate_dashboard(
        {
            "title": "Coffee Sales Executive Dashboard",
            "kpis": [{"label": "Total Revenue", "value": 30}],
            "datasets": {},
            "sections": [
                {
                    "title": "Dashboard",
                    "items": [
                        {
                            "type": "chart",
                            "chart_type": "line",
                            "title": "Daily Sales Trend",
                            "data": [],
                            "x_field": "name",
                            "y_field": "value",
                        },
                        {
                            "type": "chart",
                            "chart_type": "pie",
                            "title": "Sales by Coffee Type",
                            "data": [],
                            "x_field": "name",
                            "y_field": "value",
                        },
                        {
                            "type": "chart",
                            "chart_type": "pie",
                            "title": "Sales by Payment Method",
                            "data": [],
                            "x_field": "name",
                            "y_field": "value",
                        },
                    ],
                }
            ],
        }
    )

    html = Path(result["path"]).read_text(encoding="utf-8")
    by_title = {
        item["title"]: item
        for item in result["viewModel"]["sections"][0]["items"]
    }
    assert by_title["Daily Sales Trend"]["x_field"] == "sale_date"
    assert by_title["Sales by Coffee Type"]["x_field"] == "coffee_name"
    assert by_title["Sales by Payment Method"]["x_field"] == "cash_type"
    assert len(result["viewModel"]["datasets"]) >= 3
    assert "Latte" in html
    assert "card" in html
    assert "2026-01-01" in html
    assert "No chart data available." not in html
