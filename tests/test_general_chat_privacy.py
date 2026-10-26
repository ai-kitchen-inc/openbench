"""Tests for admin-managed privacy settings and PII redaction."""

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

from general_chat.pii import redact_pii  # noqa: E402
from general_chat.privacy import (  # noqa: E402
    PrivacySettingsCache,
    default_privacy_settings,
    invalid_privacy_values,
    resolve_privacy_settings,
)

pytestmark = pytest.mark.integration


class _MemoryStore:
    def __init__(self):
        self.data: dict = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, *, updated_by=""):
        self.data[key] = value


class TestPrivacyResolution(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(
            default_privacy_settings(),
            {"retention_days": 0, "pii_redaction": False},
        )

    def test_resolve_merges_partial_and_drops_unknown(self):
        resolved = resolve_privacy_settings({"retention_days": 30, "made_up": 1})
        self.assertEqual(resolved["retention_days"], 30)
        self.assertFalse(resolved["pii_redaction"])
        self.assertNotIn("made_up", resolved)

    def test_resolve_rejects_bad_types(self):
        self.assertEqual(
            resolve_privacy_settings({"retention_days": "30", "pii_redaction": "yes"}),
            default_privacy_settings(),
        )
        # bool is an int subclass — must not sneak into retention_days.
        self.assertEqual(
            resolve_privacy_settings({"retention_days": True})["retention_days"], 0
        )
        self.assertEqual(
            resolve_privacy_settings({"retention_days": -1})["retention_days"], 0
        )

    def test_invalid_values(self):
        self.assertEqual(invalid_privacy_values({"retention_days": -5}), {"retention_days": -5})
        self.assertEqual(invalid_privacy_values({"pii_redaction": "x"}), {"pii_redaction": "x"})
        self.assertEqual(invalid_privacy_values({"retention_days": 30}), {})
        self.assertEqual(invalid_privacy_values("nope"), {})

    def test_cache_update_persists_and_swaps(self):
        store = _MemoryStore()
        cache = PrivacySettingsCache(store)
        merged = cache.update({"retention_days": 14}, updated_by="admin@x.co")
        self.assertEqual(merged["retention_days"], 14)
        self.assertEqual(cache.value["retention_days"], 14)
        self.assertEqual(store.data["privacy"]["retention_days"], 14)
        # A second cache built over the same store resolves the saved value.
        self.assertEqual(PrivacySettingsCache(store).value["retention_days"], 14)


class TestRedactPii(unittest.TestCase):
    def test_nik_sixteen_digits(self):
        redacted, changed = redact_pii("NIK saya 3174012345678901 ya")
        self.assertTrue(changed)
        self.assertEqual(redacted, "NIK saya ****8901 ya")

    def test_card_with_spaces_and_dashes(self):
        redacted, _ = redact_pii("kartu 4111 1111 1111 1234 dan 4111-1111-1111-5678")
        self.assertNotIn("4111", redacted)
        self.assertIn("****1234", redacted)
        self.assertIn("****5678", redacted)

    def test_npwp_formatted(self):
        redacted, changed = redact_pii("NPWP: 01.234.567.8-901.234")
        self.assertTrue(changed)
        self.assertIn("NPWP ****234", redacted)
        self.assertNotIn("01.234.567", redacted)

    def test_email(self):
        redacted, changed = redact_pii("hubungi budi.s@contoso.co.id segera")
        self.assertTrue(changed)
        self.assertEqual(redacted, "hubungi ****@contoso.co.id segera")

    def test_phone_variants(self):
        for phone in ("081234567890", "+6281234567890", "6281234567890"):
            redacted, changed = redact_pii(f"hp {phone} ok")
            self.assertTrue(changed, phone)
            self.assertEqual(redacted, "hp ****7890 ok", phone)

    def test_short_numbers_untouched(self):
        for text in ("tahun 2026", "invoice 123456789012", "qty 1500"):
            redacted, changed = redact_pii(text)
            self.assertFalse(changed, text)
            self.assertEqual(redacted, text)

    def test_clean_text_flags_unchanged(self):
        redacted, changed = redact_pii("laporan penjualan kuartal dua")
        self.assertFalse(changed)
        self.assertEqual(redacted, "laporan penjualan kuartal dua")

    def test_empty(self):
        self.assertEqual(redact_pii(""), ("", False))


class TestHandlerRedaction(unittest.TestCase):
    def _handler(self, redactor):
        from general_chat.server.handler import GeneralChatHandler

        engine = Mock()
        engine.agent = Mock()
        return GeneralChatHandler(
            engine=engine,
            memory_store=Mock(),
            redactor=redactor,
        )

    def _extract(self, handler, content, attachments):
        from general_chat.server import handler as handler_module

        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    handler_module.AGUIHandler,
                    "_extract_content",
                    return_value=(content, attachments),
                )
            )
            stack.enter_context(
                patch.object(
                    handler_module,
                    "_enrich_draft_attachments",
                    side_effect=lambda drafts: drafts or [],
                )
            )
            stack.enter_context(
                patch.object(
                    handler_module,
                    "_augment_with_visual_observations",
                    side_effect=lambda agent, content, attachments: attachments,
                )
            )
            stack.enter_context(
                patch.object(
                    handler_module,
                    "_augment_with_export_instruction",
                    side_effect=lambda agent, content, attachments: attachments,
                )
            )
            return handler._extract_content({"messages": []})

    def test_redacts_content_and_draft_text(self):
        handler = self._handler(redact_pii)
        attachment = Mock()
        attachment.extracted_text = "NIK 3174012345678901"
        content, attachments = self._extract(handler, "email a@b.co", [attachment])
        self.assertEqual(content, "email ****@b.co")
        self.assertEqual(attachments[0].extracted_text, "NIK ****8901")

    def test_no_redactor_leaves_text_alone(self):
        handler = self._handler(None)
        content, _ = self._extract(handler, "email a@b.co", None)
        self.assertEqual(content, "email a@b.co")


class TestPrivacyEndpoints(unittest.TestCase):
    """Local-dev client (auth disabled → requester is admin by default)."""

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
                    "GENERAL_CHAT_MEMORY_DB": str(tmpdir / "memory.db"),
                    "OPENBENCH_AUTH_DISABLED": "1",
                    "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
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

    def test_get_returns_defaults(self):
        client = self._client()
        response = client.get("/admin/privacy")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"retentionDays": 0, "piiRedaction": False})

    def test_put_partial_merge_persists(self):
        client = self._client()
        response = client.put("/admin/privacy", json={"piiRedaction": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"retentionDays": 0, "piiRedaction": True})
        again = client.get("/admin/privacy").json()
        self.assertTrue(again["piiRedaction"])
        self.assertEqual(again["retentionDays"], 0)

    def test_put_rejects_invalid_values(self):
        client = self._client()
        for payload in ({"retentionDays": -1}, {"retentionDays": "x"}, {"piiRedaction": "y"}):
            response = client.put("/admin/privacy", json=payload)
            self.assertEqual(response.status_code, 400, payload)
            self.assertIn("privasi", response.json()["detail"])

    def test_non_admin_forbidden(self):
        client = self._client()
        headers = {"X-Local-Role": "user"}
        self.assertEqual(client.get("/admin/privacy", headers=headers).status_code, 403)
        self.assertEqual(
            client.put("/admin/privacy", json={}, headers=headers).status_code, 403
        )
        self.assertEqual(
            client.post("/admin/privacy/sweep", headers=headers).status_code, 403
        )


if __name__ == "__main__":
    unittest.main()
