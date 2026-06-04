from __future__ import annotations

from pathlib import Path

from openbench.cli.commands import demo as demo_module


def test_discover_demos_includes_general_chat_mcp_variants():
    demos = {item["name"]: item for item in demo_module._discover_demos()}

    image_search = demos["general-chat-image-search"]
    sam = demos["general-chat-sam-segmentation"]
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

    assert "mcp_variant" not in plain


def test_discover_demos_ignores_virtualenv_scripts(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    examples = root / "examples"
    venv_scripts = examples / "image-search-mcp" / ".venv" / "Lib" / "site-packages"
    venv_scripts.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'demo-test'\n", encoding="utf-8")
    (venv_scripts / "accidental_demo.py").write_text(
        '"""Should not be discovered."""\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(demo_module, "_find_project_root", lambda: root)

    demos = demo_module._discover_demos()

    assert "image-search-mcp/.venv/Lib/site-packages/accidental" not in {
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
    assert env["IMAGE_SEARCH_MCP_DATA_PATH"].endswith("/examples/image-search-mcp/data")
    assert env["IMAGE_SEARCH_MCP_MODELS_PATH"].endswith("/examples/image-search-mcp/models")
    assert env["IMAGE_SEARCH_MCP_UPLOADS_PATH"].endswith("/examples/general-chat/uploads")
    assert env["IMAGE_SEARCH_MCP_HF_CACHE_PATH"].endswith("/home/.cache/huggingface")
    assert Path(env["GENERAL_CHAT_IMAGE_SEARCH_PREVIEW_DIR"]).is_dir()
    assert (demo_dir / "uploads").is_dir()
    assert (root / "examples" / "image-search-mcp" / "data" / "previews").is_dir()
    assert (root / "examples" / "image-search-mcp" / "models").is_dir()
    assert (home_dir / ".cache" / "huggingface").is_dir()


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
