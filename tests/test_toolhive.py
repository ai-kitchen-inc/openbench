"""Tests for ToolHive-managed MCP discovery helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openbench.mcp.config import MCPServerConnectionConfig
from openbench.mcp.errors import MCPTransportError
from openbench.mcp.toolhive import (
    ToolHiveError,
    ToolHiveService,
    ToolHiveWorkload,
    _toolhive_ui_cli_candidates,
    detect_toolhive_transport,
    parse_toolhive_mcpservers_json,
    rewrite_toolhive_url,
    toolhive_workload_to_mcp_config,
    validate_toolhive_name,
    validate_toolhive_proxy_url,
)
from openbench.mcp.transports import build_transport


def test_detect_toolhive_transport_for_streamable_http_and_sse():
    assert detect_toolhive_transport("http://127.0.0.1:19767/mcp") == "streamable-http"
    assert detect_toolhive_transport("http://127.0.0.1:22089/sse") == "sse"
    assert detect_toolhive_transport("http://127.0.0.1:22089/sse#sqlite") == "sse"

    with pytest.raises(ToolHiveError, match="/mcp or /sse"):
        detect_toolhive_transport("http://127.0.0.1:22089/not-mcp")


def test_rewrite_toolhive_url_for_container_host():
    assert (
        rewrite_toolhive_url("http://127.0.0.1:19767/mcp", host="host.docker.internal")
        == "http://host.docker.internal:19767/mcp"
    )
    assert (
        rewrite_toolhive_url("http://192.168.1.10:19767/mcp", host="host.docker.internal")
        == "http://192.168.1.10:19767/mcp"
    )


def test_validate_toolhive_proxy_url_rejects_unsafe_remote_by_default():
    assert validate_toolhive_proxy_url("http://localhost:19767/mcp")
    assert validate_toolhive_proxy_url("http://host.containers.internal:19767/mcp")

    with pytest.raises(ToolHiveError, match="local proxy URLs must use http"):
        validate_toolhive_proxy_url("https://127.0.0.1:19767/mcp")

    with pytest.raises(ToolHiveError, match="localhost"):
        validate_toolhive_proxy_url("http://example.com/mcp")


def test_validate_toolhive_name_rejects_shelly_names():
    assert validate_toolhive_name("toolhive-doc-mcp") == "toolhive-doc-mcp"
    with pytest.raises(ToolHiveError):
        validate_toolhive_name("bad name; rm")


def test_parse_thv_list_mcpservers_json():
    raw = json.dumps(
        {
            "mcpServers": {
                "github": {"url": "http://127.0.0.1:55264/mcp"},
                "sqlite": {"url": "http://127.0.0.1:22089/sse#sqlite"},
            }
        }
    )

    workloads = parse_toolhive_mcpservers_json(raw)

    assert [workload.name for workload in workloads] == ["github", "sqlite"]
    assert workloads[0].transport == "streamable-http"
    assert workloads[1].transport == "sse"


def test_toolhive_workload_to_mcp_config_namespaces_and_allows_server():
    config = toolhive_workload_to_mcp_config(
        ToolHiveWorkload(name="ToolHive Docs", status="running", url="http://127.0.0.1:19767/mcp")
    )

    assert config.namespace == "toolhive-docs"
    assert config.transport == "streamable-http"
    assert config.allowed is True
    assert config.enabled is True


def test_toolhive_status_api_mapping(monkeypatch):
    class FakeResponse:
        content = b'{"version":"v1.2.3"}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"version": "v1.2.3"}

    import requests

    monkeypatch.setattr(requests, "request", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(ToolHiveService, "_cli_available", lambda self: False)

    status = ToolHiveService().status()

    assert status.available is True
    assert status.api_available is True
    assert status.version == "v1.2.3"
    assert status.management_mode == "api"


def test_toolhive_cli_fallback_for_status():
    class FakeService(ToolHiveService):
        def _api_get(self, path):
            raise ToolHiveError("api down")

        def _resolve_cli(self):
            return ("thv", "cli")

        def _run_thv(self, args):
            class Result:
                stdout = "ToolHive v9.9.9\n"

            return Result()

    status = FakeService().status()

    assert status.available is True
    assert status.api_available is False
    assert status.cli_available is True
    assert status.version == "ToolHive v9.9.9"
    assert status.management_mode == "cli"


def test_toolhive_unavailable_status_is_user_safe():
    class FakeService(ToolHiveService):
        def _api_get(self, path):
            raise ToolHiveError("api down")

        def _run_thv(self, args):
            raise ToolHiveError("thv missing")

    status = FakeService().status()

    assert status.available is False
    assert "Install ToolHive" in (status.setup_hint or "")
    assert status.management_mode == "unavailable"


def test_toolhive_cli_uses_utf8_replacement_decoding(monkeypatch):
    captured_kwargs = {}

    class FakeService(ToolHiveService):
        def _resolve_cli(self):
            return ("thv", "cli")

    class FakeResult:
        returncode = 0
        stdout = "ToolHive v9.9.9\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured_kwargs.update(kwargs)
        return FakeResult()

    monkeypatch.setattr("openbench.mcp.toolhive.subprocess.run", fake_run)

    result = FakeService()._run_thv(["version"])

    assert result.stdout == "ToolHive v9.9.9\n"
    assert captured_kwargs["encoding"] == "utf-8"
    assert captured_kwargs["errors"] == "replace"
    assert captured_kwargs["text"] is True


def test_toolhive_detects_path_cli_before_ui_cli(monkeypatch):
    monkeypatch.setattr("openbench.mcp.toolhive.shutil.which", lambda name: "/usr/bin/thv")

    class FakeService(ToolHiveService):
        def _path_exists(self, path):
            return path.endswith("ToolHive/bin/thv.exe")

    service = FakeService()

    assert service._resolve_cli() == ("/usr/bin/thv", "cli")


def test_toolhive_detects_ui_bundled_cli_when_path_cli_missing(monkeypatch):
    monkeypatch.setattr("openbench.mcp.toolhive.shutil.which", lambda name: None)
    expected_path = str(Path("C:\\Users\\Ada\\AppData\\Local") / "ToolHive" / "bin" / "thv.exe")

    class FakeService(ToolHiveService):
        def _path_exists(self, path):
            return path == expected_path

    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\Ada\\AppData\\Local")
    service = FakeService()

    assert service._resolve_cli() == (expected_path, "ui-cli")


def test_toolhive_ui_cli_candidates_include_documented_paths(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\Ada\\AppData\\Local")
    monkeypatch.setattr("openbench.mcp.toolhive.Path.home", lambda cls=None: Path("/home/ada"))

    candidates = _toolhive_ui_cli_candidates()

    assert str(Path("C:\\Users\\Ada\\AppData\\Local") / "ToolHive" / "bin" / "thv.exe") in candidates
    assert str(Path("/home/ada") / ".toolhive" / "bin" / "thv") in candidates


def test_start_workload_uses_long_start_timeout():
    class FakeService(ToolHiveService):
        def __init__(self):
            super().__init__(timeout_seconds=2.0, start_timeout_seconds=77.0)
            self.cli_timeout = None

        def _api_post(self, path, payload, *, timeout_seconds=None):
            assert timeout_seconds == 77.0
            raise ToolHiveError("api rejected request")

        def _run_thv(self, args, *, timeout_seconds=None):
            self.cli_timeout = timeout_seconds

            class Result:
                stdout = ""

            return Result()

        def _find_started_workload(self, name):
            return ToolHiveWorkload(
                name=name,
                status="running",
                url="http://127.0.0.1:19767/mcp",
            )

    service = FakeService()
    workload = service.start_workload("io.github.stacklok/aws-documentation")

    assert service.cli_timeout == 77.0
    assert workload.name == "aws-documentation"


def test_sse_transport_reports_clear_unsupported_message():
    config = MCPServerConnectionConfig(transport="sse", url="http://127.0.0.1:22089/sse")

    with pytest.raises(MCPTransportError, match="SSE MCP transport is not yet supported"):
        build_transport(config)
