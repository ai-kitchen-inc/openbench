"""Tests for team groups: store, capability overrides, and group sources."""

from __future__ import annotations

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

from general_chat.capabilities import (  # noqa: E402
    CapabilityCache,
    default_capabilities,
    resolve_capabilities,
)
from general_chat.group_store import (  # noqa: E402
    DuplicateGroupError,
    JsonGroupStore,
    PostgresGroupStore,
    slugify_group_name,
)

pytestmark = pytest.mark.integration


class _MemorySettings:
    def __init__(self):
        self.data: dict = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, *, updated_by=""):
        self.data[key] = value


class TestJsonGroupStore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = JsonGroupStore(tmp.name)

    def test_crud_round_trip(self):
        record = self.store.add("Tim Keuangan", description="Finance", created_by="a@x.co")
        self.assertEqual(record.id, "tim-keuangan")
        self.assertEqual(self.store.get("tim-keuangan").name, "Tim Keuangan")
        updated = self.store.update("tim-keuangan", description="Departemen keuangan")
        self.assertEqual(updated.description, "Departemen keuangan")
        self.assertEqual([g.id for g in self.store.list()], ["tim-keuangan"])
        self.assertTrue(self.store.remove("tim-keuangan"))
        self.assertFalse(self.store.remove("tim-keuangan"))
        self.assertIsNone(self.store.get("tim-keuangan"))

    def test_duplicate_rejected(self):
        self.store.add("HR")
        with self.assertRaises(DuplicateGroupError):
            self.store.add("hr")

    def test_slugify(self):
        self.assertEqual(slugify_group_name("Tim Keuangan & Pajak"), "tim-keuangan-pajak")


class TestPostgresGroupStoreStructure(unittest.TestCase):
    def test_sql_shape_and_interface(self):
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

        PostgresGroupStore(conn=_Conn())
        joined = "\n".join(executed)
        self.assertIn("openbench_groups", joined)
        for column in ("id TEXT PRIMARY KEY", "name", "description", "created_by"):
            self.assertIn(column, joined)
        for method in ("list", "get", "add", "update", "remove"):
            self.assertTrue(callable(getattr(PostgresGroupStore, method, None)))


class TestGroupCapabilityResolution(unittest.TestCase):
    def test_defaults_include_empty_groups(self):
        self.assertEqual(default_capabilities()["groups"], {})

    def test_resolve_keeps_valid_group_overrides(self):
        resolved = resolve_capabilities(
            {
                "groups": {
                    "finance": {"dashboards": False, "unknown_flag": True, "bad": "x"},
                    "empty": {},
                }
            }
        )
        self.assertEqual(resolved["groups"], {"finance": {"dashboards": False}})

    def test_allows_group_override_wins(self):
        cache = CapabilityCache(_MemorySettings())
        # Role default: dashboards True, mcp_management False for "user".
        self.assertTrue(cache.allows("user", "", "dashboards"))
        self.assertFalse(cache.allows("user", "", "mcp_management"))
        cache.update(
            {"groups": {"finance": {"dashboards": False, "mcp_management": True}}}
        )
        self.assertFalse(cache.allows("user", "finance", "dashboards"))
        self.assertTrue(cache.allows("user", "finance", "mcp_management"))
        # Other groups unaffected; admins still bypass.
        self.assertTrue(cache.allows("user", "hr", "dashboards"))
        self.assertTrue(cache.allows("admin", "finance", "dashboards"))

    def test_overlay_none_removes_override(self):
        cache = CapabilityCache(_MemorySettings())
        cache.update({"groups": {"finance": {"dashboards": False}}})
        cache.update({"groups": {"finance": {"dashboards": None}}})
        self.assertEqual(cache.value["groups"], {})
        self.assertTrue(cache.allows("user", "finance", "dashboards"))


class _AppHarness(unittest.TestCase):
    def _client(self) -> TestClient:
        stack = ExitStack()
        self.addCleanup(stack.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmpdir = Path(tmp.name)
        stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(self.tmpdir / "storage"),
                    "GENERAL_CHAT_UPLOAD_DIR": str(self.tmpdir / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(self.tmpdir / "downloads"),
                    "GENERAL_CHAT_MEMORY_DB": str(self.tmpdir / "memory.db"),
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(self.tmpdir / "profiles"),
                },
                clear=False,
            )
        )
        environ.pop("GENERAL_CHAT_FIREBASE_PROJECT_ID", None)
        environ.pop("GENERAL_CHAT_LOCAL_ROLE", None)
        environ.pop("GENERAL_CHAT_LOCAL_GROUP", None)
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
        from general_chat.server.app import create_app

        return TestClient(create_app())


class TestGroupRoutes(_AppHarness):
    def test_crud_and_member_assignment(self):
        client = self._client()
        created = client.post(
            "/admin/groups", json={"name": "Tim Keuangan", "description": "Finance"}
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["id"], "tim-keuangan")

        duplicate = client.post("/admin/groups", json={"name": "Tim Keuangan"})
        self.assertEqual(duplicate.status_code, 409)

        client.post("/admin/users", json={"email": "budi@corp.co.id", "role": "user"})
        assigned = client.patch(
            "/admin/users/budi@corp.co.id", json={"group": "tim-keuangan"}
        )
        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(assigned.json()["group"], "tim-keuangan")

        unknown = client.patch("/admin/users/budi@corp.co.id", json={"group": "ghost"})
        self.assertEqual(unknown.status_code, 400)

        listed = client.get("/admin/groups").json()["groups"]
        self.assertEqual(listed[0]["memberCount"], 1)

    def test_admin_only(self):
        client = self._client()
        headers = {"X-Local-Role": "user"}
        self.assertEqual(client.get("/admin/groups", headers=headers).status_code, 403)
        self.assertEqual(
            client.post("/admin/groups", json={"name": "x"}, headers=headers).status_code,
            403,
        )

    def test_capabilities_put_validates_group_ids(self):
        client = self._client()
        client.post("/admin/groups", json={"name": "Finance"})
        ok = client.put(
            "/admin/capabilities", json={"groups": {"finance": {"dashboards": False}}}
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["groups"], {"finance": {"dashboards": False}})
        bad = client.put(
            "/admin/capabilities", json={"groups": {"ghost": {"dashboards": False}}}
        )
        self.assertEqual(bad.status_code, 400)

    def test_group_capability_gate_via_local_header(self):
        client = self._client()
        client.post("/admin/groups", json={"name": "Finance"})
        client.put(
            "/admin/capabilities",
            json={"groups": {"finance": {"dashboards": False, "mcp_management": True}}},
        )
        user = {"X-Local-Role": "user"}
        finance = {"X-Local-Role": "user", "X-Local-Group": "finance"}
        # Role default allows dashboards; the finance override disables it.
        self.assertNotEqual(client.get("/dashboard/list", headers=user).status_code, 403)
        self.assertEqual(client.get("/dashboard/list", headers=finance).status_code, 403)
        # Role default denies MCP management; the finance override enables it.
        self.assertEqual(client.get("/mcp/tools", headers=user).status_code, 403)
        self.assertNotEqual(client.get("/mcp/tools", headers=finance).status_code, 403)

    def test_account_me_reports_group_effective_flags(self):
        client = self._client()
        client.post("/admin/groups", json={"name": "Finance"})
        client.put(
            "/admin/capabilities", json={"groups": {"finance": {"dashboards": False}}}
        )
        me = client.get(
            "/account/me",
            headers={"X-Local-Role": "user", "X-Local-Group": "finance"},
        ).json()
        self.assertEqual(me["group"], "finance")
        self.assertFalse(me["capabilities"]["dashboards"])

    def test_delete_cascade(self):
        client = self._client()
        client.post("/admin/groups", json={"name": "Finance"})
        client.post("/admin/users", json={"email": "budi@corp.co.id", "role": "user"})
        client.patch("/admin/users/budi@corp.co.id", json={"group": "finance"})
        client.put(
            "/admin/capabilities", json={"groups": {"finance": {"dashboards": False}}}
        )
        client.post(
            "/admin/groups/finance/sources/text",
            json={"name": "Aturan", "text": "Kebijakan reimburse maksimal 14 hari."},
        )

        deleted = client.delete("/admin/groups/finance")
        self.assertEqual(deleted.status_code, 200)

        users = client.get("/admin/users").json()["users"]
        budi = next(u for u in users if u["email"] == "budi@corp.co.id")
        self.assertEqual(budi["group"], "")
        self.assertEqual(client.get("/admin/capabilities").json()["groups"], {})
        self.assertEqual(client.get("/admin/groups").json()["groups"], [])


class TestGroupSources(_AppHarness):
    def test_group_sources_reach_members_only(self):
        client = self._client()
        client.post("/admin/groups", json={"name": "Finance"})
        response = client.post(
            "/admin/groups/finance/sources/text",
            json={"name": "Kebijakan", "text": "Batas reimburse Rp2.000.000."},
        )
        self.assertEqual(response.status_code, 200)

        member = client.get(
            "/account/shared-sources",
            headers={"X-Local-Role": "user", "X-Local-Group": "finance"},
        ).json()
        self.assertEqual(len(member["groupSources"]), 1)
        self.assertEqual(member["groupSources"][0]["name"], "Kebijakan")

        outsider = client.get(
            "/account/shared-sources", headers={"X-Local-Role": "user"}
        ).json()
        self.assertEqual(outsider["groupSources"], [])

    def test_group_source_listing_and_delete(self):
        client = self._client()
        client.post("/admin/groups", json={"name": "Finance"})
        created = client.post(
            "/admin/groups/finance/sources/text",
            json={"name": "Kebijakan", "text": "Isi kebijakan."},
        ).json()
        listed = client.get("/admin/groups/finance/sources").json()["sources"]
        self.assertEqual(len(listed), 1)
        deleted = client.delete(f"/admin/groups/finance/sources/{created['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(client.get("/admin/groups/finance/sources").json()["sources"], [])

    def test_unknown_group_404(self):
        client = self._client()
        self.assertEqual(client.get("/admin/groups/ghost/sources").status_code, 404)


class TestAwpGroupGrounding(_AppHarness):
    def test_awp_includes_group_records_and_protects_them_from_cleanup(self):
        client = self._client()
        client.post("/admin/groups", json={"name": "Finance"})
        client.post(
            "/admin/groups/finance/sources/text",
            json={"name": "Kebijakan", "text": "Batas reimburse Rp2.000.000."},
        )

        captured: dict = {}

        class _FakeHandler:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            async def handle(self, request):
                from fastapi.responses import JSONResponse

                # Exercise the cleanup filter exactly like a finished turn.
                on_complete = captured.get("on_stream_complete")
                if on_complete:
                    on_complete(captured.get("source_records") or [])
                return JSONResponse({"ok": True})

        with patch("general_chat.server.app.GeneralChatHandler", _FakeHandler):
            response = client.post(
                "/awp",
                json={"sessionId": "sess-1", "messages": []},
                headers={"X-Local-Group": "finance"},
            )
        self.assertEqual(response.status_code, 200)

        records = captured["source_records"]
        self.assertEqual([r.name for r in records], ["Kebijakan"])
        self.assertTrue(all(r.owner == "group:finance" for r in records))

        # The turn-end cleanup ran over the records; the group source must
        # survive it (cleanup only ever touches the session slice).
        still_there = client.get("/admin/groups/finance/sources").json()["sources"]
        self.assertEqual(len(still_there), 1)


if __name__ == "__main__":
    unittest.main()
