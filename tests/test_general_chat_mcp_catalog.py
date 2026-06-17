"""Tests for General Chat standard MCP server registry support."""

# ruff: noqa: E402,I001

from __future__ import annotations

import asyncio
import json
import queue
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from openbench.chat import ChatEngine
from openbench.chat.transport.agui_actions import ActionData
from openbench.core.abstractions import LLMProvider, LLMResponse
from openbench.intelligence import BaseAgent
from openbench.mcp.adapters import MCPToolAdapter
from openbench.mcp.config import MCPClientConfig, MCPPolicyConfig, MCPServerConnectionConfig
from openbench.mcp.permissions import (
    MCPPermissionContext,
    MCPPermissionSession,
    use_mcp_permission_context,
)
from openbench.mcp.toolhive import ToolHiveWorkload

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.agent import reload_external_mcp_tools
from general_chat.mcp_bootstrap import seed_all_mcp_registry
from general_chat.mcp_registry import MCPRegistryError, MCPServerRegistryStore
from general_chat.server.mcp_permissions import GeneralChatMCPPermissionCoordinator
from general_chat.server.handler import GeneralChatHandler


def _external_servers(payload: dict) -> list[dict]:
    return [
        server
        for server in payload["servers"]
        if server.get("providerKind") != "internal" and server.get("provider_kind") != "internal"
    ]


def _internal_server(payload: dict) -> dict:
    return next(
        server
        for server in payload["servers"]
        if server.get("providerKind") == "internal" or server.get("provider_kind") == "internal"
    )


class ImmediateLoop:
    def call_soon_threadsafe(self, fn, *args):
        fn(*args)


class RecordingMCPClient:
    def __init__(self):
        self.calls = []

    def call_tool_sync(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"ok": True}


def _permission_request_id(messages: list) -> tuple[str, str]:
    surface_id = ""
    request_id = ""
    for item in messages:
        message = getattr(item, "message", item)
        create = message.get("createSurface") if isinstance(message, dict) else None
        if create:
            surface_id = create["surfaceId"]
        update = message.get("updateComponents") if isinstance(message, dict) else None
        if not update:
            continue
        for component in update.get("components", []):
            if component.get("id") != "mcp-permission-allow":
                continue
            request_id = component["action"]["event"]["context"]["requestId"]
    return surface_id, request_id


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

PLAYWRIGHT_TIMEOUT_CONFIG = json.dumps(
    {
        "mcpServers": {
            "playwright": {
                "command": "docker",
                "args": ["run", "-i", "--rm", "mcp/playwright"],
                "cwd": "examples/general-chat",
                "timeout_seconds": 77,
            }
        }
    }
)


class TestMCPBootstrap(unittest.TestCase):
    def test_seed_all_mcp_registry_imports_bundled_configs(self):
        config_dir = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "mcp"
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = seed_all_mcp_registry(tmpdir, config_dir=config_dir)
            self.assertEqual([], summary["errors"])
            self.assertEqual([], summary["missing"])
            self.assertTrue(
                {
                    "filesystem",
                    "generic_api",
                    "image_search",
                    "sam_segmentation",
                    "docker",
                }.issubset(set(summary["seeded"]))
            )

            payload = MCPServerRegistryStore(tmpdir).list_payload()
            names = {server["name"] for server in payload["servers"]}
            self.assertTrue(
                {
                    "filesystem",
                    "generic_api",
                    "image_search",
                    "sam_segmentation",
                    "docker",
                    "openbench",
                }.issubset(names)
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
    calls: list[tuple[str, dict]] = []

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

    def call_tool_sync(self, namespaced_name, arguments=None, **kwargs):
        payload = dict(arguments or {})
        FakeMCPClient.calls.append((namespaced_name, payload))
        return {"called": namespaced_name, "arguments": payload}


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


class FakeStatusDiscoveredServer:
    tools = {
        "status": {
            "name": "status",
            "description": "Read status",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        }
    }


class FakeMultiServerMCPClient(FakeMCPClient):
    def _namespace(self):
        server_config = next(iter(self.config.servers.values()))
        return server_config.namespace or next(iter(self.config.servers))

    def discover_sync(self, refresh: bool = False):
        return SimpleNamespace(servers={self._namespace(): FakeStatusDiscoveredServer()})

    def discover_and_close_sync(self, refresh: bool = False):
        self.closed = True
        return SimpleNamespace(servers={self._namespace(): FakeStatusDiscoveredServer()})


class FakeAllMCPClient(FakeMultiServerMCPClient):
    TOOLS_BY_NAMESPACE = {
        "docker": {
            "docker_status": {
                "name": "docker_status",
                "description": "Read Docker MCP Gateway status",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            }
        },
        "filesystem": {
            "read_file": {
                "name": "read_file",
                "description": "Read a file",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            }
        },
        "git": {
            "git_status": {
                "name": "git_status",
                "description": "Read git status",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            }
        },
        "generic_api": {
            "fetch_generic_api_data": {
                "name": "fetch_generic_api_data",
                "description": "Fetch generic API data",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "endpoint_url": {"type": "string"},
                        "query_params": {"type": "object"},
                    },
                    "required": ["endpoint_url"],
                },
            }
        },
        "image_search": {
            "list_index_stats": {
                "name": "list_index_stats",
                "description": "List image index stats",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            "search_similar_images": {
                "name": "search_similar_images",
                "description": "Search similar images",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
        },
        "sam_segmentation": {
            "count_objects_with_sam3": {
                "name": "count_objects_with_sam3",
                "description": "Count objects with SAM 3",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            }
        },
    }

    def discover_sync(self, refresh: bool = False):
        namespace = self._namespace()
        return SimpleNamespace(
            servers={
                namespace: SimpleNamespace(
                    tools=self.TOOLS_BY_NAMESPACE.get(namespace, FakeStatusDiscoveredServer.tools)
                )
            }
        )

    def discover_and_close_sync(self, refresh: bool = False):
        self.closed = True
        return self.discover_sync(refresh=refresh)


class FakeEmptyDiscoveredServer:
    tools = {}


class FakeEmptyMCPClient(FakeMultiServerMCPClient):
    def discover_sync(self, refresh: bool = False):
        return SimpleNamespace(servers={self._namespace(): FakeEmptyDiscoveredServer()})

    def discover_and_close_sync(self, refresh: bool = False):
        self.closed = True
        return SimpleNamespace(servers={self._namespace(): FakeEmptyDiscoveredServer()})


class FakeCancelledMCPClient(FakeMCPClient):
    def discover_sync(self, refresh: bool = False):
        raise asyncio.CancelledError("Cancelled via cancel scope")

    def discover_and_close_sync(self, refresh: bool = False):
        self.closed = True
        raise asyncio.CancelledError("Cancelled via cancel scope")


class FakeConnectionClosedMCPClient(FakeMCPClient):
    def discover_sync(self, refresh: bool = False):
        raise RuntimeError("Failed to discover MCP server 'image_search': Connection closed")

    def discover_and_close_sync(self, refresh: bool = False):
        self.closed = True
        raise RuntimeError("Failed to discover MCP server 'image_search': Connection closed")


class FakeStreamableHTTPConnectMCPClient(FakeMCPClient):
    def discover_sync(self, refresh: bool = False):
        raise RuntimeError("Failed to discover MCP server 'git': All connection attempts failed")

    def discover_and_close_sync(self, refresh: bool = False):
        self.closed = True
        raise RuntimeError("Failed to discover MCP server 'git': All connection attempts failed")


class FakeDiscoveryOnlyMCPClient(FakeGitMCPClient):
    def discover_sync(self, refresh: bool = False):
        raise AssertionError("load should use persisted discovery state")


class FakeToolExecutor:
    def __init__(self):
        self._tools = {}
        self._schemas = {}

    def register(self, name, tool):
        self._tools[name] = tool
        self._schemas[name] = tool.get_schema()

    def get_schemas(self):
        return list(self._schemas.values())


class BrokenToolExecutor(FakeToolExecutor):
    def register(self, name, tool):
        return None


class ToolCallingLLM(LLMProvider):
    def __init__(self):
        self.prompts = []

    @property
    def provider_name(self):
        return "fake"

    def generate(self, prompt, model: str = "", **params) -> LLMResponse:
        self.prompts.append({"prompt": prompt, "tools": params.get("tools")})
        if len(self.prompts) == 1:
            response = LLMResponse(text="", model=model, tokens_used=0, cost=0.0)
            response.tool_calls = [
                {
                    "id": "call_0",
                    "name": "git_git_status",
                    "arguments": {"repo": "."},
                }
            ]
            return response
        return LLMResponse(text="Git status is available.", model=model, tokens_used=0, cost=0.0)


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


class TestGeneralChatMCPPermissionCoordinator(unittest.TestCase):
    def _run_adapter_with_coordinator(self, coordinator, client, messages, result):
        adapter = MCPToolAdapter(
            client=client,
            namespaced_name="git.git_status",
            tool_schema={"description": "Read git status"},
        )
        message_queue = queue.Queue()
        context = MCPPermissionContext(
            lambda request: coordinator.request_permission(
                session_id="session-1",
                request=request,
                queue=message_queue,
                loop=ImmediateLoop(),
            )
        )

        def target():
            try:
                with use_mcp_permission_context(context):
                    result["value"] = adapter.execute(repo=".")
            except Exception as exc:
                result["error"] = exc

        thread = threading.Thread(target=target)
        thread.start()
        messages.append(message_queue.get(timeout=1))
        messages.append(message_queue.get(timeout=1))
        return thread

    def test_approval_surface_blocks_mcp_tool_until_allowed(self):
        coordinator = GeneralChatMCPPermissionCoordinator(timeout_seconds=5)
        client = RecordingMCPClient()
        messages = []
        result = {}

        thread = self._run_adapter_with_coordinator(
            coordinator,
            client,
            messages,
            result,
        )
        self.assertEqual(client.calls, [])
        surface_id, request_id = _permission_request_id(messages)
        self.assertTrue(request_id)

        updates = coordinator.resolve_action(
            ActionData(
                name="mcp_permission_decision",
                surface_id=surface_id,
                context={"requestId": request_id, "decision": "allow"},
                thread_id="session-1",
            )
        )
        thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result["value"], {"ok": True})
        self.assertEqual(len(client.calls), 1)
        self.assertTrue(client.calls[0][1]["approved"])
        self.assertEqual(
            updates[0]["updateComponents"]["components"][1]["title"],
            "Approved. The tool is running now.",
        )

    def test_deny_prevents_mcp_tool_execution(self):
        coordinator = GeneralChatMCPPermissionCoordinator(timeout_seconds=5)
        client = RecordingMCPClient()
        messages = []
        result = {}

        thread = self._run_adapter_with_coordinator(
            coordinator,
            client,
            messages,
            result,
        )
        surface_id, request_id = _permission_request_id(messages)
        coordinator.resolve_action(
            ActionData(
                name="mcp_permission_decision",
                surface_id=surface_id,
                context={"requestId": request_id, "decision": "deny"},
                thread_id="session-1",
            )
        )
        thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(client.calls, [])
        self.assertIn("not approved", str(result["error"]))

    def test_permission_timeout_prevents_mcp_tool_execution(self):
        coordinator = GeneralChatMCPPermissionCoordinator(timeout_seconds=0.01)
        client = RecordingMCPClient()
        messages = []
        result = {}

        thread = self._run_adapter_with_coordinator(
            coordinator,
            client,
            messages,
            result,
        )
        thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(client.calls, [])
        self.assertIn("not approved", str(result["error"]))


class TestMCPServerRegistryStore(unittest.TestCase):
    def test_import_valid_standard_mcp_json_registers_server(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            payload = store.import_config_json(PLAYWRIGHT_CONFIG)

            self.assertEqual(len(payload["servers"]), 2)
            server = _external_servers(payload)[0]
            internal = _internal_server(payload)
            self.assertEqual(server["name"], "playwright")
            self.assertEqual(server["providerKind"], "docker")
            self.assertEqual(internal["name"], "openbench")
            self.assertEqual(internal["providerKind"], "internal")
            self.assertTrue(internal["isManaged"])
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
            remaining = store.list_payload()["servers"]
            self.assertEqual([item["name"] for item in remaining], ["openbench"])
            self.assertTrue(remaining[0]["isManaged"])

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

            names = {adapter.namespaced_name for adapter in adapters}
            self.assertIn("playwright.browser_snapshot", names)
            self.assertNotIn("playwright.browser_click", names)
            playwright_summary = next(item for item in summary["tools"] if item["server"] == "playwright")
            self.assertEqual(playwright_summary["name"], "playwright.browser_snapshot")
            loaded_server = FakeMCPClient.instances[-1].config.servers["playwright"]
            self.assertEqual(loaded_server.cwd, "examples/general-chat")

    def test_enabled_registry_adapters_preserve_server_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            FakeMCPClient.instances = []
            store = MCPServerRegistryStore(tmpdir)
            store.import_config_json(PLAYWRIGHT_TIMEOUT_CONFIG)

            with patch("general_chat.mcp_registry.MCPClient", FakeMCPClient):
                adapters, summary = store.load_enabled_tool_adapters()

            self.assertEqual(adapters[0].timeout_seconds, 77.0)
            self.assertEqual(summary["tools"][0]["timeout_seconds"], 77.0)

    def test_registry_client_policy_allows_long_server_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            FakeMCPClient.instances = []
            store = MCPServerRegistryStore(tmpdir)
            store.import_client_config(
                MCPClientConfig(
                    servers={
                        "sam_segmentation": MCPServerConnectionConfig(
                            command="docker",
                            args=["run", "-i", "--rm", "openbench/sam-segmentation-mcp:cpu"],
                            namespace="sam_segmentation",
                            timeout_seconds=3600,
                            allowed=True,
                        )
                    },
                    policy=MCPPolicyConfig(
                        allow_remote_servers=False,
                        allowed_servers=["sam_segmentation"],
                        max_timeout_seconds=3600,
                    ),
                )
            )

            with patch("general_chat.mcp_registry.MCPClient", FakeMultiServerMCPClient):
                adapters, summary = store.load_enabled_tool_adapters()

            client_config = FakeMCPClient.instances[-1].config
            self.assertEqual(client_config.policy.max_timeout_seconds, 3600.0)
            self.assertEqual(adapters[0].timeout_seconds, 3600.0)
            self.assertEqual(summary["tools"][0]["timeout_seconds"], 3600.0)

    def test_registry_policy_derives_long_timeout_for_legacy_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            FakeMCPClient.instances = []
            store = MCPServerRegistryStore(tmpdir)
            store.import_config_json(PLAYWRIGHT_TIMEOUT_CONFIG)

            state = json.loads(store.path.read_text(encoding="utf-8"))
            next(item for item in state["servers"] if item["name"] == "playwright").pop(
                "policy",
                None,
            )
            store.path.write_text(json.dumps(state), encoding="utf-8")

            with patch("general_chat.mcp_registry.MCPClient", FakeMCPClient):
                store.load_enabled_tool_adapters()

            self.assertEqual(FakeMCPClient.instances[-1].config.policy.max_timeout_seconds, 77.0)

    def test_disabled_server_is_not_started_or_offered_to_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            FakeMCPClient.instances = []
            store = MCPServerRegistryStore(tmpdir)
            server = store.import_config_json(PLAYWRIGHT_CONFIG)["servers"][0]
            store.set_server_enabled(server["id"], False)

            with patch("general_chat.mcp_registry.MCPClient", FakeMCPClient):
                adapters, summary = store.load_enabled_tool_adapters()

            self.assertNotIn("playwright.browser_snapshot", {adapter.namespaced_name for adapter in adapters})
            self.assertTrue(all(item["server"] != "playwright" for item in summary["tools"]))
            self.assertEqual(FakeMCPClient.instances, [])

    def test_load_uses_persisted_enabled_tool_state_after_discovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            FakeMCPClient.instances = []
            store = MCPServerRegistryStore(tmpdir)
            server = store.import_toolhive_workloads(
                [
                    ToolHiveWorkload(
                        name="git",
                        status="running",
                        url="http://127.0.0.1:39670/mcp",
                    )
                ]
            )["servers"][0]

            with patch("general_chat.mcp_registry.MCPClient", FakeDiscoveryOnlyMCPClient):
                discovered = store.discover_server(server["id"])
                self.assertEqual(sum(1 for tool in discovered.tools if tool.enabled), 1)
                adapters, summary = store.load_enabled_tool_adapters()

            self.assertIn("git.git_status", [adapter.namespaced_name for adapter in adapters])
            self.assertIsNone(summary["error"])
            self.assertEqual(len(FakeMCPClient.instances), 3)
            self.assertTrue(FakeMCPClient.instances[0].closed)
            self.assertTrue(FakeMCPClient.instances[1].closed)
            self.assertFalse(FakeMCPClient.instances[2].closed)

    def test_multiple_servers_with_overlapping_tool_names_remain_namespaced(self):
        config = json.dumps(
            {
                "mcpServers": {
                    "alpha": {"command": "docker", "args": ["run", "alpha"]},
                    "beta": {"command": "docker", "args": ["run", "beta"]},
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            FakeMCPClient.instances = []
            store = MCPServerRegistryStore(tmpdir)
            payload = store.import_config_json(config)

            with patch("general_chat.mcp_registry.MCPClient", FakeMultiServerMCPClient):
                for server in payload["servers"]:
                    store.discover_server(server["id"])
                adapters, summary = store.load_enabled_tool_adapters()

            external_names = sorted(
                adapter.namespaced_name
                for adapter in adapters
                if not adapter.namespaced_name.startswith("openbench.")
            )
            self.assertEqual(external_names, ["alpha.status", "beta.status"])
            self.assertEqual(
                sorted(item["adapter_name"] for item in summary["tools"] if item["server"] in {"alpha", "beta"}),
                ["alpha_status", "beta_status"],
            )

    def test_scoped_load_only_starts_selected_server(self):
        config = json.dumps(
            {
                "mcpServers": {
                    "alpha": {"command": "docker", "args": ["run", "alpha"]},
                    "beta": {"command": "docker", "args": ["run", "beta"]},
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            FakeMCPClient.instances = []
            store = MCPServerRegistryStore(tmpdir)
            payload = store.import_config_json(config)
            alpha = next(item for item in payload["servers"] if item["name"] == "alpha")

            with patch("general_chat.mcp_registry.MCPClient", FakeMultiServerMCPClient):
                adapters, summary = store.load_enabled_tool_adapters(server_ids={alpha["id"]})

            self.assertEqual(len(FakeMCPClient.instances), 2)
            self.assertTrue(FakeMCPClient.instances[0].closed)
            self.assertFalse(FakeMCPClient.instances[1].closed)
            self.assertEqual(list(FakeMCPClient.instances[0].config.servers), ["alpha"])
            self.assertEqual(list(FakeMCPClient.instances[1].config.servers), ["alpha"])
            namespaced = {adapter.namespaced_name for adapter in adapters}
            self.assertEqual(namespaced, {"alpha.status"})
            self.assertEqual([item["server"] for item in summary["tools"]], ["alpha"])

    def test_scoped_runtime_marking_preserves_unselected_registered_servers(self):
        config = json.dumps(
            {
                "mcpServers": {
                    "alpha": {"command": "docker", "args": ["run", "alpha"]},
                    "beta": {"command": "docker", "args": ["run", "beta"]},
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            payload = store.import_config_json(config)
            alpha = next(item for item in payload["servers"] if item["name"] == "alpha")

            with patch("general_chat.mcp_registry.MCPClient", FakeMultiServerMCPClient):
                adapters, summary = store.load_enabled_tool_adapters()

            store.mark_runtime_registration(
                {adapter.name for adapter in adapters},
                summary["diagnostics"],
            )
            store.mark_runtime_registration(set(), server_ids={alpha["id"]})

            servers = store.list_payload()["servers"]
            alpha_server = next(item for item in servers if item["name"] == "alpha")
            beta_server = next(item for item in servers if item["name"] == "beta")
            alpha_tool = alpha_server["tools"][0]
            beta_tool = beta_server["tools"][0]
            self.assertFalse(alpha_tool["loaded"])
            self.assertEqual(alpha_tool["status"], "enabled")
            self.assertTrue(beta_tool["loaded"])
            self.assertEqual(beta_tool["status"], "registered")

    def test_registry_loads_all_mcp_server_types_together(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            store.import_client_config(
                MCPClientConfig(
                    servers={
                        "docker": MCPServerConnectionConfig(
                            command="docker",
                            args=["mcp", "gateway", "run", "--profile", "openbench"],
                            namespace="docker",
                            timeout_seconds=3600,
                            allowed=True,
                        ),
                        "filesystem": MCPServerConnectionConfig(
                            command="npx",
                            args=["-y", "@modelcontextprotocol/server-filesystem", "."],
                            namespace="filesystem",
                            allowed=True,
                        ),
                        "generic_api": MCPServerConnectionConfig(
                            command="docker",
                            args=["run", "-i", "--rm", "openbench/generic-api-mcp:cpu"],
                            namespace="generic_api",
                            allowed=True,
                        ),
                        "image_search": MCPServerConnectionConfig(
                            command="docker",
                            args=["run", "-i", "--rm", "openbench/image-search-mcp:cpu"],
                            namespace="image_search",
                            timeout_seconds=3600,
                            allowed=True,
                        ),
                        "sam_segmentation": MCPServerConnectionConfig(
                            command="docker",
                            args=["run", "-i", "--rm", "openbench/sam-segmentation-mcp:cpu"],
                            namespace="sam_segmentation",
                            timeout_seconds=3600,
                            allowed=True,
                        ),
                    }
                )
            )
            store.import_toolhive_workloads(
                [
                    ToolHiveWorkload(
                        name="git",
                        status="running",
                        url="http://127.0.0.1:39670/mcp",
                    )
                ]
            )

            with patch("general_chat.mcp_registry.MCPClient", FakeAllMCPClient):
                adapters, summary = store.load_enabled_tool_adapters()

            namespaced = {adapter.namespaced_name for adapter in adapters}
            provider_names = {adapter.name for adapter in adapters}
            self.assertIn("docker.docker_status", namespaced)
            self.assertIn("filesystem.read_file", namespaced)
            self.assertIn("generic_api.fetch_generic_api_data", namespaced)
            self.assertIn("git.git_status", namespaced)
            self.assertIn("image_search.list_index_stats", namespaced)
            self.assertIn("image_search.search_similar_images", namespaced)
            self.assertIn("openbench.filter_records", namespaced)
            self.assertIn("sam_segmentation.count_objects_with_sam3", namespaced)
            self.assertIn("docker_docker_status", provider_names)
            self.assertIn("generic_api_fetch_generic_api_data", provider_names)
            self.assertIn("git_git_status", provider_names)
            self.assertIn("sam_segmentation_count_objects_with_sam3", provider_names)
            self.assertIsNone(summary["error"])

    def test_enabled_reachable_server_with_no_tools_reports_empty_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            server = store.import_config_json(PLAYWRIGHT_CONFIG)["servers"][0]

            with patch("general_chat.mcp_registry.MCPClient", FakeEmptyMCPClient):
                discovered = store.discover_server(server["id"])
                adapters, summary = store.load_enabled_tool_adapters()

            self.assertEqual(discovered.status, "empty")
            self.assertEqual(discovered.error, "MCP server is reachable but exposes no tools.")
            self.assertTrue(
                any(
                    item.get("server") == "playwright" and item.get("tools_discovered") == 0
                    for item in summary["diagnostics"]
                )
            )
            self.assertNotIn("playwright.status", [adapter.namespaced_name for adapter in adapters])

    def test_cancelled_mcp_discovery_reports_server_error_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            server = store.import_config_json(PLAYWRIGHT_CONFIG)["servers"][0]

            with patch("general_chat.mcp_registry.MCPClient", FakeCancelledMCPClient):
                discovered = store.discover_server(server["id"])
                adapters, summary = store.load_enabled_tool_adapters()

            self.assertEqual(discovered.status, "failed")
            self.assertTrue(discovered.enabled)
            self.assertEqual(discovered.error, "Cancelled via cancel scope")
            self.assertTrue(
                any(
                    item.get("server") == "playwright"
                    and item.get("category") == "server_unreachable"
                    and item.get("error") == "Cancelled via cancel scope"
                    for item in summary["errors"]
                )
            )
            self.assertNotIn("playwright.browser_snapshot", [adapter.namespaced_name for adapter in adapters])

    def test_streamable_http_discovery_failure_remains_enabled_with_clean_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            payload = store.import_toolhive_workloads(
                [
                    ToolHiveWorkload(
                        name="git",
                        status="running",
                        url="http://127.0.0.1:39670/mcp",
                    )
                ]
            )
            server = payload["servers"][0]

            with patch("general_chat.mcp_registry.MCPClient", FakeStreamableHTTPConnectMCPClient):
                discovered = store.discover_server(server["id"])
                adapters, summary = store.load_enabled_tool_adapters()

            self.assertEqual(discovered.status, "failed")
            self.assertTrue(discovered.enabled)
            self.assertEqual(discovered.config["transport"], "streamable-http")
            self.assertIn("All connection attempts failed", discovered.error or "")
            self.assertTrue(
                any(
                    item.get("server") == "git"
                    and item.get("category") == "server_unreachable"
                    and "All connection attempts failed" in item.get("error", "")
                    for item in summary["errors"]
                )
            )
            self.assertNotIn("git.git_status", [adapter.namespaced_name for adapter in adapters])

    def test_docker_connection_closed_includes_actionable_hint(self):
        config = json.dumps(
            {
                "mcpServers": {
                    "image_search": {
                        "command": "docker",
                        "args": ["run", "-i", "--rm", "openbench/image-search-mcp:cpu"],
                        "namespace": "image_search",
                    }
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            server = store.import_config_json(config)["servers"][0]

            with patch("general_chat.mcp_registry.MCPClient", FakeConnectionClosedMCPClient):
                discovered = store.discover_server(server["id"])
                _adapters, summary = store.load_enabled_tool_adapters()

            self.assertEqual(discovered.status, "failed")
            self.assertTrue(discovered.enabled)
            self.assertIn("Connection closed", discovered.error or "")
            self.assertIn("test_mcp_server.py --mode docker", discovered.diagnostics["hint"])
            image_error = next(item for item in summary["errors"] if item["server"] == "image_search")
            self.assertIn("openbench/image-search-mcp:cpu", image_error["hint"])

    def test_enabled_tools_with_invalid_schema_report_invalid_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            store.import_config_json(PLAYWRIGHT_CONFIG)

            with (
                patch("general_chat.mcp_registry.MCPClient", FakeMCPClient),
                patch(
                    "openbench.mcp.adapters.MCPToolAdapter.get_schema",
                    side_effect=ValueError("schema validation failed"),
                ),
            ):
                adapters, summary = store.load_enabled_tool_adapters()

            external_names = [
                adapter.namespaced_name
                for adapter in adapters
                if not adapter.namespaced_name.startswith("openbench.")
            ]
            self.assertEqual(external_names, [])
            self.assertTrue(
                any(item.get("category") == "invalid_tool_schema" for item in summary["errors"])
            )
            self.assertIn("schema validation failed", summary["error"])

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
                    return_value={
                        "enabled": True,
                        "available_to_chat": True,
                        "tools": [{"name": "playwright.browser_snapshot"}],
                        "registered_tools": ["playwright_browser_snapshot"],
                        "error": None,
                    },
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
            self.assertNotIn("reload", imported_toolhive.json())

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
            self.assertEqual([item["name"] for item in remaining], ["toolhive-doc-mcp", "openbench"])

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
            server = imported.json()["servers"][0]
            self.assertEqual(server["name"], "git")
            self.assertEqual(server["transport"], "streamable-http")
            self.assertNotIn("reload", imported.json())

            loaded = client.post(f"/mcp/catalogs/servers/{server['id']}/discover")

            self.assertEqual(loaded.status_code, 200)
            payload = loaded.json()
            self.assertEqual(payload["reload"]["tools"][0]["name"], "git.git_status")
            self.assertIn("git_git_status", payload["reload"]["registered_tools"])
            self.assertTrue(payload["reload"]["available_to_chat"])
            self.assertIsNone(payload["reload"].get("error"))
            self.assertIn("git_git_status", agent.tools._tools)

    def test_load_discovered_server_with_no_enabled_tools_reports_no_enabled_error(self):
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
            server = imported.json()["servers"][0]
            internal = _internal_server(imported.json())
            client.post(
                f"/mcp/catalogs/servers/{internal['id']}/enable",
                json={"enabled": False},
            )
            discovered = client.post(f"/mcp/catalogs/servers/{server['id']}/discover")
            self.assertEqual(discovered.status_code, 200)

            disabled = client.post(
                f"/mcp/catalogs/servers/{server['id']}/tools/git_status/enable",
                json={"enabled": False},
            )
            self.assertEqual(disabled.status_code, 200)
            self.assertEqual(disabled.json()["server"]["enabledToolsCount"], 0)

            loaded = client.post(f"/mcp/catalogs/servers/{server['id']}/discover")
            self.assertEqual(loaded.status_code, 400)
            self.assertIn("no enabled tools", loaded.json()["detail"])

    def test_loaded_toolhive_tool_is_available_to_current_chat_turn(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            FakeMCPClient.instances = []
            FakeMCPClient.calls = []
            store = MCPServerRegistryStore(tmpdir)
            store.import_toolhive_workloads(
                [
                    ToolHiveWorkload(
                        name="git",
                        status="running",
                        url="http://127.0.0.1:39670/mcp",
                    )
                ]
            )

            with (
                patch.dict(environ, {"GENERAL_CHAT_MCP_REGISTRY_ROOT": tmpdir}, clear=False),
                patch("general_chat.mcp_registry.MCPClient", FakeGitMCPClient),
            ):
                llm = ToolCallingLLM()
                agent = BaseAgent(goal="General chat", max_iterations=3)
                agent._llm = llm
                agent._mcp_permission_session = MCPPermissionSession(lambda request: "yes")

                summary = reload_external_mcp_tools(agent)

                self.assertTrue(summary["available_to_chat"])
                self.assertIn("git_git_status", summary["registered_tools"])
                self.assertIn("openbench_filter_records", summary["registered_tools"])
                self.assertIn("git_git_status", agent.tools._tools)

                engine = ChatEngine(agent=agent)
                handler = GeneralChatHandler(engine=engine, db_path=":memory:")
                request_agent = handler._create_request_agent()
                result = engine._execute_agent(
                    "Use the git status tool.",
                    None,
                    agent=request_agent,
                )

            self.assertEqual(result.output, "Git status is available.")
            self.assertEqual(result.metadata["tools_used"], ["git_git_status"])
            self.assertEqual(FakeMCPClient.calls, [("git.git_status", {"repo": "."})])
            first_tool_names = {
                item["function"]["name"]
                for item in llm.prompts[0]["tools"]
            }
            self.assertIn("git_git_status", first_tool_names)

    def test_runtime_registration_failure_reports_actionable_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            store.import_toolhive_workloads(
                [
                    ToolHiveWorkload(
                        name="git",
                        status="running",
                        url="http://127.0.0.1:39670/mcp",
                    )
                ]
            )

            agent = Mock()
            agent.tools = BrokenToolExecutor()
            agent._external_mcp_tool_names = set()

            with (
                patch.dict(environ, {"GENERAL_CHAT_MCP_REGISTRY_ROOT": tmpdir}, clear=False),
                patch("general_chat.mcp_registry.MCPClient", FakeGitMCPClient),
            ):
                summary = reload_external_mcp_tools(agent)

            self.assertFalse(summary["available_to_chat"])
            self.assertIn("registered but not visible to chat", summary["error"])
            self.assertEqual(summary["registered_tools"], [])
            self.assertEqual(agent._external_mcp_tool_names, set())

    def test_scoped_reload_preserves_previously_loaded_other_server_tools(self):
        config = json.dumps(
            {
                "mcpServers": {
                    "alpha": {"command": "docker", "args": ["run", "alpha"]},
                    "beta": {"command": "docker", "args": ["run", "beta"]},
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            payload = store.import_config_json(config)
            alpha = next(item for item in payload["servers"] if item["name"] == "alpha")

            agent = Mock()
            agent.tools = FakeToolExecutor()
            agent._external_mcp_tool_names = set()
            agent._external_mcp_tools = []
            agent._external_mcp_tool_servers = {}

            with (
                patch.dict(environ, {"GENERAL_CHAT_MCP_REGISTRY_ROOT": tmpdir}, clear=False),
                patch("general_chat.mcp_registry.MCPClient", FakeMultiServerMCPClient),
            ):
                full_summary = reload_external_mcp_tools(agent)
                self.assertIn("alpha_status", full_summary["registered_tools"])
                self.assertIn("beta_status", full_summary["registered_tools"])

                FakeMCPClient.instances = []
                scoped_summary = reload_external_mcp_tools(agent, server_ids={alpha["id"]})

            self.assertEqual(len(FakeMCPClient.instances), 2)
            self.assertTrue(FakeMCPClient.instances[0].closed)
            self.assertFalse(FakeMCPClient.instances[1].closed)
            self.assertEqual(list(FakeMCPClient.instances[0].config.servers), ["alpha"])
            self.assertEqual(list(FakeMCPClient.instances[1].config.servers), ["alpha"])
            self.assertEqual(scoped_summary["registered_tools"], ["alpha_status"])
            self.assertIn("alpha_status", agent.tools._tools)
            self.assertIn("beta_status", agent.tools._tools)
            self.assertIn("alpha_status", agent._external_mcp_tool_names)
            self.assertIn("beta_status", agent._external_mcp_tool_names)

    def test_scoped_reload_after_disable_unregisters_only_selected_server_tools(self):
        config = json.dumps(
            {
                "mcpServers": {
                    "alpha": {"command": "docker", "args": ["run", "alpha"]},
                    "beta": {"command": "docker", "args": ["run", "beta"]},
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MCPServerRegistryStore(tmpdir)
            payload = store.import_config_json(config)
            alpha = next(item for item in payload["servers"] if item["name"] == "alpha")

            agent = Mock()
            agent.tools = FakeToolExecutor()
            agent._external_mcp_tool_names = set()
            agent._external_mcp_tools = []
            agent._external_mcp_tool_servers = {}

            with (
                patch.dict(environ, {"GENERAL_CHAT_MCP_REGISTRY_ROOT": tmpdir}, clear=False),
                patch("general_chat.mcp_registry.MCPClient", FakeMultiServerMCPClient),
            ):
                reload_external_mcp_tools(agent)
                store.set_server_enabled(alpha["id"], False)
                scoped_summary = reload_external_mcp_tools(agent, server_ids={alpha["id"]})

            self.assertEqual(scoped_summary["registered_tools"], [])
            self.assertNotIn("alpha_status", agent.tools._tools)
            self.assertIn("beta_status", agent.tools._tools)
            self.assertNotIn("alpha_status", agent._external_mcp_tool_names)
            self.assertIn("beta_status", agent._external_mcp_tool_names)


if __name__ == "__main__":
    unittest.main()
