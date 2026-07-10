"""End-to-end wrapper test: guest /awp turns are grounded on admin-curated sources."""

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

REPO_ROOT = Path(__file__).resolve().parents[1]
for example in ("general-chat", "controlled-source-chat"):
    src = REPO_ROOT / "examples" / example / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


pytestmark = pytest.mark.integration


class TestGuestChatUsesCuratedSources(unittest.TestCase):
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
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                    "CONTROLLED_CHAT_AUTH_SECRET": "test-secret",
                    "GENERAL_CHAT_SHARED_SOURCES_OWNER": "admin",
                    "GENERAL_CHAT_SHARED_SOURCES_THREAD": "controlled-sources",
                },
                clear=False,
            )
        )
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
        from controlled_source_chat.app import build_app

        return TestClient(build_app())

    def _login(self, client: TestClient, username: str, password: str) -> dict[str, str]:
        token = client.post(
            "/auth/login", json={"username": username, "password": password}
        ).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_guest_awp_grounds_on_admin_thread_without_cleanup(self):
        client = self._client()
        admin = self._login(client, "admin", "admin123")
        guest = self._login(client, "guest", "guest123")
        client.post(
            "/chat/sources/controlled-sources/text",
            headers=admin,
            json={"name": "kb-note", "text": "The Zylor Bridge opened in 1987."},
        )

        response = client.post(
            "/awp", headers=guest, json={"threadId": "guest-session-1"}
        )

        self.assertEqual(response.status_code, 200)
        kwargs = self.handler_cls.call_args.kwargs
        self.assertEqual([r.name for r in kwargs["source_records"]], ["kb-note"])
        self.assertEqual(kwargs["source_records"][0].session_id, "controlled-sources")
        self.assertIsNone(kwargs["on_stream_complete"])

    def test_awp_without_token_is_401(self):
        client = self._client()
        response = client.post("/awp", json={"threadId": "s1"})
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
