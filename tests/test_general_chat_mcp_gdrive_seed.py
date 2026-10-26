"""Tests for the disabled-by-default Google Drive MCP seed."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.mcp_bootstrap import (  # noqa: E402
    BUNDLED_MCP_CONFIGS,
    DISABLED_BY_DEFAULT_CONFIGS,
    seed_all_mcp_registry,
)
from general_chat.mcp_registry import MCPServerRegistryStore  # noqa: E402

CONFIG_DIR = (
    Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "mcp"
)


def _find_server(store: MCPServerRegistryStore, name: str) -> dict | None:
    return next(
        (
            item
            for item in store.list_payload()["servers"]
            if item.get("name") == name
        ),
        None,
    )


class TestGoogleDriveMcpSeed(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def test_config_registered_in_bundle(self):
        self.assertIn("google-drive-mcp.yaml", BUNDLED_MCP_CONFIGS)
        self.assertIn("google-drive-mcp.yaml", DISABLED_BY_DEFAULT_CONFIGS)
        self.assertTrue((CONFIG_DIR / "google-drive-mcp.yaml").exists())

    def test_seeded_disabled_by_default(self):
        summary = seed_all_mcp_registry(self.root, config_dir=CONFIG_DIR)
        self.assertIn("google_drive", summary["seeded"])
        store = MCPServerRegistryStore(Path(self.root))
        server = _find_server(store, "google_drive")
        self.assertIsNotNone(server)
        self.assertFalse(server["enabled"])

    def test_admin_enable_survives_reseed(self):
        seed_all_mcp_registry(self.root, config_dir=CONFIG_DIR)
        store = MCPServerRegistryStore(Path(self.root))
        server = _find_server(store, "google_drive")
        store.set_server_enabled(server["id"], True)

        seed_all_mcp_registry(self.root, config_dir=CONFIG_DIR)
        store = MCPServerRegistryStore(Path(self.root))
        server = _find_server(store, "google_drive")
        self.assertTrue(server["enabled"])


if __name__ == "__main__":
    unittest.main()
