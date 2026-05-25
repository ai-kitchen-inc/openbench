"""Tests for General Chat standard MCP server registry support."""

# ruff: noqa: E402,I001

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from openbench.mcp.toolhive import ToolHiveWorkload

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.mcp_registry import MCPRegistryError, MCPServerRegistryStore


PLAYWRIGHT_CONFIG = json.dumps(
    {
        "mcpServers": {
            "playwright": {
                "command": "docker",
                "args": ["run", "-i", "--rm", "mcp/playwright"],
                "cwd": "examples/general-chat",
                "env": {"PLAYWRIGHT_TOKEN": "secret-token"},
            }
        }
    }
)


class FakeDiscoveredServer:
    tools = {
        "browser_click": {
            "name": "browser_click",
            "description": "Click an element",
            "inputSchema": {
                "type": "object",
                "properties": {"selector": {"type": "string"}},
                "required": ["selector"],
            },
        },
        "browser_snapshot": {
            "name": "browser_snapshot",
            "description": "Capture page structure",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    }


class FakeDiscovery:
    servers = {"playwright": FakeDiscoveredServer()}


class FakeMCPClient:
    instances: list[FakeMCPClient] = []

    def __init__(self, config):
        self.config = config
        self.closed = False
        FakeMCPClient.instances.append(self)

    def discover_sync(self, refresh: bool = False):
        return FakeDiscovery()

    def discover_and_close_sync(self, refresh: bool = False):
        self.closed = True
        return FakeDiscovery()

    def close_sync(self):
        self.closed = True


class FakeGitDiscoveredServer:
    tools = {
        "git_status": {
            "name": "git_status",
            "description": "Read git status",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        }
    }


class FakeGitDiscovery:
    servers = {"git": FakeGitDiscoveredServer()}


class FakeGitMCPClient(FakeMCPClient):
    def discover_sync(self, refresh: bool = False):
        return FakeGitDiscovery()

    def discover_and_close_sync(self, refresh: bool = False):
        self.closed = True
        return FakeGitDiscovery()


class FakeToolExecutor:
    def __init__(self):
        self._tools = {}
        self._schemas = {}

    def register(self, name, tool):
        self._tools[name] = tool
        self._schemas[name] = tool.get_schema()


class FakeToolHiveService:
    def status(self):
        class Status:
            def to_dict(self):
                return {
                    "available": True,
                    "apiAvailable": True,
                    "cliAvailable": False,
                    "version": "v0.test",
                    "apiBaseUrl": "http://127.0.0.1:8080",
                    "source": "api",
                    "error": None,
                    "setupHint": None,
                    "uiCliDetected": False,
                    "cliPath": "thv",
                    "managementMode": "api",
                }

        return Status()

    def list_workloads(self):
        return [
            ToolHiveWorkload(
                name="toolhive-doc-mcp",
                status="running",
                url="http://127.0.0.1:19767/mcp",
                package="ghcr.io/stackloklabs/toolhive-doc-mcp:test",
            )
        ]

    def list_registry_servers(self):
        return []


class FakeGitToolHiveService(FakeToolHiveService):
    def list_workloads(self):
        return [
            ToolHiveWorkload(
                name="git",
                status="running",
                url="http://127.0.0.1:39670/mcp",
                package="io.github.stacklok/git",
            )
        ]


class TestMCPServerRegistryStore(unittest.TestCase):
    def test_import_valid_standard_mcp_json_registers_server(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            payload = store.import_config_json(PLAYWRIGHT_CONFIG)

            self.assertEqual(len(payload["servers"]), 1)
            server = payload["servers"][0]
            self.assertEqual(server["name"], "playwright")
            self.assertEqual(server["transport"], "stdio")
            self.assertTrue(server["enabled"])
            self.assertEqual(server["displayConfig"]["command"], "docker")
            self.assertEqual(server["displayConfig"]["env"]["PLAYWRIGHT_TOKEN"], "***REDACTED***")
            self.assertNotIn("catalog", json.dumps(payload).lower())
            self.assertNotIn("oci", json.dumps(payload).lower())

    def test_invalid_json_missing_mcp_servers_and_invalid_server_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            with self.assertRaisesRegex(MCPRegistryError, "valid JSON"):
                store.import_config_json("{bad")
            with self.assertRaisesRegex(MCPRegistryError, "mcpServers"):
                store.import_config_json(json.dumps({"servers": {}}))
            with self.assertRaisesRegex(MCPRegistryError, "args must be an array of strings"):
                store.import_config_json(
                    json.dumps({"mcpServers": {"bad": {"command": "docker", "args": "run"}}})
                )

    def test_duplicate_normalized_server_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            with self.assertRaisesRegex(MCPRegistryError, "normalize to the same name"):
                store.import_config_json(
                    json.dumps(
                        {
                            "mcpServers": {
                                "Play Wright": {"command": "docker"},
                                "play-wright": {"command": "docker"},
                            }
                        }
                    )
                )

    def test_server_registration_toggle_and_removal_persist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            server = store.import_config_json(PLAYWRIGHT_CONFIG)["servers"][0]

            disabled = store.set_server_enabled(server["id"], False)
            self.assertFalse(disabled.enabled)
            self.assertEqual(MCPServerRegistryStore(tmpdir).get_server(server["id"]).status, "disabled")

            enabled = store.set_server_enabled(server["id"], True)
            self.assertTrue(enabled.enabled)
            store.remove_server(server["id"])
            self.assertEqual(store.list_payload()["servers"], [])

    def test_discovery_stores_tools_and_tool_toggle_filters_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            FakeMCPClient.instances = []
            store = MCPServerRegistryStore(tmpdir)
            server = store.import_config_json(PLAYWRIGHT_CONFIG)["servers"][0]

            with patch("general_chat.mcp_registry.MCPClient", FakeMCPClient):
                discovered = store.discover_server(server["id"])
                self.assertEqual(discovered.status, "running")
                self.assertEqual(len(discovered.tools), 2)
                self.assertTrue(FakeMCPClient.instances[-1].closed)

                updated = store.set_tool_enabled(server["id"], "browser_click", False)
                self.assertFalse(next(tool for tool in updated.tools if tool.name == "browser_click").enabled)

                adapters, summary = store.load_enabled_tool_adapters()

            self.assertEqual([adapter.namespaced_name for adapter in adapters], ["playwright.browser_snapshot"])
            self.assertEqual(summary["tools"][0]["name"], "playwright.browser_snapshot")
            loaded_server = FakeMCPClient.instances[-1].config.servers["playwright"]
            self.assertEqual(loaded_server.cwd, "examples/general-chat")

    def test_disabled_server_is_not_started_or_offered_to_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            FakeMCPClient.instances = []
            store = MCPServerRegistryStore(tmpdir)
            server = store.import_config_json(PLAYWRIGHT_CONFIG)["servers"][0]
            store.set_server_enabled(server["id"], False)

            with patch("general_chat.mcp_registry.MCPClient", FakeMCPClient):
                adapters, summary = store.load_enabled_tool_adapters()

            self.assertEqual(adapters, [])
            self.assertEqual(summary["tools"], [])
            self.assertEqual(FakeMCPClient.instances, [])

    def test_import_toolhive_workload_persists_metadata_and_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            payload = store.import_toolhive_workloads(
                [
                    ToolHiveWorkload(
                        name="toolhive-doc-mcp",
                        status="running",
                        url="http://127.0.0.1:19767/mcp",
                    )
                ]
            )

            server = payload["servers"][0]
            self.assertEqual(server["source"], "toolhive")
            self.assertEqual(server["workloadName"], "toolhive-doc-mcp")
            self.assertEqual(server["proxyUrl"], "http://127.0.0.1:19767/mcp")
            self.assertEqual(server["transport"], "streamable-http")


class TestMCPServerRegistryEndpoints(unittest.TestCase):
    def test_import_toggle_discover_and_remove_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stack = ExitStack()
            self.addCleanup(stack.close)
            stack.enter_context(
                patch.dict(
                    environ,
                    {
                        "GENERAL_CHAT_STORAGE_ROOT": tmpdir,
                        "GENERAL_CHAT_UPLOAD_DIR": str(Path(tmpdir) / "uploads"),
                        "GENERAL_CHAT_DOWNLOAD_DIR": str(Path(tmpdir) / "downloads"),
                        "OPENBENCH_PROFILE_DIR": str(Path(tmpdir) / "profiles"),
                    },
                    clear=False,
                )
            )
            agent = Mock()
            agent.model = "mock-model"
            agent._persona = None
            agent._skill_registry = None
            agent._mcp_summary = {"enabled": False, "tools": []}
            agent._external_mcp_summary = {"enabled": False, "tools": []}
            agent._external_mcp_tool_names = set()
            agent.tools = FakeToolExecutor()
            stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
            stack.enter_context(
                patch("general_chat.server.app.ToolHiveService", return_value=FakeToolHiveService())
            )
            stack.enter_context(patch("general_chat.mcp_registry.MCPClient", FakeMCPClient))
            stack.enter_context(
                patch(
                    "general_chat.server.app.reload_external_mcp_tools",
                    return_value={"enabled": True, "tools": [{"name": "playwright.browser_snapshot"}]},
                )
            )

            from general_chat.server.app import create_app

            client = TestClient(create_app())
            invalid = client.post("/mcp/catalogs/import", json={"url": "https://example.com/catalog.json"})
            self.assertEqual(invalid.status_code, 400)
            self.assertIn("mcpServers", invalid.json()["detail"])

            imported = client.post("/mcp/catalogs/import", json={"config": PLAYWRIGHT_CONFIG})
            self.assertEqual(imported.status_code, 200)
            server = imported.json()["servers"][0]
            self.assertEqual(server["name"], "playwright")

            status = client.get("/toolhive/status")
            self.assertEqual(status.status_code, 200)
            self.assertTrue(status.json()["available"])
            self.assertEqual(status.json()["managementMode"], "api")
            self.assertEqual(status.json()["cliPath"], "thv")

            workloads = client.get("/toolhive/workloads")
            self.assertEqual(workloads.status_code, 200)
            self.assertEqual(workloads.json()["workloads"][0]["name"], "toolhive-doc-mcp")

            imported_toolhive = client.post(
                "/mcp/catalogs/toolhive/import-running",
                json={"names": ["toolhive-doc-mcp"]},
            )
            self.assertEqual(imported_toolhive.status_code, 200)
            toolhive_server = next(
                item
                for item in imported_toolhive.json()["servers"]
                if item["name"] == "toolhive-doc-mcp"
            )
            self.assertEqual(toolhive_server["source"], "toolhive")

            disabled = client.post(
                f"/mcp/catalogs/servers/{server['id']}/enable",
                json={"enabled": False},
            )
            self.assertEqual(disabled.status_code, 200)
            self.assertFalse(disabled.json()["server"]["enabled"])

            enabled = client.post(
                f"/mcp/catalogs/servers/{server['id']}/enable",
                json={"enabled": True},
            )
            self.assertEqual(enabled.status_code, 200)

            discovered = client.post(f"/mcp/catalogs/servers/{server['id']}/discover")
            self.assertEqual(discovered.status_code, 200)
            self.assertEqual(discovered.json()["server"]["toolsCount"], 2)

            tool_toggle = client.post(
                f"/mcp/catalogs/servers/{server['id']}/tools/browser_click/enable",
                json={"enabled": False},
            )
            self.assertEqual(tool_toggle.status_code, 200)
            tool = next(item for item in tool_toggle.json()["server"]["tools"] if item["name"] == "browser_click")
            self.assertFalse(tool["enabled"])

            removed = client.delete(f"/mcp/catalogs/servers/{server['id']}")
            self.assertEqual(removed.status_code, 200)
            remaining = client.get("/mcp/catalogs").json()["servers"]
            self.assertEqual([item["name"] for item in remaining], ["toolhive-doc-mcp"])

    def test_import_toolhive_git_workload_reload_discovers_streamable_http_tools(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stack = ExitStack()
            self.addCleanup(stack.close)
            stack.enter_context(
                patch.dict(
                    environ,
                    {
                        "GENERAL_CHAT_STORAGE_ROOT": tmpdir,
                        "GENERAL_CHAT_UPLOAD_DIR": str(Path(tmpdir) / "uploads"),
                        "GENERAL_CHAT_DOWNLOAD_DIR": str(Path(tmpdir) / "downloads"),
                        "OPENBENCH_PROFILE_DIR": str(Path(tmpdir) / "profiles"),
                    },
                    clear=False,
                )
            )
            agent = Mock()
            agent.model = "mock-model"
            agent._persona = None
            agent._skill_registry = None
            agent._mcp_summary = {"enabled": False, "tools": []}
            agent._external_mcp_summary = {"enabled": False, "tools": []}
            agent._external_mcp_tool_names = set()
            agent.tools = FakeToolExecutor()
            stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
            stack.enter_context(
                patch("general_chat.server.app.ToolHiveService", return_value=FakeGitToolHiveService())
            )
            stack.enter_context(patch("general_chat.mcp_registry.MCPClient", FakeGitMCPClient))

            from general_chat.server.app import create_app

            client = TestClient(create_app())
            imported = client.post("/mcp/catalogs/toolhive/import-running", json={"names": ["git"]})

            self.assertEqual(imported.status_code, 200)
            payload = imported.json()
            server = payload["servers"][0]
            self.assertEqual(server["name"], "git")
            self.assertEqual(server["transport"], "streamable-http")
            self.assertEqual(payload["reload"]["tools"][0]["name"], "git.git_status")
            self.assertIsNone(payload["reload"].get("error"))


if __name__ == "__main__":
    unittest.main()
