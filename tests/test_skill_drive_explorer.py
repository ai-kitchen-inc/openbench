"""Tests for the drive-explorer SDK skill + MCPClient binding.

The drive-explorer skill is MCP-backed: its tool wrappers translate
agent tool calls into ``MCPClient.call_tool(name, arguments)``. These
tests verify:

1. The skill loads cleanly and exposes its 4 tools.
2. Each wrapper translates to the correct underlying MCP tool name
   with the right argument shape.
3. Calling a tool before ``bind(mcp_client=...)`` raises a clear
   error pointing the caller at the setup reference.
4. ``MockMCPClient`` works as the test double the skill's reference
   documentation promises.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from openbench.integrations.mcp import MCPClient, MockMCPClient
from openbench.intelligence.skill import Skill

SDK_SKILLS_DIR = Path(__file__).resolve().parent.parent / "src" / "openbench" / "skills"
SKILL_PATH = SDK_SKILLS_DIR / "drive-explorer"


class TestDriveExplorerSkill(unittest.TestCase):
    """Skill structure: it loads, has the right tools, has references."""

    def setUp(self):
        self.skill = Skill.from_dir(SKILL_PATH)
        self.tools = {name: (fn, schema) for name, fn, schema in self.skill.tools}
        # Reset binding between tests so a leak in one doesn't mask the
        # next test's "not bound" assertion.
        self.addCleanup(self.skill.bind, mcp_client=None)

    def test_skill_loads(self):
        self.assertEqual(self.skill.name, "drive-explorer")
        self.assertTrue(self.skill.has_tools)
        self.assertGreater(len(self.skill.description), 50)

    def test_exposes_four_tools(self):
        expected = {
            "drive_search",
            "drive_read_file",
            "drive_list_recent",
            "drive_get_metadata",
        }
        self.assertEqual(set(self.tools), expected)

    def test_each_tool_has_schema_with_required_fields(self):
        for name, (_, schema) in self.tools.items():
            self.assertEqual(schema["name"], name)
            self.assertIn("description", schema)
            self.assertIn("parameters", schema)
            self.assertEqual(schema["parameters"]["type"], "object")

    def test_skill_references_include_mcp_setup_doc(self):
        self.assertIn("mcp-server-setup.md", self.skill.references)


class TestDriveExplorerBinding(unittest.TestCase):
    """The skill must fail loudly if used without an MCPClient bound."""

    def setUp(self):
        self.skill = Skill.from_dir(SKILL_PATH)
        self.tools = {name: fn for name, fn, _ in self.skill.tools}
        # Defensive: clear any client bound by a prior test.
        self.skill.bind(mcp_client=None)
        self.addCleanup(self.skill.bind, mcp_client=None)

    def test_calling_tool_without_bound_client_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.tools["drive_search"](query="anything")
        self.assertIn("not bound", str(ctx.exception))
        self.assertIn("mcp_client", str(ctx.exception))

    def test_bind_accepts_extra_kwargs_silently(self):
        """``bind`` must ignore unrelated kwargs (e.g. scratchpad)."""
        client = MockMCPClient({"search": lambda args: []})
        # Should not raise even though scratchpad is unrelated.
        self.skill.bind(mcp_client=client, scratchpad="ignored")


class TestDriveExplorerToolDispatch(unittest.TestCase):
    """Each wrapper must hit the right MCP tool with the right args."""

    def setUp(self):
        self.calls: list[tuple[str, dict]] = []

        def make_handler(return_value):
            def handler(args):
                return return_value

            return handler

        self.client = MockMCPClient(
            {
                "search": make_handler([{"id": "1", "name": "Q1.pdf"}]),
                "read_file": make_handler({"id": "1", "content": "hi"}),
                "list_recent": make_handler([{"id": "2", "name": "memo.docx"}]),
                "get_metadata": make_handler({"id": "1", "modifiedTime": "2026-05-01"}),
            }
        )
        # Wrap call_tool to record calls for assertion.
        original_call = self.client.call_tool

        def recording_call(name, args):
            self.calls.append((name, dict(args)))
            return original_call(name, args)

        self.client.call_tool = recording_call  # type: ignore[method-assign]

        self.skill = Skill.from_dir(SKILL_PATH)
        self.tools = {name: fn for name, fn, _ in self.skill.tools}
        self.skill.bind(mcp_client=self.client)
        self.addCleanup(self.skill.bind, mcp_client=None)

    def test_drive_search_translates_to_search_tool(self):
        out = self.tools["drive_search"](query="Q1 report", max_results=5)
        self.assertEqual(self.calls, [("search", {"query": "Q1 report", "max_results": 5})])
        self.assertEqual(out, [{"id": "1", "name": "Q1.pdf"}])

    def test_drive_search_default_max_results_is_10(self):
        self.tools["drive_search"](query="x")
        self.assertEqual(self.calls[-1], ("search", {"query": "x", "max_results": 10}))

    def test_drive_read_file_translates_to_read_file_tool(self):
        out = self.tools["drive_read_file"](file_id="abc123")
        self.assertEqual(self.calls, [("read_file", {"file_id": "abc123"})])
        self.assertEqual(out, {"id": "1", "content": "hi"})

    def test_drive_list_recent_translates_to_list_recent_tool(self):
        self.tools["drive_list_recent"](max_results=3)
        self.assertEqual(self.calls, [("list_recent", {"max_results": 3})])

    def test_drive_get_metadata_translates_to_get_metadata_tool(self):
        self.tools["drive_get_metadata"](file_id="xyz")
        self.assertEqual(self.calls, [("get_metadata", {"file_id": "xyz"})])


class TestMockMCPClient(unittest.TestCase):
    """MockMCPClient is part of the skill's documented test contract."""

    def test_satisfies_mcp_client_protocol(self):
        client = MockMCPClient({"x": lambda a: 1})
        self.assertIsInstance(client, MCPClient)

    def test_call_tool_invokes_handler(self):
        client = MockMCPClient({"echo": lambda args: args["v"]})
        self.assertEqual(client.call_tool("echo", {"v": 42}), 42)

    def test_missing_handler_raises_keyerror(self):
        client = MockMCPClient({})
        with self.assertRaises(KeyError):
            client.call_tool("nope", {})

    def test_list_tools_returns_handler_names_sorted(self):
        client = MockMCPClient({"b": lambda a: None, "a": lambda a: None})
        names = [t["name"] for t in client.list_tools()]
        self.assertEqual(names, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
