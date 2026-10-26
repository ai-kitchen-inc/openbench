"""Tests for auto-ingesting Google Drive links pasted in chat messages."""

from __future__ import annotations

import sys
import uuid
from contextlib import ExitStack
from os import environ
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import unittest

from fastapi.testclient import TestClient

from openbench.core.abstractions import Agent, ExecutionContext, ExecutionResult

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.google_drive import (  # noqa: E402
    MSG_FOLDER_NEEDS_AUTH,
    DriveAccessError,
    DriveLink,
)
from general_chat.sources import SourceRecord  # noqa: E402

pytestmark = pytest.mark.integration

FILE_ID_A = "1AbCdEfGhIjKlMnOpQrStUv"
FILE_ID_B = "1ZyXwVuTsRqPoNmLkJiHgFe"
FILE_ID_C = "1CcCcCcCcCcCcCcCcCcCcCc"
FILE_ID_D = "1DdDdDdDdDdDdDdDdDdDdDd"


def _drive_link(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"


class MockAgent(Agent):
    def __init__(self):
        self.context: ExecutionContext | None = None

    @property
    def agent_type(self) -> str:
        return "mock"

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        self.context = context
        return ExecutionResult(output=context.goal, status="success", metadata={})

    def estimate_cost(self, context: ExecutionContext) -> float:
        return 0.0


def _fake_drive_source_record(
    *, session_id, link, file_store, parser, max_bytes, credentials=None
):
    record = SourceRecord.create(
        session_id=session_id,
        name=f"drive-{link.file_id}.txt",
        kind="text",
        mime_type="text/plain",
        size_bytes=10,
        url=None,
        text="drive file text",
        metadata={
            "driveFileId": link.file_id,
            "driveUrl": link.original_url,
            "driveAccess": "public",
        },
    )
    return record, None


class TestChatDriveLinkAutoIngest(unittest.TestCase):
    def _build_test_client(self) -> TestClient:
        tmpdir = Path("tests/.tmp") / f"drive-chat-{uuid.uuid4().hex}"
        tmpdir.mkdir(parents=True, exist_ok=True)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            patch.dict(
                environ,
                {
                    "GENERAL_CHAT_STORAGE_ROOT": str(tmpdir / "storage"),
                    "GENERAL_CHAT_UPLOAD_DIR": str(tmpdir / "uploads"),
                    "GENERAL_CHAT_DOWNLOAD_DIR": str(tmpdir / "downloads"),
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                },
                clear=False,
            )
        )
        environ.pop("GENERAL_CHAT_FIREBASE_PROJECT_ID", None)
        environ.pop("GENERAL_CHAT_SHARED_SOURCES_OWNER", None)
        environ.pop("GENERAL_CHAT_SHARED_SOURCES_THREAD", None)
        stack.enter_context(
            patch("general_chat.server.app.create_agent", return_value=MockAgent())
        )
        from general_chat.server.app import create_app

        return TestClient(create_app())

    def _post_turn(self, client: TestClient, session_id: str, content: str, **headers):
        return client.post(
            "/awp",
            json={
                "threadId": session_id,
                "messages": [{"role": "user", "content": content}],
                "forwardedProps": {"sessionId": session_id},
            },
            headers={"accept": "text/event-stream", **headers},
        )

    def _sources(self, client: TestClient, session_id: str) -> list[dict]:
        return client.get(f"/chat/sources/{session_id}").json()

    def test_drive_link_in_message_creates_session_source(self):
        client = self._build_test_client()
        with patch(
            "general_chat.server.app.drive_source_record",
            side_effect=_fake_drive_source_record,
        ) as mock_ingest:
            response = self._post_turn(
                client, "s-drive", f"Tolong ringkas {_drive_link(FILE_ID_A)}"
            )
        self.assertEqual(response.status_code, 200)
        mock_ingest.assert_called_once()
        sources = self._sources(client, "s-drive")
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["metadata"]["driveFileId"], FILE_ID_A)

    def test_same_link_not_reingested_next_turn(self):
        client = self._build_test_client()
        message = f"Baca {_drive_link(FILE_ID_A)}"
        with patch(
            "general_chat.server.app.drive_source_record",
            side_effect=_fake_drive_source_record,
        ) as mock_ingest:
            self._post_turn(client, "s-dedup", message)
            self._post_turn(client, "s-dedup", message)
        self.assertEqual(mock_ingest.call_count, 1)
        self.assertEqual(len(self._sources(client, "s-dedup")), 1)

    def test_non_drive_urls_ignored(self):
        client = self._build_test_client()
        with patch(
            "general_chat.server.app.drive_source_record",
            side_effect=_fake_drive_source_record,
        ) as mock_ingest:
            response = self._post_turn(
                client, "s-web", "Ringkas https://example.com/artikel dong"
            )
        self.assertEqual(response.status_code, 200)
        mock_ingest.assert_not_called()
        self.assertEqual(self._sources(client, "s-web"), [])

    def test_unreadable_folder_link_produces_failed_record(self):
        client = self._build_test_client()
        folder = f"https://drive.google.com/drive/folders/{FILE_ID_A}"
        with (
            patch(
                "general_chat.server.app.list_drive_folder",
                side_effect=DriveAccessError(MSG_FOLDER_NEEDS_AUTH, needs_auth=True),
            ),
            patch(
                "general_chat.server.app.drive_source_record",
                side_effect=_fake_drive_source_record,
            ) as mock_ingest,
        ):
            self._post_turn(client, "s-folder", f"Lihat {folder}")
        mock_ingest.assert_not_called()
        sources = self._sources(client, "s-folder")
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["status"], "failed")
        self.assertIn("Hubungkan Google Drive", sources[0]["error"])

    def test_folder_link_in_chat_ingests_listed_files(self):
        client = self._build_test_client()
        folder = f"https://drive.google.com/drive/folders/{FILE_ID_C}"
        children = [
            DriveLink(
                file_id=fid,
                doc_kind="file",
                resource_key=None,
                original_url=f"https://drive.google.com/file/d/{fid}/view",
            )
            for fid in (FILE_ID_A, FILE_ID_B)
        ]
        with (
            patch("general_chat.server.app.list_drive_folder", return_value=children),
            patch(
                "general_chat.server.app.drive_source_record",
                side_effect=_fake_drive_source_record,
            ) as mock_ingest,
        ):
            self._post_turn(client, "s-folder-ok", f"Baca semua di {folder}")
        self.assertEqual(mock_ingest.call_count, 2)
        sources = self._sources(client, "s-folder-ok")
        self.assertEqual(
            {s["metadata"]["driveFileId"] for s in sources}, {FILE_ID_A, FILE_ID_B}
        )

    def test_url_endpoint_folder_returns_multi_record_payload(self):
        client = self._build_test_client()
        folder = f"https://drive.google.com/drive/folders/{FILE_ID_C}"
        children = [
            DriveLink(
                file_id=fid,
                doc_kind="file",
                resource_key=None,
                original_url=f"https://drive.google.com/file/d/{fid}/view",
            )
            for fid in (FILE_ID_A, FILE_ID_B)
        ]
        with (
            patch("general_chat.server.app.list_drive_folder", return_value=children),
            patch(
                "general_chat.server.app.drive_source_record",
                side_effect=_fake_drive_source_record,
            ),
        ):
            response = client.post(
                "/chat/sources/s-folder-api/url", json={"url": folder}
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["folder"])
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(self._sources(client, "s-folder-api")), 2)

    def test_capability_off_skips_ingest(self):
        client = self._build_test_client()
        response = client.put(
            "/admin/capabilities",
            json={"roles": {"user": {"session_sources": False}}},
        )
        self.assertEqual(response.status_code, 200)
        with patch(
            "general_chat.server.app.drive_source_record",
            side_effect=_fake_drive_source_record,
        ) as mock_ingest:
            response = self._post_turn(
                client,
                "s-gated",
                f"Baca {_drive_link(FILE_ID_A)}",
                **{"X-Local-Role": "user"},
            )
        self.assertEqual(response.status_code, 200)
        mock_ingest.assert_not_called()

    def test_multiple_links_capped_at_three(self):
        client = self._build_test_client()
        message = " dan ".join(
            _drive_link(fid) for fid in (FILE_ID_A, FILE_ID_B, FILE_ID_C, FILE_ID_D)
        )
        with patch(
            "general_chat.server.app.drive_source_record",
            side_effect=_fake_drive_source_record,
        ) as mock_ingest:
            self._post_turn(client, "s-many", message)
        self.assertEqual(mock_ingest.call_count, 3)
        self.assertEqual(len(self._sources(client, "s-many")), 3)

    def test_missing_session_id_skips_ingest(self):
        client = self._build_test_client()
        with patch(
            "general_chat.server.app.drive_source_record",
            side_effect=_fake_drive_source_record,
        ) as mock_ingest:
            response = client.post(
                "/awp",
                json={
                    "messages": [
                        {"role": "user", "content": f"Baca {_drive_link(FILE_ID_A)}"}
                    ]
                },
                headers={"accept": "text/event-stream"},
            )
        self.assertEqual(response.status_code, 200)
        mock_ingest.assert_not_called()


if __name__ == "__main__":
    unittest.main()
