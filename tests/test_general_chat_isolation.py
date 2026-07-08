"""Per-user isolation tests for General Chat (sessions + sources + uploads)."""

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

from openbench.integrations.firebase_auth import FirebaseUser

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))


pytestmark = pytest.mark.integration

USER_A = FirebaseUser(uid="uid-a", email="alice@example.com")
USER_B = FirebaseUser(uid="uid-b", email="bob@example.com")

A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}


class TestGeneralChatUserIsolation(unittest.TestCase):
    """Two allowlisted users must never see each other's data."""

    def _client(self, users: dict[str, FirebaseUser] | None = None) -> TestClient:
        users = users or {"token-a": USER_A, "token-b": USER_B}
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
                    "GENERAL_CHAT_FIREBASE_PROJECT_ID": "demo-project",
                    "GENERAL_CHAT_ALLOWED_EMAILS": ",".join(
                        sorted({(u.email or "").lower() for u in users.values()})
                    ),
                    "OPENBENCH_PROFILE_DIR": str(self.tmpdir / "profiles"),
                },
                clear=False,
            )
        )
        environ.pop("OPENBENCH_AUTH_DISABLED", None)

        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))

        verifier = Mock()
        verifier.verify.side_effect = lambda token, **_kw: users[token]
        verifier_cls = stack.enter_context(patch("general_chat.server.auth.FirebaseIDVerifier"))
        verifier_cls.return_value = verifier

        from general_chat.server import auth as auth_module
        from general_chat.server.app import create_app

        auth_module._verifier.cache_clear()
        self.addCleanup(auth_module._verifier.cache_clear)
        return TestClient(create_app())

    def _seed_session(self, owner: str, session_id: str, title: str = "Seeded") -> None:
        from openbench.chat.session import ChatSession
        from openbench.chat.stores.sqlite import SQLiteSessionStore

        store = SQLiteSessionStore(
            str(self.tmpdir / "storage" / "sessions.db"), owner=owner
        )
        store.save(ChatSession(session_id=session_id, title=title))

    def test_session_list_is_scoped_per_user(self):
        client = self._client()
        self._seed_session("alice@example.com", "session-a")

        as_a = client.get("/sessions", headers=A).json()
        as_b = client.get("/sessions", headers=B).json()

        self.assertEqual([s["sessionId"] for s in as_a], ["session-a"])
        self.assertEqual(as_b, [])

    def test_get_foreign_session_is_404(self):
        client = self._client()
        self._seed_session("alice@example.com", "session-a")

        self.assertEqual(client.get("/sessions/session-a", headers=A).status_code, 200)
        self.assertEqual(client.get("/sessions/session-a", headers=B).status_code, 404)

    def test_delete_foreign_session_leaves_it_intact(self):
        client = self._client()
        self._seed_session("alice@example.com", "session-a")
        client.post(
            "/chat/sources/session-a/text",
            headers=A,
            json={"name": "note", "text": "alice's private context"},
        )

        client.delete("/sessions/session-a", headers=B)

        # A's session and sources survive B's delete attempt.
        self.assertEqual(client.get("/sessions/session-a", headers=A).status_code, 200)
        sources = client.get("/chat/sources/session-a", headers=A).json()
        self.assertEqual(len(sources), 1)

    def test_sources_on_same_thread_id_are_isolated(self):
        client = self._client()
        client.post(
            "/chat/sources/thread-x/text",
            headers=A,
            json={"name": "a-note", "text": "alpha secret"},
        )
        client.post(
            "/chat/sources/thread-x/text",
            headers=B,
            json={"name": "b-note", "text": "bravo secret"},
        )

        a_sources = client.get("/chat/sources/thread-x", headers=A).json()
        b_sources = client.get("/chat/sources/thread-x", headers=B).json()

        self.assertEqual([s["name"] for s in a_sources], ["a-note"])
        self.assertEqual([s["name"] for s in b_sources], ["b-note"])

        a_search = client.get(
            "/chat/sources/thread-x/search", headers=A, params={"q": "bravo"}
        ).json()
        self.assertEqual(a_search["results"], [])

    def test_foreign_source_delete_is_404(self):
        client = self._client()
        created = client.post(
            "/chat/sources/thread-x/text",
            headers=A,
            json={"name": "a-note", "text": "alpha secret"},
        ).json()

        response = client.delete(
            f"/chat/sources/thread-x/{created['id']}", headers=B
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            len(client.get("/chat/sources/thread-x", headers=A).json()), 1
        )

    def test_upload_lookup_is_scoped_per_user(self):
        client = self._client()
        upload = client.post(
            "/chat/upload",
            headers=A,
            files={"file": ("notes.txt", b"hello isolation", "text/plain")},
            data={"sessionId": "thread-up"},
        )
        self.assertEqual(upload.status_code, 200)
        file_id = upload.json()["id"].replace("source-", "")

        # Resolve the actual upload file id from A's record url (/uploads/<file-id>/...).
        record = upload.json()
        url = record.get("url") or ""
        file_id = url.split("/")[2] if url.startswith("/uploads/") else file_id

        as_a = client.get(f"/chat/uploads/{file_id}", headers=A)
        as_b = client.get(f"/chat/uploads/{file_id}", headers=B)

        self.assertEqual(as_a.status_code, 200)
        self.assertEqual(as_b.status_code, 404)

    def test_email_casing_is_normalized(self):
        cased = FirebaseUser(uid="uid-a", email="Alice@Example.com")
        client = self._client(users={"token-a": USER_A, "token-cased": cased})
        client.post(
            "/chat/sources/thread-case/text",
            headers={"Authorization": "Bearer token-cased"},
            json={"name": "note", "text": "case test"},
        )

        # Same user with lowercase email claim sees the same data.
        sources = client.get("/chat/sources/thread-case", headers=A).json()
        self.assertEqual([s["name"] for s in sources], ["note"])


class TestGeneralChatLocalSentinel(unittest.TestCase):
    """With auth disabled, all data belongs to the 'local' sentinel owner."""

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
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(self.tmpdir / "profiles"),
                },
                clear=False,
            )
        )
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def test_sources_work_and_land_under_local_owner(self):
        client = self._client()
        response = client.post(
            "/chat/sources/thread-local/text",
            json={"name": "note", "text": "local dev"},
        )

        self.assertEqual(response.status_code, 200)
        listed = client.get("/chat/sources/thread-local").json()
        self.assertEqual([s["name"] for s in listed], ["note"])
        self.assertEqual(listed[0].get("owner"), "local")
        local_file = self.tmpdir / "storage" / "sources" / "local" / "thread-local.json"
        self.assertTrue(local_file.exists())

    def test_session_rows_are_stamped_local(self):
        import sqlite3

        client = self._client()
        from openbench.chat.session import ChatSession
        from openbench.chat.stores.sqlite import SQLiteSessionStore

        store = SQLiteSessionStore(
            str(self.tmpdir / "storage" / "sessions.db"), owner="local"
        )
        store.save(ChatSession(session_id="s-local", title="Local"))

        listed = client.get("/sessions").json()
        self.assertEqual([s["sessionId"] for s in listed], ["s-local"])

        conn = sqlite3.connect(str(self.tmpdir / "storage" / "sessions.db"))
        try:
            owner = conn.execute(
                "SELECT owner FROM sessions WHERE session_id = 's-local'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(owner, "local")


if __name__ == "__main__":
    unittest.main()
