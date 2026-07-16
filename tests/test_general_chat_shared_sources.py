"""Tests for admin-curated global shared sources in General Chat."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from openbench.integrations.firebase_auth import FirebaseUser

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))


pytestmark = pytest.mark.integration

ADMIN = FirebaseUser(uid="uid-admin", email="boss@example.com")
MEMBER = FirebaseUser(uid="uid-member", email="member@example.com")
ADMIN_H = {"Authorization": "Bearer token-admin"}
MEMBER_H = {"Authorization": "Bearer token-member"}


class TestGlobalSharedSources(unittest.TestCase):
    def _client(self) -> TestClient:
        stack = ExitStack()
        self.addCleanup(stack.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmpdir = Path(tmp.name)
        stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(tmpdir / "storage"),
                    "GENERAL_CHAT_UPLOAD_DIR": str(tmpdir / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(tmpdir / "downloads"),
                    "GENERAL_CHAT_FIREBASE_PROJECT_ID": "demo-project",
                    "GENERAL_CHAT_BOOTSTRAP_ADMIN": "boss@example.com",
                    "GENERAL_CHAT_ALLOWED_EMAILS": "member@example.com",
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                },
                clear=False,
            )
        )
        environ.pop("OPENBENCH_AUTH_DISABLED", None)
        # This suite exercises the merge branch, not the env-pinned one.
        environ.pop("GENERAL_CHAT_SHARED_SOURCES_OWNER", None)
        environ.pop("GENERAL_CHAT_SHARED_SOURCES_THREAD", None)

        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))

        self.handler_cls = Mock()
        handler_instance = Mock()

        async def _handle(_request):
            return JSONResponse({"ok": True})

        handler_instance.handle = _handle
        self.handler_cls.return_value = handler_instance
        stack.enter_context(
            patch("general_chat.server.app.GeneralChatHandler", self.handler_cls)
        )

        tokens = {"token-admin": ADMIN, "token-member": MEMBER}
        verifier = Mock()
        verifier.verify.side_effect = lambda token, **_kw: tokens[token]
        verifier_cls = stack.enter_context(patch("general_chat.server.auth.FirebaseIDVerifier"))
        verifier_cls.return_value = verifier

        from general_chat.server import auth as auth_module
        from general_chat.server.app import create_app

        auth_module._verifier.cache_clear()
        self.addCleanup(auth_module._verifier.cache_clear)
        return TestClient(create_app())

    def _add_shared_text(self, client: TestClient, name: str, text: str) -> dict:
        response = client.post(
            "/admin/shared-sources/text",
            headers=ADMIN_H,
            json={"name": name, "text": text},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_admin_crud_roundtrip(self):
        client = self._client()
        created = self._add_shared_text(client, "kb-note", "Zylor Bridge opened in 1987.")

        listed = client.get("/admin/shared-sources", headers=ADMIN_H).json()["sources"]
        self.assertEqual([item["name"] for item in listed], ["kb-note"])

        deleted = client.delete(
            f"/admin/shared-sources/{created['id']}", headers=ADMIN_H
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(
            client.get("/admin/shared-sources", headers=ADMIN_H).json()["sources"], []
        )

    def test_user_preview_endpoint_truncates_text(self):
        client = self._client()
        self._add_shared_text(client, "kb-long", "x" * 900)

        payload = client.get("/account/shared-sources", headers=MEMBER_H).json()
        item = payload["sources"][0]
        self.assertEqual(item["name"], "kb-long")
        self.assertEqual(len(item["textPreview"]), 500)
        self.assertTrue(item["textTruncated"])
        self.assertNotIn("text", item)

    def test_admin_shared_source_routes_blocked_for_users(self):
        client = self._client()
        self.assertEqual(
            client.get("/admin/shared-sources", headers=MEMBER_H).status_code, 403
        )
        self.assertEqual(
            client.post(
                "/admin/shared-sources/text",
                headers=MEMBER_H,
                json={"name": "x", "text": "y"},
            ).status_code,
            403,
        )

    def test_awp_merges_shared_and_session_sources(self):
        client = self._client()
        self._add_shared_text(client, "kb-note", "Curated fact.")
        client.post(
            "/chat/sources/session-1/text",
            headers=MEMBER_H,
            json={"name": "my-note", "text": "Member's own context."},
        )

        response = client.post(
            "/awp", headers=MEMBER_H, json={"threadId": "session-1"}
        )

        self.assertEqual(response.status_code, 200)
        kwargs = self.handler_cls.call_args.kwargs
        names = [record.name for record in kwargs["source_records"]]
        self.assertEqual(names, ["kb-note", "my-note"])
        self.assertIsNotNone(kwargs["on_stream_complete"])

    def test_awp_cleanup_never_sees_shared_records(self):
        client = self._client()
        self._add_shared_text(client, "kb-note", "Curated fact.")

        response = client.post(
            "/awp", headers=MEMBER_H, json={"threadId": "session-1"}
        )
        self.assertEqual(response.status_code, 200)
        kwargs = self.handler_cls.call_args.kwargs

        # Simulate stream completion over the full record list: the
        # cleanup closure must filter out the shared records.
        captured: dict = {}
        with patch(
            "general_chat.server.app.mark_source_upload_deleted",
            side_effect=lambda record: captured.setdefault("records", []).append(record),
        ):
            kwargs["on_stream_complete"](kwargs["source_records"])
        self.assertNotIn("records", captured)
        # Shared source untouched afterwards.
        remaining = client.get("/admin/shared-sources", headers=ADMIN_H).json()["sources"]
        self.assertEqual([item["name"] for item in remaining], ["kb-note"])

    def test_env_pinned_branch_still_replaces(self):
        client = self._client()
        self._add_shared_text(client, "kb-note", "Curated fact.")
        client.post(
            "/chat/sources/session-1/text",
            headers=MEMBER_H,
            json={"name": "my-note", "text": "Member context."},
        )
        with patch.dict(
            environ,
            {
                "GENERAL_CHAT_SHARED_SOURCES_OWNER": "shared",
                "GENERAL_CHAT_SHARED_SOURCES_THREAD": "global-sources",
            },
            clear=False,
        ):
            response = client.post(
                "/awp", headers=MEMBER_H, json={"threadId": "session-1"}
            )
        self.assertEqual(response.status_code, 200)
        kwargs = self.handler_cls.call_args.kwargs
        self.assertEqual([r.name for r in kwargs["source_records"]], ["kb-note"])
        self.assertIsNone(kwargs["on_stream_complete"])


if __name__ == "__main__":
    unittest.main()
