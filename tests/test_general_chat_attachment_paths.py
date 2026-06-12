"""Tests for General Chat image attachment paths used by MCP tools."""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import ExitStack
from os import environ
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from openbench.chat.files import StoredFile
from openbench.chat.session import Attachment

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))


class FakeGCSFileStore:
    def __init__(self, root: Path):
        self.root = root
        self.stored: StoredFile | None = None

    def store(self, filename: str, content: bytes, mime_type: str):
        safe_name = Path(filename).name
        path = self.root / "cache" / safe_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        self.stored = StoredFile(
            id="file-image",
            name=safe_name,
            path=str(path),
            mime_type=mime_type,
            size_bytes=len(content),
            stored_at="2026-06-11T00:00:00+00:00",
            web_view_link=f"gs://test-bucket/uploads/default/session-1/file-image/{safe_name}",
        )
        return self.stored


class FakeStorageBackend:
    def __init__(self, file_store: FakeGCSFileStore):
        self._file_store = file_store

    def file_store(self):
        return self._file_store

    def session_store(self):
        return SimpleNamespace(load=lambda _id: None, save=lambda _session: None)

    def memory_store(self):
        return None


class TestGeneralChatAttachmentPaths(unittest.TestCase):
    def test_attachment_to_dict_serializes_path(self):
        attachment = Attachment(
            id="file-image",
            type="image",
            name="cats.png",
            url="/uploads/file-image/cats.png",
            mime_type="image/png",
            path="/general-chat/uploads/file-image/cats.png",
        )

        self.assertEqual(
            attachment.to_dict()["path"],
            "/general-chat/uploads/file-image/cats.png",
        )

    def test_chat_attachment_upload_returns_mcp_path_and_mirrors_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            fake_file_store = FakeGCSFileStore(tmpdir)
            fake_storage = FakeStorageBackend(fake_file_store)
            upload_dir = tmpdir / "mcp-uploads"
            agent = Mock()
            agent.model = "mock-model"
            agent._persona = None
            agent._skill_registry = None

            with ExitStack() as stack:
                stack.enter_context(
                    patch.dict(
                        environ,
                        {
                            "GENERAL_CHAT_GCP_BUCKET": "test-bucket",
                            "GENERAL_CHAT_STORAGE_ROOT": str(tmpdir / "storage"),
                            "GENERAL_CHAT_UPLOAD_DIR": str(upload_dir),
                            "GENERAL_CHAT_DOWNLOAD_DIR": str(tmpdir / "downloads"),
                            "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
                        },
                        clear=False,
                    )
                )
                stack.enter_context(
                    patch("general_chat.server.app.create_agent", return_value=agent)
                )
                stack.enter_context(
                    patch("general_chat.server.app._build_storage_backend", return_value=fake_storage)
                )
                from general_chat.server.app import create_app

                client = TestClient(create_app())
                response = client.post(
                    "/chat/attachments/upload",
                    files={"file": ("cats.png", b"png-bytes", "image/png")},
                    data={"sessionId": "session-1"},
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["type"], "image")
            self.assertEqual(payload["path"], "/general-chat/uploads/file-image/cats.png")
            self.assertIn("sam_segmentation.count_objects_with_sam3", payload["extractedText"])
            self.assertIn("/general-chat/uploads/file-image/cats.png", payload["extractedText"])
            self.assertEqual(
                (upload_dir / "file-image" / "cats.png").read_bytes(),
                b"png-bytes",
            )

    def test_enrich_draft_attachments_derives_mcp_path_from_upload_url(self):
        from general_chat.server.handler import _enrich_draft_attachments

        enriched = _enrich_draft_attachments(
            [
                Attachment(
                    id="file-image",
                    type="image",
                    name="cats.png",
                    url="/uploads/file-image/cats.png",
                    mime_type="image/png",
                    size_bytes=9,
                )
            ]
        )

        self.assertEqual(len(enriched), 1)
        self.assertEqual(enriched[0].path, "/general-chat/uploads/file-image/cats.png")
        self.assertIn("image_path=\"/general-chat/uploads/file-image/cats.png\"", enriched[0].extracted_text)


if __name__ == "__main__":
    unittest.main()
