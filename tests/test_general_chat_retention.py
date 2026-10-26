"""Tests for the session retention sweep and admin-blindness guarantees."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.retention import run_retention_sweep  # noqa: E402

from openbench.chat.session import ChatSession  # noqa: E402
from openbench.chat.stores.sqlite import SQLiteSessionStore  # noqa: E402

pytestmark = pytest.mark.integration


class _UserRecord:
    def __init__(self, email):
        self.email = email


class _UserStore:
    def __init__(self, emails):
        self._emails = emails

    def list_users(self):
        return [_UserRecord(email) for email in self._emails]


class _SourceStore:
    """Per-owner fake with the list/clear subset the sweep touches."""

    def __init__(self):
        self.records: dict[str, list[str]] = {}
        self.cleared: list[str] = []

    def list(self, session_id):
        return self.records.get(session_id, [])

    def clear(self, session_id):
        self.cleared.append(session_id)
        self.records.pop(session_id, None)


class _MemoryStore:
    def __init__(self):
        self.deleted: list[str] = []

    def delete_session(self, session_id):
        self.deleted.append(session_id)


def _seed_session(store, session_id, *, days_old):
    session = ChatSession(session_id=session_id)
    session.updated_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    store.save(session)


class TestRunRetentionSweep(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = str(Path(tmp.name) / "sessions.db")
        self.source_stores: dict[str, _SourceStore] = {}
        self.memory_store = _MemoryStore()
        self.purged: list[list] = []

    def _session_store_for(self, owner):
        return SQLiteSessionStore(db_path=self.db_path, owner=owner)

    def _sources_for(self, owner):
        return self.source_stores.setdefault(owner, _SourceStore())

    def _sweep(self, *, retention_days, emails=("a@x.co",)):
        return run_retention_sweep(
            retention_days=retention_days,
            user_store=_UserStore(list(emails)),
            session_store_for=self._session_store_for,
            sources_for=self._sources_for,
            purge_artifacts=self.purged.append,
            memory_store=self.memory_store,
        )

    def test_deletes_expired_keeps_fresh_across_owners(self):
        local = self._session_store_for("local")
        user = self._session_store_for("a@x.co")
        _seed_session(local, "old-local", days_old=40)
        _seed_session(local, "fresh-local", days_old=1)
        _seed_session(user, "old-user", days_old=31)
        self._sources_for("a@x.co").records["old-user"] = ["record"]

        summary = self._sweep(retention_days=30)

        self.assertEqual(summary, {"deleted_sessions": 2, "owners_scanned": 2})
        self.assertIsNone(local.load("old-local"))
        self.assertIsNotNone(local.load("fresh-local"))
        self.assertIsNone(user.load("old-user"))
        # Sources purged + cleared, memory rows dropped.
        self.assertEqual(self.purged, [[], ["record"]])
        self.assertIn("old-user", self.source_stores["a@x.co"].cleared)
        self.assertCountEqual(self.memory_store.deleted, ["old-local", "old-user"])

    def test_zero_days_is_noop(self):
        local = self._session_store_for("local")
        _seed_session(local, "old", days_old=400)
        summary = self._sweep(retention_days=0)
        self.assertEqual(summary, {"deleted_sessions": 0, "owners_scanned": 0})
        self.assertIsNotNone(local.load("old"))

    def test_idempotent_second_run(self):
        local = self._session_store_for("local")
        _seed_session(local, "old", days_old=40)
        first = self._sweep(retention_days=30, emails=())
        second = self._sweep(retention_days=30, emails=())
        self.assertEqual(first["deleted_sessions"], 1)
        self.assertEqual(second["deleted_sessions"], 0)

    def test_failure_on_one_session_does_not_stop_sweep(self):
        local = self._session_store_for("local")
        _seed_session(local, "bad", days_old=40)
        _seed_session(local, "old", days_old=40)

        calls = []

        def purge(records):
            calls.append(records)
            if len(calls) == 1:
                raise RuntimeError("boom")

        summary = run_retention_sweep(
            retention_days=30,
            user_store=_UserStore([]),
            session_store_for=self._session_store_for,
            sources_for=self._sources_for,
            purge_artifacts=purge,
            memory_store=self.memory_store,
        )
        self.assertEqual(summary["deleted_sessions"], 1)

    def test_paginates_past_one_page(self):
        local = self._session_store_for("local")
        for i in range(205):
            _seed_session(local, f"old-{i}", days_old=40)
        summary = self._sweep(retention_days=30, emails=())
        self.assertEqual(summary["deleted_sessions"], 205)


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
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def _session_db(self) -> str:
        return str(self.tmpdir / "storage" / "sessions.db")


class TestSweepEndpoint(_AppHarness):
    def test_sweep_deletes_backdated_local_sessions(self):
        client = self._client()
        put = client.put("/admin/privacy", json={"retentionDays": 30})
        self.assertEqual(put.status_code, 200)

        store = SQLiteSessionStore(db_path=self._session_db(), owner="local")
        _seed_session(store, "expired", days_old=45)
        _seed_session(store, "fresh", days_old=2)

        response = client.post("/admin/privacy/sweep")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["deletedSessions"], 1)
        self.assertGreaterEqual(payload["ownersScanned"], 1)
        self.assertIsNone(store.load("expired"))
        self.assertIsNotNone(store.load("fresh"))

    def test_sweep_disabled_by_default(self):
        client = self._client()
        store = SQLiteSessionStore(db_path=self._session_db(), owner="local")
        _seed_session(store, "expired", days_old=400)
        response = client.post("/admin/privacy/sweep")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"deletedSessions": 0, "ownersScanned": 0})
        self.assertIsNotNone(store.load("expired"))


class TestAdminBlindness(_AppHarness):
    """Admins manage users and settings but never see another owner's chats.

    Auth-disabled local mode maps every request to owner ``local``, so a
    foreign owner's rows are simply invisible — these tests pin that the
    admin role gets no special cross-owner access via the API.
    """

    def test_admin_cannot_read_foreign_session(self):
        client = self._client()
        foreign = SQLiteSessionStore(db_path=self._session_db(), owner="user@corp.co.id")
        _seed_session(foreign, "foreign-session", days_old=0)

        # Admin (local role default) requests the foreign session id.
        self.assertEqual(client.get("/sessions/{}".format("foreign-session")).status_code, 404)
        # And it never shows in the admin's own listing.
        listed = client.get("/sessions").json()
        self.assertEqual([s for s in listed if s["sessionId"] == "foreign-session"], [])

    def test_admin_delete_of_foreign_session_touches_nothing(self):
        client = self._client()
        foreign = SQLiteSessionStore(db_path=self._session_db(), owner="user@corp.co.id")
        _seed_session(foreign, "foreign-session", days_old=0)

        response = client.delete("/sessions/foreign-session")
        # Endpoint is idempotent by design; the foreign row must survive.
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(foreign.load("foreign-session"))


if __name__ == "__main__":
    unittest.main()
