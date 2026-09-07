"""Guards for the vendored ``db_server`` MCP fork and its bundled MCP configs.

The fork has no test suite of its own and its heavy deps (fastmcp, asyncpg,
motor) are not part of the SDK extras, so these tests load only the
dependency-free ``app/redact.py`` module by path and inspect the yaml /
build files as text.
"""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
FORK = REPO / "examples" / "general-chat" / "mcp" / "db-server"
MCP_DIR = REPO / "examples" / "general-chat" / "mcp"


def _load_redact():
    spec = importlib.util.spec_from_file_location("db_server_redact", FORK / "app" / "redact.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestRedactDsn(unittest.TestCase):
    def setUp(self) -> None:
        self.redact_dsn = _load_redact().redact_dsn

    def test_masks_userinfo_password(self) -> None:
        self.assertEqual(
            self.redact_dsn("postgresql://mcp_app:s3cr3t@34.61.185.118:5432/appdata"),
            "postgresql://mcp_app:***@34.61.185.118:5432/appdata",
        )

    def test_handles_sqlalchemy_driver_schemes(self) -> None:
        self.assertEqual(
            self.redact_dsn("postgresql+asyncpg://u:p@h/db"),
            "postgresql+asyncpg://u:***@h/db",
        )
        self.assertEqual(
            self.redact_dsn("mongodb+srv://user:pw@cluster.example.net/db"),
            "mongodb+srv://user:***@cluster.example.net/db",
        )

    def test_password_with_special_chars(self) -> None:
        self.assertEqual(
            self.redact_dsn("mysql+aiomysql://root:p%40ss:word@localhost:3306/x"),
            "mysql+aiomysql://root:***@localhost:3306/x",
        )

    def test_user_without_password_unchanged(self) -> None:
        self.assertEqual(self.redact_dsn("postgresql://user@host/db"), "postgresql://user@host/db")

    def test_no_userinfo_unchanged(self) -> None:
        self.assertEqual(
            self.redact_dsn("sqlite+aiosqlite:////data/default.db"),
            "sqlite+aiosqlite:////data/default.db",
        )

    def test_query_string_password_masked(self) -> None:
        self.assertEqual(
            self.redact_dsn("postgresql://host/db?user=a&password=b&sslmode=require"),
            "postgresql://host/db?user=a&password=***&sslmode=require",
        )

    def test_empty_and_none(self) -> None:
        self.assertEqual(self.redact_dsn(None), "")
        self.assertEqual(self.redact_dsn(""), "")


class TestForkServerNeverEchoesRawDsn(unittest.TestCase):
    """Static guard: every DSN-carrying f-string in the fork goes through redact_dsn."""

    def test_no_raw_url_interpolation(self) -> None:
        source = (FORK / "mcp_server.py").read_text(encoding="utf-8")
        leaks = re.findall(r"\{(?:database_url|final_database_url)\}", source)
        self.assertEqual(leaks, [], f"raw DSN interpolated into output: {leaks}")
        self.assertIn("from redact import redact_dsn", source)
        self.assertIn("redact_dsn(os.getenv('DATABASE_URL'))", source)

    def test_dynamic_connect_gated_off_by_default(self) -> None:
        source = (FORK / "mcp_server.py").read_text(encoding="utf-8")
        self.assertIn('os.getenv("MCP_ALLOW_DYNAMIC_CONNECT", "0")', source)
        # The gate must be the first thing connect_to_database does.
        body = source.split("async def connect_to_database", 1)[1]
        self.assertLess(
            body.index("_dynamic_connect_enabled()"),
            body.index("DatabaseManager()"),
        )


class TestBundledMcpConfigs(unittest.TestCase):
    def _load(self, name: str) -> dict:
        return yaml.safe_load((MCP_DIR / name).read_text(encoding="utf-8"))["mcp"]

    def test_db_server_denies_dynamic_connect_at_registry_level(self) -> None:
        cfg = self._load("db-server-docker.yaml")
        self.assertIn("db_server.connect_to_database", cfg["policy"]["denied_tools"])

    def test_db_server_image_tag_consistent_across_build_and_deploy(self) -> None:
        cfg = self._load("db-server-docker.yaml")
        image = next(a for a in cfg["servers"]["db_server"]["args"] if "mcp-db-server:" in a)
        for rel in ("cloudbuild.mcp-db-server.yaml", "deploy/deploy.sh"):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn(image, text, f"{rel} does not reference {image}")

    def test_stdio_dashboard_servers_allow_cold_start(self) -> None:
        # Cold start of the dashboard/aggregate stdio servers exceeded 30 s in
        # prod (2026-09-07): the artifact was written but the call reported a
        # timeout and the agent retried via a duplicate tool.
        for name in ("dashboard-generator-stdio.yaml", "aggregate-data-stdio.yaml"):
            cfg = self._load(name)
            self.assertGreaterEqual(cfg["policy"]["max_timeout_seconds"], 120, name)
            for server_name, server in cfg["servers"].items():
                self.assertGreaterEqual(server["timeout_seconds"], 120, f"{name}:{server_name}")


if __name__ == "__main__":
    unittest.main()
