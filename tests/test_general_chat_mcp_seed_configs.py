"""Tests for seeding a selected subset of bundled MCP configs (local mock DB path)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from os import environ
from pathlib import Path
from unittest.mock import patch

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))
SCRIPTS = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from general_chat.mcp_bootstrap import (  # noqa: E402
    SEED_CONFIGS_ENV,
    seed_all_mcp_registry,
    seed_config_names_from_env,
    seed_mcp_configs,
)
from general_chat.mcp_registry import MCPServerRegistryStore  # noqa: E402
from seed_live_demo_db import print_env_lines, seed  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "mcp"


def _names(store: MCPServerRegistryStore) -> set[str]:
    return {item["name"] for item in store.list_payload()["servers"] if item.get("name")}


class TestSeedSelectedConfigs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_seeds_only_the_requested_config(self):
        with patch.dict(environ, {"MCP_DB_DATABASE_URL": "sqlite+aiosqlite:///x.db"}):
            summary = seed_mcp_configs(self.root, ["db-server-local.yaml"], config_dir=CONFIG_DIR)
        self.assertEqual(summary["seeded"], ["db_server"])
        self.assertEqual(summary["errors"], [])
        names = _names(MCPServerRegistryStore(self.root))
        self.assertIn("db_server", names)
        self.assertNotIn("google_drive", names)
        self.assertNotIn("filesystem", names)

    def test_rejects_paths_and_reports_missing(self):
        summary = seed_mcp_configs(
            self.root,
            ["../secrets.yaml", "C:/evil.yaml", "notes.txt", "does-not-exist.yaml"],
            config_dir=CONFIG_DIR,
        )
        self.assertEqual(summary["seeded"], [])
        self.assertEqual(summary["missing"], ["does-not-exist.yaml"])
        self.assertEqual(
            sorted(e["config"] for e in summary["errors"]),
            ["../secrets.yaml", "C:/evil.yaml", "notes.txt"],
        )
        self.assertEqual(_names(MCPServerRegistryStore(self.root)) - {"openbench"}, set())

    def test_seed_all_still_seeds_the_bundle(self):
        with patch.dict(environ, {}, clear=False):
            environ.pop("GENERAL_CHAT_MCP_DB_SERVER_CONFIG", None)
            summary = seed_all_mcp_registry(self.root, config_dir=CONFIG_DIR)
        self.assertIn("db_server", summary["seeded"])
        self.assertIn("google_drive", summary["seeded"])

    def test_env_name_parsing(self):
        with patch.dict(
            environ,
            {SEED_CONFIGS_ENV: " db-server-local.yaml, ,filesystem-mcp.yaml ,db-server-local.yaml"},
        ):
            self.assertEqual(
                seed_config_names_from_env(), ("db-server-local.yaml", "filesystem-mcp.yaml")
            )
        with patch.dict(environ, {SEED_CONFIGS_ENV: ""}):
            self.assertEqual(seed_config_names_from_env(), ())


class TestSeedScriptEnvLines(unittest.TestCase):
    def test_print_env_lines_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "live-demo.db"
            self.assertGreater(seed(db), 0)
            lines = print_env_lines(
                db, Path(tmp) / ".venv-dbserver", example_root=Path(tmp) / "gc", windows=True
            )
        keys = [line.split("=", 1)[0] for line in lines]
        self.assertEqual(
            keys,
            [
                "DB_SERVER_MCP_PYTHON",
                "MCP_DB_DATABASE_URL",
                "DB_SERVER_MCP_CWD",
                "GENERAL_CHAT_SEED_MCP_CONFIGS",
            ],
        )
        self.assertTrue(lines[0].endswith("/.venv-dbserver/Scripts/python.exe"))
        self.assertTrue(lines[1].startswith("MCP_DB_DATABASE_URL=sqlite+aiosqlite:///"))
        self.assertNotIn("\\", "".join(lines))
        self.assertTrue(lines[2].endswith("/gc/mcp/db-server"))
        self.assertEqual(lines[3], "GENERAL_CHAT_SEED_MCP_CONFIGS=db-server-local.yaml")

    def test_posix_interpreter_path(self):
        lines = print_env_lines(Path("/tmp/x.db"), Path("/opt/venv"), windows=False)
        self.assertEqual(lines[0], "DB_SERVER_MCP_PYTHON=/opt/venv/bin/python")


if __name__ == "__main__":
    unittest.main()
