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
