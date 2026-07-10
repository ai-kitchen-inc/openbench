from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from openbench.cli.commands import demo as demo_module


def test_discover_demos_includes_general_chat_mcp_variants():
    demos = {item["name"]: item for item in demo_module._discover_demos()}

    image_search = demos["general-chat-image-search"]
    sam = demos["general-chat-sam-segmentation"]
    all_mcp = demos["general-chat-all"]
    plain = demos["general-chat"]

    assert image_search["type"] == "server"
    assert image_search["dir"] == plain["dir"]
    assert image_search["has_frontend"] is True
    assert image_search["port"] == 8005
    assert image_search["mcp_variant"] == "image-search"

    assert sam["type"] == "server"
    assert sam["dir"] == plain["dir"]
    assert sam["has_frontend"] is True
    assert sam["port"] == 8005
    assert sam["mcp_variant"] == "sam-segmentation"

    assert all_mcp["type"] == "server"
    assert all_mcp["dir"] == plain["dir"]
    assert all_mcp["has_frontend"] is True
    assert all_mcp["port"] == 8005
    assert all_mcp["mcp_profile"] == "all"

    assert "mcp_variant" not in plain


def test_run_demo_help_documents_all_mcp_option():
    result = CliRunner().invoke(demo_module.run_demo, ["--help"])

    assert result.exit_code == 0
    assert "--all-mcp" in result.output
    assert "all bundled MCP configs" in result.output


def test_discover_demos_ignores_virtualenv_scripts(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    examples = root / "examples"
    venv_scripts = examples / "ignored-demo" / ".venv" / "Lib" / "site-packages"
    venv_scripts.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'demo-test'\n", encoding="utf-8")
    (venv_scripts / "accidental_demo.py").write_text(
        '"""Should not be discovered."""\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(demo_module, "_find_project_root", lambda: root)

    demos = demo_module._discover_demos()

    assert "ignored-demo/.venv/Lib/site-packages/accidental" not in {
        item["name"] for item in demos
    }


def test_general_chat_image_search_env_creates_expected_paths(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    demo_dir = root / "examples" / "general-chat"
    home_dir = tmp_path / "home"
    demo_dir.mkdir(parents=True)

    monkeypatch.setattr(demo_module, "_find_project_root", lambda: root)
    monkeypatch.setattr(demo_module.Path, "home", staticmethod(lambda: home_dir))

    env = demo_module._general_chat_mcp_env("image-search", demo_dir)

    assert env["GENERAL_CHAT_MCP_ENABLED"] == "1"
    assert env["GENERAL_CHAT_MCP_MODE"] == "external"
    assert env["GENERAL_CHAT_MCP_CONFIG"] == "mcp/image-search-docker.yaml"
    assert env["GENERAL_CHAT_MCP_REGISTRY_ENABLED"] == "0"
    assert env["GENERAL_CHAT_MCP_APPROVED_TOOLS"] == (
        "image_search.list_index_stats,image_search.search_similar_images"
    )
    assert env["IMAGE_SEARCH_MCP_DATA_PATH"].endswith("/mcp/image-search-mcp/data")
    assert env["IMAGE_SEARCH_MCP_MODELS_PATH"].endswith("/mcp/image-search-mcp/models")
    assert env["IMAGE_SEARCH_MCP_UPLOADS_PATH"].endswith("/examples/general-chat/uploads")
    assert env["IMAGE_SEARCH_MCP_HF_CACHE_PATH"].endswith("/home/.cache/huggingface")
    assert Path(env["GENERAL_CHAT_IMAGE_SEARCH_PREVIEW_DIR"]).is_dir()
    assert (demo_dir / "uploads").is_dir()
    assert (root / "mcp" / "image-search-mcp" / "data" / "previews").is_dir()
    assert (root / "mcp" / "image-search-mcp" / "models").is_dir()
    assert (home_dir / ".cache" / "huggingface").is_dir()


def test_general_chat_dashboard_generator_env_uses_split_aggregate_mcp(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    demo_dir = root / "examples" / "general-chat"
    demo_dir.mkdir(parents=True)

    monkeypatch.setattr(demo_module, "_find_project_root", lambda: root)

    env = demo_module._general_chat_mcp_env("dashboard-generator", demo_dir)

    assert env["GENERAL_CHAT_MCP_ENABLED"] == "1"
    assert env["GENERAL_CHAT_MCP_MODE"] == "external"
    assert env["GENERAL_CHAT_MCP_CONFIG"] == "mcp/dashboard-generator-stdio.yaml"
    assert env["GENERAL_CHAT_MCP_APPROVED_TOOLS"] == (
        "aggregate_data.extract_metadata,"
        "aggregate_data.aggregate_data,"
        "dashboard_generator.generate_dashboard"
    )
    assert "dashboard_generator.extract_metadata" not in env["GENERAL_CHAT_MCP_APPROVED_TOOLS"]
    assert Path(env["DASHBOARD_GENERATOR_MCP_PYTHONPATH"].split(os.pathsep)[-1]) == (
        root / "mcp" / "dashboard-generator-mcp"
    ).resolve()
    assert Path(env["AGGREGATE_DATA_MCP_PYTHONPATH"].split(os.pathsep)[-1]) == (
        root / "mcp" / "aggregate-data-mcp"
    ).resolve()
    assert Path(env["OPENBENCH_DASHBOARD_STATE_PATH"]).parent == (
        demo_dir / ".openbench"
    ).resolve()
    assert (demo_dir / ".openbench").is_dir()


def test_general_chat_sam_env_creates_expected_upload_path(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    demo_dir = root / "examples" / "general-chat"
    demo_dir.mkdir(parents=True)

    monkeypatch.setattr(demo_module, "_find_project_root", lambda: root)

    env = demo_module._general_chat_mcp_env("sam-segmentation", demo_dir)

    assert env["GENERAL_CHAT_MCP_ENABLED"] == "1"
    assert env["GENERAL_CHAT_MCP_MODE"] == "external"
    assert env["GENERAL_CHAT_MCP_CONFIG"] == "mcp/sam-segmentation-docker.yaml"
    assert env["GENERAL_CHAT_MCP_APPROVED_TOOLS"] == "sam_segmentation.count_objects_with_sam3"
    assert env["GENERAL_CHAT_MCP_REGISTRY_ENABLED"] == "0"
    assert env["SAM_SEGMENTATION_MCP_UPLOADS_PATH"].endswith("/examples/general-chat/uploads")
    assert env["SAM_SEGMENTATION_MCP_DEBUG_PATH"].endswith(
        "/examples/general-chat/uploads/_sam_debug"
    )
    assert (demo_dir / "uploads").is_dir()
    assert (demo_dir / "uploads" / "_sam_debug").is_dir()


def test_general_chat_plain_env_enables_unified_mcp_registry():
    env = demo_module._general_chat_plain_env()

    assert env == {
        "GENERAL_CHAT_MCP_ENABLED": "0",
        "GENERAL_CHAT_MCP_REGISTRY_ENABLED": "1",
    }


def test_general_chat_all_mcp_env_creates_paths_and_seeds_registry(tmp_path, monkeypatch):
    from openbench.mcp.toolhive import ToolHiveWorkload

    root = tmp_path / "repo"
    demo_dir = root / "examples" / "general-chat"
    mcp_dir = demo_dir / "mcp"
    home_dir = tmp_path / "home"
    mcp_dir.mkdir(parents=True)
    (demo_dir / "src").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'demo-test'\n", encoding="utf-8")

    configs = {
        "filesystem-mcp.yaml": (
            "filesystem",
            "npx",
            ['"-y"', '"@modelcontextprotocol/server-filesystem"', '"${GENERAL_CHAT_MCP_SANDBOX}"'],
        ),
        "generic-api-docker.yaml": ("generic_api", "docker", ['"run"', '"generic-api"']),
        "image-search-docker.yaml": ("image_search", "docker", ['"run"', '"image-search"']),
        "sam-segmentation-docker.yaml": ("sam_segmentation", "docker", ['"run"', '"sam"']),
        "docker-mcp-gateway.yaml": ("docker", "docker", ['"mcp"', '"gateway"', '"run"']),
        "custom-function-docker.yaml": (
            "custom_function",
            "docker",
            ['"run"', '"-v"', '"${CUSTOM_FN_DATA_PATH}:/data/functions:ro"', '"fn-image"'],
        ),
    }
    for filename, (server_name, command, args) in configs.items():
        (mcp_dir / filename).write_text(
            "\n".join(
                [
                    "mcp:",
                    "  servers:",
                    f"    {server_name}:",
                    "      transport: stdio",
                    f"      command: {command}",
                    "      args:",
                    *[f"        - {arg}" for arg in args],
                    f"      namespace: {server_name}",
                    "      allowed: true",
                ]
            ),
            encoding="utf-8",
        )
    default_registry_path = demo_dir / ".openbench" / "mcp_registry" / "servers.json"
    default_registry_path.parent.mkdir(parents=True)
    default_registry_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "id": "server-stale-time",
                        "name": "time",
                        "config": {
                            "transport": "streamable-http",
                            "url": "http://127.0.0.1:61632/mcp",
                            "namespace": "time",
                        },
                        "source": "toolhive",
                        "provider_kind": "toolhive",
                        "source_type": "toolhive",
                        "server_namespace": "time",
                        "enabled": True,
                        "status": "registered",
                    }
                ],
                "tools": {},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(demo_module, "_find_project_root", lambda: root)
    monkeypatch.setattr(demo_module.Path, "home", staticmethod(lambda: home_dir))
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"))
    monkeypatch.setattr(
        demo_module,
        "_list_running_toolhive_workloads",
        lambda: [
            ToolHiveWorkload(
                name="git",
                status="running",
                url="http://127.0.0.1:39670/mcp",
            )
        ],
    )

    env = demo_module._general_chat_all_mcp_env(demo_dir)

    assert env["GENERAL_CHAT_MCP_ENABLED"] == "0"
    assert env["GENERAL_CHAT_MCP_REGISTRY_ENABLED"] == "1"
    assert Path(env["GENERAL_CHAT_STORAGE_ROOT"]) == (demo_dir / ".openbench" / "all-mcp").resolve()
    assert env["IMAGE_SEARCH_MCP_DATA_PATH"].endswith("/mcp/image-search-mcp/data")
    assert env["SAM_SEGMENTATION_MCP_DEBUG_PATH"].endswith(
        "/examples/general-chat/uploads/_sam_debug"
    )
    assert env["GENERIC_API_USERNAME"] == ""
    assert env["GENERIC_API_PASSWORD"] == ""
    assert env["GENERIC_API_TIMEOUT_SECONDS"] == "30"
    assert Path(env["GENERAL_CHAT_UPLOAD_DIR"]).is_dir()
    assert Path(env["GENERAL_CHAT_DOWNLOAD_DIR"]).is_dir()
    assert Path(env["GENERAL_CHAT_MCP_SANDBOX"]).is_dir()
    assert Path(env["GENERAL_CHAT_IMAGE_SEARCH_PREVIEW_DIR"]).is_dir()
    assert Path(env["CUSTOM_FN_DATA_PATH"]).is_dir()
    assert Path(env["CUSTOM_FN_DATA_PATH"]) == (
        Path(env["GENERAL_CHAT_STORAGE_ROOT"]) / "custom-functions"
    )
    assert default_registry_path.exists()

    state_path = Path(env["GENERAL_CHAT_STORAGE_ROOT"]) / "mcp_registry" / "servers.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    server_names = {item["name"] for item in state["servers"]}
    assert {
        "custom_function",
        "docker",
        "filesystem",
        "generic_api",
        "git",
        "image_search",
        "openbench",
        "sam_segmentation",
    }.issubset(server_names)
    custom_fn = next(item for item in state["servers"] if item["name"] == "custom_function")
    # ${CUSTOM_FN_DATA_PATH} must be expanded at seed time, not stored raw.
    assert f"{env['CUSTOM_FN_DATA_PATH']}:/data/functions:ro" in custom_fn["config"]["args"]
    assert "time" not in server_names


def test_general_chat_all_mcp_warns_when_image_search_docker_image_missing(
    tmp_path,
    monkeypatch,
    capsys,
):
    root = tmp_path / "repo"
    demo_dir = root / "examples" / "general-chat"
    home_dir = tmp_path / "home"
    demo_dir.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'demo-test'\n", encoding="utf-8")

    class FakeInspectResult:
        def __init__(self, returncode, stderr):
            self.returncode = returncode
            self.stdout = ""
            self.stderr = stderr

    def fake_run(cmd, capture_output, text, timeout, check):
        assert cmd[1:3] == ["image", "inspect"]
        assert capture_output is True
        assert text is True
        assert timeout == 10
        assert check is False
        if cmd[3] == "openbench/generic-api-mcp:cpu":
            return FakeInspectResult(0, "")
        if cmd[3] == "custom-function-mcp:local":
            return FakeInspectResult(0, "")
        assert cmd[3] == "openbench/image-search-mcp:cpu"
        return FakeInspectResult(1, "No such image: openbench/image-search-mcp:cpu")

    monkeypatch.setattr(demo_module, "_find_project_root", lambda: root)
    monkeypatch.setattr(demo_module.Path, "home", staticmethod(lambda: home_dir))
    monkeypatch.setattr(demo_module.shutil, "which", lambda name: name)
    monkeypatch.setattr(demo_module, "_command_available", lambda *names: True)
    monkeypatch.setattr(demo_module.subprocess, "run", fake_run)

    demo_module._general_chat_all_mcp_env(demo_dir, seed_registry=False)

    output = capsys.readouterr().out
    normalized_output = " ".join(output.split())
    assert "openbench/image-search-mcp:cpu" in output
    assert "Connection closed" in output
    assert "docker compose -f" in output
    assert "mcp\\image-search-mcp\\docker-compose.yml" in output
    assert "--profile" in output
    assert "cpu build" in normalized_output
    assert "No such image" in output


def test_run_demo_all_mcp_flag_and_alias_pass_profile(monkeypatch):
    demo_dir = Path("examples/general-chat")
    demos = [
        {
            "name": "general-chat",
            "type": "server",
            "dir": demo_dir,
            "port": 8005,
            "has_frontend": True,
        },
        {
            "name": "general-chat-all",
            "type": "server",
            "dir": demo_dir,
            "port": 8005,
            "has_frontend": True,
            "mcp_profile": "all",
        },
    ]
    calls: list[dict[str, object]] = []

    def fake_run_server(info, port, no_frontend, no_install, *, all_mcp=False):
        calls.append(
            {
                "name": info["name"],
                "port": port,
                "no_frontend": no_frontend,
                "no_install": no_install,
                "all_mcp": all_mcp,
            }
        )

    monkeypatch.setattr(demo_module, "_discover_demos", lambda: demos)
    monkeypatch.setattr(demo_module, "_run_server", fake_run_server)

    runner = CliRunner()
    base = runner.invoke(
        demo_module.run_demo,
        ["general-chat", "--all-mcp", "--no-frontend", "--no-install"],
    )
    alias = runner.invoke(
        demo_module.run_demo,
        ["general-chat-all", "--all-mcp", "--no-frontend", "--no-install"],
    )

    assert base.exit_code == 0
    assert alias.exit_code == 0
    assert [call["name"] for call in calls] == ["general-chat", "general-chat-all"]
    assert all(call["all_mcp"] is True for call in calls)


def test_run_demo_rejects_all_mcp_for_non_general_chat(monkeypatch):
    monkeypatch.setattr(
        demo_module,
        "_discover_demos",
        lambda: [
            {
                "name": "sales-analytics",
                "type": "server",
                "dir": Path("examples/sales-analytics"),
                "port": 8000,
                "has_frontend": True,
            }
        ],
    )

    result = CliRunner().invoke(demo_module.run_demo, ["sales-analytics", "--all-mcp"])

    assert result.exit_code != 0
    assert "--all-mcp is only supported" in result.output


def test_run_server_passes_plain_general_chat_unified_mcp_env(tmp_path, monkeypatch):
    demo_dir = tmp_path / "general-chat"
    demo_dir.mkdir()
    captured: dict[str, object] = {}

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self._polls = 0

        def poll(self):
            self._polls += 1
            return None if self._polls == 1 else 0

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

    def fake_popen(cmd, cwd, env, stdout, stderr):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return FakeProcess()

    monkeypatch.setattr(demo_module, "_resolve_pnpm_command", lambda: None)
    monkeypatch.setattr(demo_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(demo_module.time, "sleep", lambda _seconds: None)

    demo_module._run_server(
        {
            "name": "general-chat",
            "type": "server",
            "dir": demo_dir,
            "port": 8005,
            "has_frontend": True,
        },
        port=None,
        no_frontend=True,
        no_install=True,
    )

    assert captured["cwd"] == str(demo_dir)
    assert captured["env"]["PYTHONUNBUFFERED"] == "1"
    assert captured["env"]["GENERAL_CHAT_MCP_ENABLED"] == "0"
    assert captured["env"]["GENERAL_CHAT_MCP_REGISTRY_ENABLED"] == "1"
    assert captured["cmd"][-3:] == ["--port", "8005", "--reload"]


def test_run_server_watches_only_src_when_present(tmp_path, monkeypatch):
    demo_dir = tmp_path / "general-chat"
    demo_dir.mkdir()
    (demo_dir / "src").mkdir()
    captured: dict[str, object] = {}

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self._polls = 0

        def poll(self):
            self._polls += 1
            return None if self._polls == 1 else 0

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

    def fake_popen(cmd, cwd, env, stdout, stderr):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return FakeProcess()

    monkeypatch.setattr(demo_module, "_resolve_pnpm_command", lambda: None)
    monkeypatch.setattr(demo_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(demo_module.time, "sleep", lambda _seconds: None)

    demo_module._run_server(
        {
            "name": "general-chat",
            "type": "server",
            "dir": demo_dir,
            "port": 8005,
            "has_frontend": True,
        },
        port=None,
        no_frontend=True,
        no_install=True,
    )

    # Reload must be scoped to src/ so runtime writes under .openbench/
    # (e.g. saving a custom function) don't restart the server.
    assert captured["cmd"][-5:] == ["--port", "8005", "--reload", "--reload-dir", "src"]


def test_run_server_passes_all_mcp_env_to_backend(tmp_path, monkeypatch):
    demo_dir = tmp_path / "general-chat"
    demo_dir.mkdir()
    captured: dict[str, object] = {}

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self._polls = 0

        def poll(self):
            self._polls += 1
            return None if self._polls == 1 else 0

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

    def fake_popen(cmd, cwd, env, stdout, stderr):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return FakeProcess()

    monkeypatch.setattr(demo_module, "_resolve_pnpm_command", lambda: None)
    monkeypatch.setattr(
        demo_module,
        "_general_chat_all_mcp_env",
        lambda demo_dir: {
            "GENERAL_CHAT_MCP_ENABLED": "0",
            "GENERAL_CHAT_MCP_REGISTRY_ENABLED": "1",
            "ALL_MCP": "1",
        },
    )
    monkeypatch.setattr(demo_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(demo_module.time, "sleep", lambda _seconds: None)

    demo_module._run_server(
        {
            "name": "general-chat",
            "type": "server",
            "dir": demo_dir,
            "port": 8005,
            "has_frontend": True,
        },
        port=None,
        no_frontend=True,
        no_install=True,
        all_mcp=True,
    )

    assert captured["cwd"] == str(demo_dir)
    assert captured["env"]["PYTHONUNBUFFERED"] == "1"
    assert captured["env"]["GENERAL_CHAT_MCP_ENABLED"] == "0"
    assert captured["env"]["GENERAL_CHAT_MCP_REGISTRY_ENABLED"] == "1"
    assert captured["env"]["ALL_MCP"] == "1"
    assert captured["cmd"][-3:] == ["--port", "8005", "--reload"]


def test_run_server_passes_variant_env_to_backend(tmp_path, monkeypatch):
    demo_dir = tmp_path / "general-chat"
    demo_dir.mkdir()
    captured: dict[str, object] = {}

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self._polls = 0

        def poll(self):
            self._polls += 1
            return None if self._polls == 1 else 0

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

    def fake_popen(cmd, cwd, env, stdout, stderr):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return FakeProcess()

    monkeypatch.setattr(demo_module, "_resolve_pnpm_command", lambda: None)
    monkeypatch.setattr(demo_module, "_general_chat_mcp_env", lambda variant, demo_dir: {"DEMO_MCP": variant})
    monkeypatch.setattr(demo_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(demo_module.time, "sleep", lambda _seconds: None)

    demo_module._run_server(
        {
            "name": "general-chat-image-search",
            "type": "server",
            "dir": demo_dir,
            "port": 8005,
            "has_frontend": True,
            "mcp_variant": "image-search",
        },
        port=None,
        no_frontend=True,
        no_install=True,
    )

    assert captured["cwd"] == str(demo_dir)
    assert captured["env"]["PYTHONUNBUFFERED"] == "1"
    assert captured["env"]["DEMO_MCP"] == "image-search"
    assert captured["cmd"][-3:] == ["--port", "8005", "--reload"]


def test_wait_for_backend_health_uses_health_endpoint(monkeypatch):
    requested_urls: list[str] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    def fake_urlopen(url, timeout):
        requested_urls.append(url)
        assert timeout == 1
        return FakeResponse()

    monkeypatch.setattr(demo_module.urllib.request, "urlopen", fake_urlopen)

    assert demo_module._wait_for_backend_health(8123, timeout=1) is True
    assert requested_urls == ["http://127.0.0.1:8123/health"]


def test_run_server_passes_backend_port_to_frontend_vite_env(tmp_path, monkeypatch):
    demo_dir = tmp_path / "general-chat"
    frontend_dir = demo_dir / "frontend"
    frontend_dir.mkdir(parents=True)
    popen_calls: list[dict[str, object]] = []

    class FakeProcess:
        def __init__(self, name: str):
            self.name = name
            self.returncode = None
            self._polls = 0

        def poll(self):
            self._polls += 1
            if self.name == "backend":
                return None
            return None if self._polls == 1 else 0

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def kill(self):
            self.returncode = -9

    def fake_popen(cmd, cwd, env, stdout, stderr):
        name = "frontend" if cmd[-1] == "dev" else "backend"
        popen_calls.append({"name": name, "cmd": cmd, "cwd": cwd, "env": env})
        return FakeProcess(name)

    monkeypatch.setattr(demo_module, "_resolve_pnpm_command", lambda: ["pnpm"])
    monkeypatch.setattr(demo_module, "_wait_for_backend_health", lambda port: True)
    monkeypatch.setattr(demo_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(demo_module.time, "sleep", lambda _seconds: None)

    demo_module._run_server(
        {
            "name": "general-chat",
            "type": "server",
            "dir": demo_dir,
            "port": 8005,
            "has_frontend": True,
        },
        port=8123,
        no_frontend=False,
        no_install=True,
    )

    frontend_call = next(call for call in popen_calls if call["name"] == "frontend")
    assert frontend_call["cwd"] == str(frontend_dir)
    assert frontend_call["env"]["VITE_BACKEND_URL"] == "http://localhost:8123"
