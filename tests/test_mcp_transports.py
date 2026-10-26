"""Unit tests for MCP transport helpers.

The client/transport integration paths (session reuse, reconnects,
streamable HTTP against a faked SDK) live in
``tests/test_mcp_server_client.py``; this file covers the small units:
dispatch, model conversion, shutdown-noise detection, and the
concurrency helper.
"""

from __future__ import annotations

import asyncio
import builtins
import unittest
from types import SimpleNamespace

from openbench.mcp.config import MCPServerConnectionConfig
from openbench.mcp.errors import MCPTransportError
from openbench.mcp.transports import (
    InMemoryMCPTransport,
    MCPTransport,
    StdioMCPTransport,
    StreamableHTTPTransport,
    _is_mcp_sdk_shutdown_noise,
    _model_to_dict,
    build_transport,
    gather_with_concurrency,
)


class _MinimalTransport(MCPTransport):
    async def initialize(self):
        return {}

    async def list_tools(self):
        return []

    async def call_tool(self, name, arguments):
        return {}


class TestBuildTransport(unittest.TestCase):
    def test_stdio_config_builds_stdio_transport(self):
        config = MCPServerConnectionConfig(transport="stdio", command="python")
        self.assertIsInstance(build_transport(config), StdioMCPTransport)

    def test_streamable_http_config_builds_http_transport(self):
        config = MCPServerConnectionConfig(
            transport="streamable-http", url="http://localhost:1234/mcp"
        )
        self.assertIsInstance(build_transport(config), StreamableHTTPTransport)

    def test_sse_is_rejected_with_guidance(self):
        config = MCPServerConnectionConfig(transport="sse", url="http://localhost:1234/sse")
        with self.assertRaises(MCPTransportError) as ctx:
            build_transport(config)
        self.assertIn("Streamable HTTP", str(ctx.exception))

    def test_unknown_transport_is_rejected(self):
        with self.assertRaises(MCPTransportError):
            build_transport(SimpleNamespace(transport="carrier-pigeon"))


class TestModelToDict(unittest.TestCase):
    def test_pydantic_model_dump_wins(self):
        model = SimpleNamespace(
            model_dump=lambda by_alias, exclude_none: {"inputSchema": {"type": "object"}}
        )
        self.assertEqual(_model_to_dict(model), {"inputSchema": {"type": "object"}})

    def test_legacy_dict_method(self):
        class Legacy:
            def dict(self):
                return {"name": "legacy"}

        self.assertEqual(_model_to_dict(Legacy()), {"name": "legacy"})

    def test_plain_dict_passes_through(self):
        payload = {"name": "x"}
        self.assertIs(_model_to_dict(payload), payload)

    def test_scalar_is_wrapped(self):
        self.assertEqual(_model_to_dict(42), {"result": 42})


class TestShutdownNoiseDetection(unittest.TestCase):
    def test_keyboard_interrupt_and_system_exit_are_never_noise(self):
        self.assertFalse(_is_mcp_sdk_shutdown_noise(KeyboardInterrupt()))
        self.assertFalse(_is_mcp_sdk_shutdown_noise(SystemExit()))

    def test_generator_exit_is_noise(self):
        self.assertTrue(_is_mcp_sdk_shutdown_noise(GeneratorExit()))

    def test_plain_runtime_error_is_not_noise(self):
        self.assertFalse(_is_mcp_sdk_shutdown_noise(RuntimeError("real failure")))

    def test_cancelled_without_cancel_scope_is_not_noise(self):
        self.assertFalse(_is_mcp_sdk_shutdown_noise(asyncio.CancelledError("unrelated")))

    def test_running_athrow_message_is_noise(self):
        exc = RuntimeError("athrow(): asynchronous generator is already running")
        self.assertTrue(_is_mcp_sdk_shutdown_noise(exc))

    def test_exception_group_with_noise_member_is_noise(self):
        group_cls = getattr(builtins, "BaseExceptionGroup", None)
        if group_cls is None:  # pragma: no cover - Python < 3.11
            self.skipTest("BaseExceptionGroup unavailable")
        noisy = group_cls("wrap", [GeneratorExit(), RuntimeError("x")])
        quiet = group_cls("wrap", [RuntimeError("x")])
        self.assertTrue(_is_mcp_sdk_shutdown_noise(noisy))
        self.assertFalse(_is_mcp_sdk_shutdown_noise(quiet))


class TestInMemoryTransport(unittest.TestCase):
    def setUp(self):
        self.server = SimpleNamespace(
            list_tools=lambda: [{"name": "echo"}],
            list_resources=lambda: [{"uri": "openbench://x"}],
            list_prompts=lambda: [{"name": "p"}],
            call_tool=lambda name, arguments, approved: {
                "name": name,
                "arguments": arguments,
                "approved": approved,
            },
        )
        self.transport = InMemoryMCPTransport(self.server)

    def test_initialize_reports_capabilities(self):
        result = asyncio.run(self.transport.initialize())
        self.assertEqual(set(result["capabilities"]), {"tools", "resources", "prompts"})

    def test_delegates_to_server(self):
        self.assertEqual(asyncio.run(self.transport.list_tools()), [{"name": "echo"}])
        self.assertEqual(asyncio.run(self.transport.list_resources()), [{"uri": "openbench://x"}])
        self.assertEqual(asyncio.run(self.transport.list_prompts()), [{"name": "p"}])

    def test_call_tool_is_preapproved(self):
        result = asyncio.run(self.transport.call_tool("echo", {"value": "hi"}))
        self.assertEqual(result, {"name": "echo", "arguments": {"value": "hi"}, "approved": True})


class TestTransportBaseDefaults(unittest.TestCase):
    def test_optional_capabilities_default_to_empty(self):
        transport = _MinimalTransport()
        self.assertEqual(asyncio.run(transport.list_resources()), [])
        self.assertEqual(asyncio.run(transport.list_prompts()), [])
        self.assertIsNone(asyncio.run(transport.close()))


class TestGatherWithConcurrency(unittest.TestCase):
    def test_preserves_order(self):
        async def value(n):
            await asyncio.sleep(0)
            return n

        results = asyncio.run(gather_with_concurrency(2, value(1), value(2), value(3)))
        self.assertEqual(results, [1, 2, 3])

    def test_respects_limit(self):
        state = {"active": 0, "peak": 0}

        async def tracked():
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            await asyncio.sleep(0.01)
            state["active"] -= 1

        asyncio.run(gather_with_concurrency(2, *(tracked() for _ in range(6))))
        self.assertLessEqual(state["peak"], 2)
        self.assertGreaterEqual(state["peak"], 1)


if __name__ == "__main__":
    unittest.main()
