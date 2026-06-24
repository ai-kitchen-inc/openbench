from __future__ import annotations

from pathlib import Path

import pytest


def test_fastmcp_server_builds_when_sdk_is_installed():
    pytest.importorskip("mcp.server.fastmcp")

    from app.mcp_server import build_mcp

    server = build_mcp()

    assert server.name == "dashboard_generator_mcp"


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
