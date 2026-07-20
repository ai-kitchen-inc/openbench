"""Ownership checks for /uploads file serving (``_upload_access_allowed``)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat.server.app import (  # noqa: E402
    SHARED_SOURCES_OWNER,
    _stamp_upload_owner,
    _upload_access_allowed,
)
from general_chat.sources import SourceRecord, SourceStore  # noqa: E402

ALICE = "alice@example.com"
BOB = "bob@example.com"


class TestUploadAccessAllowed(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmpdir = Path(tmp.name)
        self.upload_dir = str(tmpdir / "uploads")
        Path(self.upload_dir).mkdir(parents=True)
        self.store = SourceStore(tmpdir / "storage")

    def _allowed(self, owner: str, file_id: str, role: str = "user") -> bool:
        return _upload_access_allowed(
            owner=owner,
            role=role,
            file_id=file_id,
            upload_dir=self.upload_dir,
            source_store=self.store,
        )

    def _add_record(self, owner: str, file_id: str) -> None:
        record = SourceRecord.create(
            session_id="s1",
            name="doc.pdf",
            kind="file",
            mime_type="application/pdf",
            size_bytes=1,
            url=f"/uploads/{file_id}/doc.pdf",
            text="",
            status="ready",
            metadata={"fileId": file_id},
            owner=owner,
        )
        self.store.for_owner(owner).upsert(record)

    def test_marker_owner_allowed(self) -> None:
        _stamp_upload_owner(self.upload_dir, "file-aaa", ALICE)
        self.assertTrue(self._allowed(ALICE, "file-aaa"))

    def test_marker_foreign_owner_denied(self) -> None:
        _stamp_upload_owner(self.upload_dir, "file-aaa", ALICE)
        self.assertFalse(self._allowed(BOB, "file-aaa"))

    def test_marker_admin_allowed(self) -> None:
        _stamp_upload_owner(self.upload_dir, "file-aaa", ALICE)
        self.assertTrue(self._allowed(BOB, "file-aaa", role="admin"))

    def test_marker_shared_allowed_for_everyone(self) -> None:
        _stamp_upload_owner(self.upload_dir, "file-shared", SHARED_SOURCES_OWNER)
        self.assertTrue(self._allowed(ALICE, "file-shared"))
        self.assertTrue(self._allowed(BOB, "file-shared"))

    def test_record_only_owner_allowed(self) -> None:
        self._add_record(ALICE, "file-legacy")
        self.assertTrue(self._allowed(ALICE, "file-legacy"))

    def test_record_only_foreign_owner_denied(self) -> None:
        self._add_record(ALICE, "file-legacy")
        self.assertFalse(self._allowed(BOB, "file-legacy"))

    def test_shared_record_allowed_for_everyone(self) -> None:
        self._add_record(SHARED_SOURCES_OWNER, "file-global")
        self.assertTrue(self._allowed(ALICE, "file-global"))
        self.assertTrue(self._allowed(BOB, "file-global"))

    def test_unclaimed_legacy_grandfathered(self) -> None:
        # No marker, no source record anywhere: pre-rollout transient
        # attachment — stays readable so existing chat histories keep working.
        self.assertTrue(self._allowed(ALICE, "file-unknown"))

    def test_marker_wins_over_missing_record(self) -> None:
        _stamp_upload_owner(self.upload_dir, "file-bbb", BOB)
        self.assertFalse(self._allowed(ALICE, "file-bbb"))
        self.assertTrue(self._allowed(BOB, "file-bbb"))


if __name__ == "__main__":
    unittest.main()
