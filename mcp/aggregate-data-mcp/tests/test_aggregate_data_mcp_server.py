from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_fastmcp_server_builds_when_sdk_is_installed():
    pytest.importorskip("mcp.server.fastmcp")

    from app.mcp_server import build_mcp

    server = build_mcp()

    assert server.name == "aggregate_data_mcp"


def test_aggregate_service_extracts_metadata_and_averages_by_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pytest.importorskip("pandas")

    from app.service import get_service

    source = tmp_path / "sales.csv"
    source.write_text(
        "branch,revenue\n"
        "Jakarta,100\n"
        "Jakarta,200\n"
        "Bandung,50\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBENCH_DASHBOARD_STATE_PATH", str(tmp_path / "state.json"))

    service = get_service()
    metadata = service.extract_metadata(str(source))
    assert metadata["row_count"] == 3
    assert [column["name"] for column in metadata["columns"]] == ["branch", "revenue"]

    result = service.aggregate_data(
        str(source),
        (
            'SELECT "branch", AVG("revenue") AS avg_revenue '
            'FROM data GROUP BY "branch" ORDER BY avg_revenue DESC'
        ),
        dataset_id="avg_revenue_by_branch",
    )

    assert result["errors"] == []
    assert result["datasets"][0]["id"] == "avg_revenue_by_branch"
    assert result["datasets"][0]["records"][0] == {
        "branch": "Jakarta",
        "avg_revenue": 150.0,
    }

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["aggregate_datasets"]["avg_revenue_by_branch"][0]["branch"] == "Jakarta"


def test_aggregate_service_rejects_destructive_sql(tmp_path: Path):
    pytest.importorskip("pandas")

    from app.service import get_service

    source = tmp_path / "sales.csv"
    source.write_text("branch,revenue\nJakarta,100\n", encoding="utf-8")

    result = get_service().aggregate_data(str(source), "DROP TABLE data")

    assert result["datasets"] == []
    assert "Only read-only SELECT or WITH" in result["errors"][0]["error"]
