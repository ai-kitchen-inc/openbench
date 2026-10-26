"""Tests for the MCP discovery cache data structures."""

from __future__ import annotations

import unittest

from openbench.mcp.discovery import DiscoveredMCPServer, MCPDiscoveryCache


class TestDiscoveredMCPServer(unittest.TestCase):
    def test_defaults_are_empty(self):
        server = DiscoveredMCPServer(name="files")
        self.assertEqual(server.name, "files")
        self.assertEqual(server.capabilities, {})
        self.assertEqual(server.tools, {})
        self.assertEqual(server.resources, {})
        self.assertEqual(server.prompts, {})

    def test_default_containers_are_not_shared(self):
        first = DiscoveredMCPServer(name="a")
        second = DiscoveredMCPServer(name="b")
        first.tools["read"] = {"name": "read"}
        self.assertEqual(second.tools, {})


class TestMCPDiscoveryCache(unittest.TestCase):
    def test_empty_cache_lists_nothing(self):
        self.assertEqual(MCPDiscoveryCache().list_namespaced_tools(), {})

    def test_tools_are_namespaced_per_server(self):
        cache = MCPDiscoveryCache(
            servers={
                "files": DiscoveredMCPServer(
                    name="files",
                    tools={"read": {"name": "read"}, "write": {"name": "write"}},
                ),
                "search": DiscoveredMCPServer(
                    name="search",
                    tools={"read": {"name": "read", "description": "search read"}},
                ),
            }
        )
        namespaced = cache.list_namespaced_tools()
        self.assertEqual(sorted(namespaced), ["files.read", "files.write", "search.read"])
        # Same tool name on two servers must stay distinct.
        self.assertEqual(namespaced["search.read"]["description"], "search read")

    def test_clear_empties_servers(self):
        cache = MCPDiscoveryCache(servers={"files": DiscoveredMCPServer(name="files")})
        cache.clear()
        self.assertEqual(cache.servers, {})
        self.assertEqual(cache.list_namespaced_tools(), {})


if __name__ == "__main__":
    unittest.main()
