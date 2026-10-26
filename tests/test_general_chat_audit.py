"""Tests for the append-only audit trail."""

from __future__ import annotations

import csv
import io
import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.audit_store import (  # noqa: E402
    AuditRecord,
    JsonAuditStore,
    PostgresAuditStore,
)

pytestmark = pytest.mark.integration


class TestJsonAuditStore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = JsonAuditStore(tmp.name)

    def _seed(self, *records):
        for record in records:
            self.store.append(record)

    def test_append_and_list_newest_first(self):
        self._seed(
            AuditRecord(action="user.add", actor="a@x.co", ts="2026-08-01T10:00:00+00:00"),
            AuditRecord(action="user.delete", actor="a@x.co", ts="2026-08-02T10:00:00+00:00"),
        )
        items = self.store.list()
        self.assertEqual([r.action for r in items], ["user.delete", "user.add"])
        self.assertEqual(self.store.count(), 2)

    def test_filters(self):
        self._seed(
            AuditRecord(action="user.add", actor="a@x.co", ts="2026-08-01T10:00:00+00:00"),
            AuditRecord(action="user.delete", actor="b@x.co", ts="2026-08-02T10:00:00+00:00"),
            AuditRecord(action="privacy.update", actor="a@x.co", ts="2026-08-03T10:00:00+00:00"),
        )
        self.assertEqual(self.store.count(actor="a@x.co"), 2)
        # Action filter is a prefix match so "user" covers user.*.
        self.assertEqual(self.store.count(action="user"), 2)
        self.assertEqual(self.store.count(since="2026-08-02"), 2)
        self.assertEqual(self.store.count(until="2026-08-01T23:59:59"), 1)
        items = self.store.list(actor="a@x.co", action="privacy")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].action, "privacy.update")

    def test_pagination(self):
        self._seed(
            *[
                AuditRecord(action="chat.turn", ts=f"2026-08-01T10:00:{i:02d}+00:00")
                for i in range(5)
            ]
        )
        page = self.store.list(limit=2, offset=2)
        # Newest-first: seconds 04,03,02,01,00 → offset 2 gives 02,01.
        self.assertEqual(
            [r.ts for r in page],
            ["2026-08-01T10:00:02+00:00", "2026-08-01T10:00:01+00:00"],
        )
        self.assertEqual(len(self.store.list(limit=2, offset=4)), 1)

    def test_malformed_line_skipped(self):
        self._seed(AuditRecord(action="user.add"))
        with self.store.path.open("a", encoding="utf-8") as handle:
            handle.write("not json\n")
        self._seed(AuditRecord(action="user.delete"))
        self.assertEqual(self.store.count(), 2)

    def test_detail_round_trip(self):
        self._seed(AuditRecord(action="x", detail={"session": "s1", "model": "m"}))
        self.assertEqual(self.store.list()[0].detail, {"session": "s1", "model": "m"})


class TestPostgresAuditStoreStructure(unittest.TestCase):
    """Structural assertions only — no live database in the suite."""

    def test_exposes_same_interface(self):
        for method in ("append", "list", "count"):
            self.assertTrue(callable(getattr(PostgresAuditStore, method, None)))

    def test_requires_connection_info(self):
        with self.assertRaises(ValueError):
            PostgresAuditStore()

    def test_init_db_sql_shape(self):
        executed: list[str] = []

        class _Cursor:
            def execute(self, sql, params=None):
                executed.append(sql)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class _Conn:
            def cursor(self):
                return _Cursor()

            def commit(self):
                pass

        PostgresAuditStore(conn=_Conn())
        joined = "\n".join(executed)
        self.assertIn("openbench_audit_log", joined)
        for column in ("ts", "actor", "role", "action", "target", "detail JSONB", "status"):
            self.assertIn(column, joined)
        self.assertIn("BIGSERIAL", joined)
        self.assertIn("CREATE INDEX IF NOT EXISTS", joined)


class _AppHarness(unittest.TestCase):
    def _client(self, **extra_env) -> TestClient:
        stack = ExitStack()
        self.addCleanup(stack.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmpdir = Path(tmp.name)
        env = {
            "GENERAL_CHAT_STORAGE_ROOT": str(self.tmpdir / "storage"),
            "GENERAL_CHAT_UPLOAD_DIR": str(self.tmpdir / "uploads"),
            "GENERAL_CHAT_DOWNLOAD_DIR": str(self.tmpdir / "downloads"),
            "GENERAL_CHAT_MEMORY_DB": str(self.tmpdir / "memory.db"),
            "OPENBENCH_AUTH_DISABLED": "1",
            "OPENBENCH_PROFILE_DIR": str(self.tmpdir / "profiles"),
        }
        env.update(extra_env)
        stack.enter_context(patch.dict(environ, env, clear=False))
        environ.pop("GENERAL_CHAT_FIREBASE_PROJECT_ID", None)
        environ.pop("GENERAL_CHAT_LOCAL_ROLE", None)
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def _audit_actions(self, client) -> list[str]:
        payload = client.get("/admin/audit?limit=200").json()
        return [item["action"] for item in payload["items"]]


class TestAuditEndpoints(_AppHarness):
    def test_admin_only(self):
        client = self._client()
        headers = {"X-Local-Role": "user"}
        self.assertEqual(client.get("/admin/audit", headers=headers).status_code, 403)
        self.assertEqual(client.get("/admin/audit/export", headers=headers).status_code, 403)

    def test_admin_mutations_recorded(self):
        client = self._client()
        response = client.post(
            "/admin/users", json={"email": "user@corp.co.id", "role": "user"}
        )
        self.assertEqual(response.status_code, 201)
        client.put("/admin/capabilities", json={})
        client.put("/admin/privacy", json={"piiRedaction": True})
        client.delete("/sessions/some-session")

        actions = self._audit_actions(client)
        for expected in ("user.add", "capabilities.update", "privacy.update", "session.delete"):
            self.assertIn(expected, actions)

        payload = client.get("/admin/audit?action=user.add").json()
        self.assertEqual(payload["total"], 1)
        entry = payload["items"][0]
        self.assertEqual(entry["target"], "user@corp.co.id")
        self.assertEqual(entry["actor"], "local")
        self.assertEqual(entry["detail"], {"role": "user"})

    def test_capability_denial_recorded(self):
        client = self._client()
        response = client.get("/mcp/tools", headers={"X-Local-Role": "user"})
        self.assertEqual(response.status_code, 403)
        payload = client.get("/admin/audit?action=capability.denied").json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["target"], "/mcp/tools")
        self.assertEqual(payload["items"][0]["status"], "denied")

    def test_csv_export_and_self_audit(self):
        client = self._client()
        client.post("/admin/users", json={"email": "user@corp.co.id", "role": "user"})
        response = client.get("/admin/audit/export")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("attachment; filename=", response.headers["content-disposition"])

        rows = list(csv.reader(io.StringIO(response.text)))
        self.assertEqual(
            rows[0], ["ts", "actor", "role", "action", "target", "status", "detail"]
        )
        self.assertTrue(any(row[3] == "user.add" for row in rows[1:]))
        # The export itself lands in the trail.
        self.assertIn("audit.export", self._audit_actions(client))

    def test_broken_audit_store_never_breaks_requests(self):
        broken = Mock()
        broken.append.side_effect = RuntimeError("audit disk full")
        with patch("general_chat.server.app.build_audit_store", return_value=broken):
            client = self._client()
            response = client.post(
                "/admin/users", json={"email": "user@corp.co.id", "role": "user"}
            )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(broken.append.called)


if __name__ == "__main__":
    unittest.main()
