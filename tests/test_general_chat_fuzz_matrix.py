"""Fuzzy bug matrix for General Chat — the P0 "release minimum" checklist.

Each test carries the ID from the Fuzzy Bug Testing General Chat document
(AUTH-*, CHAT-*, UP-*, SRC-*, ADM-*, AGT-*, EMB-*, FILE-*). Everything runs
against the FastAPI app via TestClient with Firebase, the LLM, Docling and
the network mocked, so the suite is fast and deterministic.
"""

from __future__ import annotations

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

from openbench.integrations.firebase_auth import FirebaseUser

GENERAL_CHAT_SRC = Path(__file__).resolve().parents[1] / "examples" / "general-chat" / "src"
if str(GENERAL_CHAT_SRC) not in sys.path:
    sys.path.insert(0, str(GENERAL_CHAT_SRC))

from general_chat import extractor as extractor_mod  # noqa: E402

pytestmark = pytest.mark.integration

ADMIN = FirebaseUser(uid="uid-admin", email="boss@example.com")
ALICE = FirebaseUser(uid="uid-a", email="alice@example.com")
BOB = FirebaseUser(uid="uid-b", email="bob@example.com")

ADMIN_H = {"Authorization": "Bearer token-admin"}
A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}

FUZZ_STRINGS = [
    "",
    " ",
    "\t\n",
    "x" * 10_000,
    "Halo مرحبا こんにちは 🚀 ‍ ‏",
    "%?#&=../\\%00",
    "<script>alert(1)</script><img src=x onerror=alert(1)>",
    "' OR 1=1 --; DROP TABLE sessions;",
]


class _NoDocling:
    """Stand-in converter: OCR finds nothing, never loads models."""

    def convert(self, _path):
        doc = Mock()
        doc.export_to_markdown.return_value = ""
        return Mock(document=doc)


class _ClientMixin:
    def _env(self, stack: ExitStack, extra: dict[str, str]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmpdir = Path(tmp.name)
        base = {
            "GENERAL_CHAT_STORAGE_ROOT": str(tmpdir / "storage"),
            "GENERAL_CHAT_UPLOAD_DIR": str(tmpdir / "uploads"),
            "GENERAL_CHAT_DOWNLOAD_DIR": str(tmpdir / "downloads"),
            "OPENBENCH_PROFILE_DIR": str(tmpdir / "profiles"),
            "GENERAL_CHAT_MULTIPART_UPLOAD_MAX_BYTES": "1024",
        }
        base.update(extra)
        stack.enter_context(patch.dict(environ, base, clear=False))
        for name in (
            "GENERAL_CHAT_GCP_BUCKET",
            "GENERAL_CHAT_ARCHIVE_BUCKET",
            "GENERAL_CHAT_SOURCE_INDEX_ENABLED",
            "OPENBENCH_DOWNLOAD_SECRET",
        ):
            if name not in extra:
                environ.pop(name, None)
        return tmpdir

    def _common_patches(self, stack: ExitStack) -> None:
        agent = Mock()
        agent.model = "mock-model"
        agent._persona = None
        agent._skill_registry = None
        stack.enter_context(patch("general_chat.server.app.create_agent", return_value=agent))
        stack.enter_context(
            patch.object(extractor_mod, "_get_converter", return_value=_NoDocling())
        )

    def _firebase_client(self, extra_env: dict[str, str] | None = None) -> TestClient:
        users = {"token-admin": ADMIN, "token-a": ALICE, "token-b": BOB}
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.tmpdir = self._env(
            stack,
            {
                "GENERAL_CHAT_FIREBASE_PROJECT_ID": "demo-project",
                "GENERAL_CHAT_BOOTSTRAP_ADMIN": ADMIN.email or "",
                "GENERAL_CHAT_ALLOWED_EMAILS": ",".join(
                    sorted({(u.email or "").lower() for u in users.values()})
                ),
                **(extra_env or {}),
            },
        )
        environ.pop("OPENBENCH_AUTH_DISABLED", None)
        self._common_patches(stack)

        verifier = Mock()

        def _verify(token, **_kw):
            from openbench.integrations.firebase_auth import InvalidTokenError

            try:
                return users[token]
            except KeyError:
                raise InvalidTokenError("bad token") from None

        verifier.verify.side_effect = _verify
        verifier_cls = stack.enter_context(patch("general_chat.server.auth.FirebaseIDVerifier"))
        verifier_cls.return_value = verifier

        from general_chat.server import auth as auth_module
        from general_chat.server.app import create_app

        auth_module._verifier.cache_clear()
        self.addCleanup(auth_module._verifier.cache_clear)
        return TestClient(create_app())

    def _local_client(self) -> TestClient:
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.tmpdir = self._env(stack, {"OPENBENCH_AUTH_DISABLED": "1"})
        environ.pop("GENERAL_CHAT_FIREBASE_PROJECT_ID", None)
        self._common_patches(stack)
        from general_chat.server.app import create_app

        return TestClient(create_app())


def _upload(client, headers, name, content, mime, session="s1"):
    return client.post(
        "/chat/upload",
        headers=headers,
        files={"file": (name, io.BytesIO(content), mime)},
        data={"sessionId": session},
    )


# ── 5.1 Auth and authorization ───────────────────────────────────────────


class TestAuth(_ClientMixin, unittest.TestCase):
    def test_AUTH_001_unknown_google_account_is_403(self):
        client = self._firebase_client()
        stranger = FirebaseUser(uid="uid-x", email="stranger@example.com")
        # Token verifies but the account is not in the user store.
        with patch("general_chat.server.auth._verifier") as verifier:
            verifier.return_value.verify.return_value = stranger
            response = client.get("/account/me", headers={"Authorization": "Bearer t"})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Traceback", response.text)

    def test_AUTH_002_token_fuzz_never_leaks_data(self):
        client = self._firebase_client()
        for header in (
            {},
            {"Authorization": ""},
            {"Authorization": "Bearer"},
            {"Authorization": "Bearer "},
            {"Authorization": "Bearer random-garbage"},
            {"Authorization": "Basic dXNlcjpwYXNz"},
            {"Authorization": "Bearer " + "A" * 5000},
        ):
            for path in ("/sessions", "/account/me", "/chat/sources/s1", "/admin/users"):
                response = client.get(path, headers=header)
                self.assertIn(response.status_code, (401, 403), (header, path, response.text))
                self.assertNotIn("Traceback", response.text)

    def test_AUTH_003_local_role_header_ignored_when_firebase_active(self):
        client = self._firebase_client()
        for value in ("admin", "ADMIN", "user", "invalid", " admin "):
            response = client.get("/admin/users", headers={**A, "X-Local-Role": value})
            self.assertEqual(response.status_code, 403, value)
            me = client.get("/account/me", headers={**A, "X-Local-Role": value}).json()
            self.assertEqual(me["role"], "user", value)

    def test_AUTH_004_user_without_attachments_capability_gets_403(self):
        client = self._firebase_client()
        caps = client.get("/admin/capabilities", headers=ADMIN_H).json()
        caps["roles"]["user"]["attachments"] = False
        put = client.put("/admin/capabilities", headers=ADMIN_H, json=caps)
        self.assertEqual(put.status_code, 200, put.text)
        response = _upload(client, A, "note.txt", b"hello", "text/plain")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get("capability"), "attachments")
        # Admin keeps the capability regardless of the user-role flag.
        self.assertEqual(
            _upload(client, ADMIN_H, "note.txt", b"hello", "text/plain").status_code, 200
        )

    def test_AUTH_006_user_role_cannot_touch_admin_routes(self):
        client = self._firebase_client()
        before = client.get("/admin/users", headers=ADMIN_H).json()
        attempts = [
            ("GET", "/admin/users", None),
            ("POST", "/admin/users", {"email": "evil@example.com", "role": "admin"}),
            ("DELETE", f"/admin/users/{ADMIN.email}", None),
            ("PUT", "/admin/capabilities", {"roles": {"user": {"attachments": False}}}),
            ("GET", "/admin/audit", None),
            ("POST", "/admin/privacy/sweep", {}),
            ("PUT", "/admin/persona", {"soul": "pwned"}),
            ("GET", "/admin/agents", None),
            ("POST", "/admin/agents", {"name": "x"}),
            ("GET", "/admin/shared-sources", None),
            ("POST", "/admin/shared-sources/text", {"name": "x", "text": "y"}),
            ("GET", "/admin/../admin/users", None),
            ("GET", "/ADMIN/users", None),
        ]
        for method, path, body in attempts:
            response = client.request(method, path, headers=A, json=body)
            self.assertIn(response.status_code, (403, 404), (method, path, response.text))
        after = client.get("/admin/users", headers=ADMIN_H).json()
        self.assertEqual(before, after)
        self.assertTrue(
            client.get("/admin/capabilities", headers=ADMIN_H).json()["roles"]["user"][
                "attachments"
            ]
        )

    def test_AUTH_007_account_me_in_local_mode_reflects_header_role(self):
        client = self._local_client()
        admin = client.get("/account/me").json()
        self.assertEqual(admin["role"], "admin")
        user = client.get("/account/me", headers={"X-Local-Role": "user"}).json()
        self.assertEqual(user["role"], "user")
        self.assertIn("capabilities", user)
        self.assertFalse(user["capabilities"]["mcp_management"])
        weird = client.get("/account/me", headers={"X-Local-Role": "root"}).json()
        self.assertEqual(weird["role"], "admin")

    def test_AUTH_006b_local_user_role_blocked_from_admin(self):
        client = self._local_client()
        response = client.get("/admin/users", headers={"X-Local-Role": "user"})
        self.assertEqual(response.status_code, 403)


# ── 5.2 Chat streaming and session ───────────────────────────────────────


class TestChatSessions(_ClientMixin, unittest.TestCase):
    def _seed(self, owner: str, session_id: str) -> None:
        from openbench.chat.session import ChatSession
        from openbench.chat.stores.sqlite import SQLiteSessionStore

        store = SQLiteSessionStore(str(self.tmpdir / "storage" / "sessions.db"), owner=owner)
        store.save(ChatSession(session_id=session_id, title="Seeded"))

    def test_CHAT_001_awp_payload_fuzz_never_500s(self):
        client = self._firebase_client()
        payloads = [
            {},
            [],
            "string",
            {"messages": []},
            {"messages": "nope"},
            {"messages": [{"role": "user", "content": ""}]},
            {"messages": [{"role": "user", "content": "   "}]},
            {"messages": [{"role": "user"}]},
            {"messages": [{"role": "user", "content": "x" * 300_000}]},
            {"threadId": "../../etc", "messages": [{"role": "user", "content": "hi"}]},
        ]
        for payload in payloads:
            response = client.post("/awp", headers=A, json=payload)
            self.assertNotEqual(
                response.status_code,
                500,
                (
                    payload if not isinstance(payload, dict) else list(payload)[:2],
                    response.text[:300],
                ),
            )
            self.assertNotIn("Traceback", response.text)
        # Malformed JSON body.
        response = client.post(
            "/awp", headers={**A, "Content-Type": "application/json"}, content=b"{not json"
        )
        self.assertNotEqual(response.status_code, 500, response.text[:300])

    def test_CHAT_003_foreign_session_is_404_without_metadata(self):
        client = self._firebase_client()
        self._seed(ALICE.email, "sess-alice")
        self.assertEqual(client.get("/sessions/sess-alice", headers=A).status_code, 200)
        response = client.get("/sessions/sess-alice", headers=B)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Seeded", response.text)
        self.assertEqual(
            client.patch("/sessions/sess-alice", headers=B, json={"title": "pwn"}).status_code, 404
        )
        self.assertEqual(client.get("/sessions/sess-alice", headers=A).json()["title"], "Seeded")

    def test_CHAT_005_rename_fuzz_sanitizes_to_64_chars(self):
        client = self._firebase_client()
        self._seed(ALICE.email, "sess-alice")
        for title in FUZZ_STRINGS:
            response = client.patch("/sessions/sess-alice", headers=A, json={"title": title})
            if not title.strip():
                self.assertEqual(response.status_code, 400, repr(title))
                continue
            self.assertEqual(response.status_code, 200, repr(title))
            stored = client.get("/sessions/sess-alice", headers=A).json()["title"]
            self.assertLessEqual(len(stored), 64, repr(title))
            self.assertNotIn("\n", stored)
        # Non-string / missing title.
        for body in ({}, {"title": None}, {"title": 123}, {"title": ["x"]}, {"title": {"a": 1}}):
            response = client.patch("/sessions/sess-alice", headers=A, json=body)
            self.assertIn(response.status_code, (200, 400), (body, response.text))
            self.assertNotEqual(response.status_code, 500)

    def test_CHAT_006_double_delete_is_idempotent(self):
        client = self._firebase_client()
        self._seed(ALICE.email, "sess-alice")
        self.assertEqual(client.delete("/sessions/sess-alice", headers=A).status_code, 200)
        self.assertEqual(client.delete("/sessions/sess-alice", headers=A).status_code, 200)
        self.assertEqual(client.get("/sessions/sess-alice", headers=A).status_code, 404)

    def test_CHAT_007_action_fuzz_is_safe(self):
        client = self._firebase_client()
        payloads = [
            {},
            {"name": "unknown_action", "surfaceId": "s"},
            {"name": "mcp_permission_decision", "surfaceId": "s", "context": "notadict"},
            {
                "name": "mcp_permission_decision",
                "surfaceId": "s",
                "context": {"requestId": "../x", "decision": "approve"},
            },
            {"name": 123},
            [],
        ]
        for payload in payloads:
            response = client.post("/chat/action", headers=A, json=payload)
            self.assertNotEqual(response.status_code, 500, (payload, response.text[:300]))
            self.assertNotIn("Traceback", response.text)


# ── 5.3 Upload and attachment ────────────────────────────────────────────


class TestUploads(_ClientMixin, unittest.TestCase):
    def test_UP_001_multipart_size_boundaries(self):
        client = self._firebase_client()
        limit = 1024
        below = _upload(client, A, "a.txt", b"a" * (limit - 1), "text/plain")
        self.assertEqual(below.status_code, 200, below.text)
        exact = _upload(client, A, "b.txt", b"b" * limit, "text/plain")
        self.assertEqual(exact.status_code, 200, exact.text)
        above = _upload(client, A, "c.txt", b"c" * (limit + 1), "text/plain")
        self.assertEqual(above.status_code, 413, above.text)
        # Nothing orphaned: only two sources exist.
        self.assertEqual(len(client.get("/chat/sources/s1", headers=A).json()), 2)

    def test_UP_002_direct_upload_without_gcs_is_503(self):
        client = self._firebase_client()
        response = client.post(
            "/chat/uploads/initiate",
            headers=A,
            json={"filename": "big.pdf", "sizeBytes": 50 * 1024 * 1024, "sessionId": "s1"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(client.get("/chat/sources/s1", headers=A).json(), [])
        self.assertEqual(
            client.post("/chat/uploads/complete", headers=A, json={"fileId": "x"}).status_code,
            503,
        )

    def test_UP_003_mime_mismatch_fails_safely(self):
        client = self._firebase_client()
        html = b"<html><script>alert(1)</script><body>hi</body></html>"
        cases = [
            ("evil.pdf", html, "application/pdf"),
            ("evil.jpg", b"not an image", "image/jpeg"),
            ("evil.txt", html, ""),
            ("evil.pdf", html, "application/octet-stream"),
            ("evil.png", html, "text/html"),
        ]
        for name, content, mime in cases:
            response = _upload(client, A, name, content, mime)
            self.assertIn(response.status_code, (200, 400), (name, mime, response.text[:300]))
            if response.status_code == 200:
                body = response.json()
                self.assertIn(body["status"], ("ready", "failed"))
                self.assertNotIn("Traceback", response.text)

    def test_UP_004_path_traversal_filenames_are_contained(self):
        client = self._firebase_client()
        upload_root = Path(self.tmpdir / "uploads").resolve()
        for name in (
            "../../secret.txt",
            "a/../b.txt",
            "..\\..\\win.txt",
            "%2e%2e%2fenc.txt",
            "CON.txt",
            "NUL",
            "noext",
            "x" * 255 + ".txt",
            "weird\nname.txt",
        ):
            response = _upload(client, A, name, b"payload", "text/plain")
            self.assertNotEqual(response.status_code, 500, (name, response.text[:300]))
            if response.status_code != 200:
                continue
            body = response.json()
            url = body.get("url") or ""
            self.assertTrue(url.startswith("/uploads/"), (name, url))
            self.assertNotIn("..", url.split("/uploads/", 1)[1].split("/", 1)[0])
        # Every file written lives under the upload root.
        for path in self.tmpdir.rglob("*"):
            if path.is_file() and "uploads" in path.parts:
                path.resolve().relative_to(upload_root)
        # Nothing escaped above the temp dir.
        self.assertFalse((self.tmpdir.parent / "secret.txt").exists())

    def test_UP_005_foreign_upload_is_404(self):
        client = self._firebase_client()
        uploaded = _upload(client, A, "private.txt", b"alice secret", "text/plain").json()
        url = uploaded["url"]
        self.assertEqual(client.get(url, headers=A).status_code, 200)
        self.assertEqual(client.get(url, headers=A).text, "alice secret")
        for headers in (B, {}):
            response = client.get(url, headers=headers)
            self.assertIn(response.status_code, (401, 404), headers)
            self.assertNotIn("alice secret", response.text)
        self.assertEqual(client.head(url, headers=B).status_code, 404)
        # Admin may read it.
        self.assertEqual(client.get(url, headers=ADMIN_H).status_code, 200)

    def test_UP_006_batch_mixed_valid_and_broken(self):
        client = self._firebase_client()
        results = [
            _upload(client, A, "ok1.txt", b"first", "text/plain").json(),
            _upload(client, A, "broken.pdf", b"garbage", "application/pdf").json(),
            _upload(client, A, "ok2.md", b"# second", "text/markdown").json(),
        ]
        self.assertEqual([r["status"] for r in results], ["ready", "failed", "ready"])
        listed = client.get("/chat/sources/s1", headers=A).json()
        self.assertEqual(len(listed), 3)

    def test_UP_010_unsupported_types_are_rejected(self):
        client = self._firebase_client()
        for name, mime in (
            ("run.exe", "application/x-msdownload"),
            ("bundle.zip", "application/zip"),
            ("noext", ""),
            ("script.sh", "text/x-shellscript"),
        ):
            response = _upload(client, A, name, b"MZ\x90\x00", mime)
            self.assertIn(response.status_code, (200, 400), (name, response.text[:300]))
            if response.status_code == 200:
                self.assertEqual(response.json()["status"], "failed", name)

    def test_UP_012_octet_stream_falls_back_to_extension(self):
        client = self._firebase_client()
        response = _upload(client, A, "notes.md", b"# hi", "application/octet-stream")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["mimeType"], "text/markdown")
        self.assertEqual(response.json()["status"], "ready")

    def test_UP_composer_attachment_fuzz(self):
        client = self._firebase_client()
        bad = client.post(
            "/chat/attachments/upload",
            headers=A,
            files={"file": ("x.exe", io.BytesIO(b"MZ"), "application/x-msdownload")},
        )
        self.assertEqual(bad.status_code, 400)
        big = client.post(
            "/chat/attachments/upload",
            headers=A,
            files={"file": ("big.txt", io.BytesIO(b"a" * 2048), "text/plain")},
        )
        self.assertEqual(big.status_code, 413)
        missing = client.post("/chat/attachments/upload", headers=A, data={"sessionId": "s1"})
        self.assertIn(missing.status_code, (400, 422))


# ── 5.4 Source text, URL, retrieval ──────────────────────────────────────


class TestSources(_ClientMixin, unittest.TestCase):
    def test_SRC_001_text_source_fuzz(self):
        client = self._firebase_client()
        for text in [*FUZZ_STRINGS, "a" * 1000000]:
            response = client.post(
                "/chat/sources/s1/text", headers=A, json={"name": text[:50], "text": text}
            )
            self.assertEqual(response.status_code, 200, repr(text[:40]))
            body = response.json()
            self.assertIn(body["status"], ("ready", "failed"))
            if not text.strip():
                self.assertEqual(body["status"], "failed")
        for body in (
            {},
            {"text": None},
            {"text": 123},
            {"text": ["a"]},
            {"name": None, "text": "ok"},
        ):
            response = client.post("/chat/sources/s1/text", headers=A, json=body)
            self.assertNotEqual(response.status_code, 500, (body, response.text[:200]))

    def test_SRC_002_private_targets_are_rejected_before_any_fetch(self):
        client = self._firebase_client()
        fetched: list[str] = []

        def _no_fetch(url, **_kw):
            fetched.append(url)
            raise AssertionError(f"network reached for {url}")

        with (
            patch("general_chat.sources.fetch_url_text", side_effect=_no_fetch),
            patch("general_chat.sources._fetch_url_bytes", side_effect=_no_fetch, create=True),
            patch(
                "general_chat.sources.SourceParserRegistry._parse_url_with_docling",
                side_effect=_no_fetch,
            ),
        ):
            for url in (
                "http://localhost/admin",
                "http://127.0.0.1:8080/health",
                "http://127.1/",
                "http://0.0.0.0/",
                "http://[::1]/",
                "http://10.0.0.5/",
                "http://192.168.1.1/",
                "http://172.16.0.1/",
                "http://169.254.169.254/computeMetadata/v1/",
                "http://metadata.google.internal/computeMetadata/v1/",
                "file:///etc/passwd",
                "gopher://example.com/",
                "ftp://example.com/x",
                "http://2130706433/",
                "http://0x7f000001/",
            ):
                response = client.post("/chat/sources/s1/url", headers=A, json={"url": url})
                self.assertEqual(response.status_code, 200, url)
                self.assertEqual(
                    response.json()["status"], "failed", (url, response.json().get("error"))
                )
        self.assertEqual(fetched, [])

    def test_SRC_004_malformed_urls(self):
        client = self._firebase_client()
        with (
            patch("general_chat.sources.fetch_url_text", side_effect=AssertionError("no net")),
            patch(
                "general_chat.sources.SourceParserRegistry._parse_url_with_docling",
                side_effect=AssertionError("no net"),
            ),
        ):
            for url in (
                "",
                "   ",
                "example.com",
                "javascript:alert(1)",
                "http://",
                "http://exa mple.com/",
                "http://a/" + "q" * 20000,
            ):
                response = client.post("/chat/sources/s1/url", headers=A, json={"url": url})
                self.assertEqual(response.status_code, 200, url)
                self.assertEqual(response.json()["status"], "failed", url)
        for body in ({}, {"url": None}, {"url": 5}, {"url": ["http://x"]}):
            response = client.post("/chat/sources/s1/url", headers=A, json=body)
            self.assertNotEqual(response.status_code, 500, (body, response.text[:200]))

    def test_SRC_007_delete_unknown_or_foreign_source(self):
        client = self._firebase_client()
        created = client.post(
            "/chat/sources/s1/text", headers=A, json={"name": "n", "text": "alpha"}
        ).json()
        self.assertEqual(
            client.delete("/chat/sources/s1/does-not-exist", headers=A).status_code, 404
        )
        self.assertEqual(
            client.delete(f"/chat/sources/s1/{created['id']}", headers=B).status_code, 404
        )
        self.assertEqual(
            client.delete(f"/chat/sources/other/{created['id']}", headers=A).status_code, 404
        )
        self.assertEqual(client.delete("/chat/sources/s1/../../x", headers=A).status_code, 404)
        self.assertEqual(len(client.get("/chat/sources/s1", headers=A).json()), 1)
        self.assertEqual(
            client.delete(f"/chat/sources/s1/{created['id']}", headers=A).status_code, 200
        )
        self.assertEqual(
            client.delete(f"/chat/sources/s1/{created['id']}", headers=A).status_code, 404
        )

    def test_SRC_008_search_fuzz_no_crash_no_leak(self):
        client = self._firebase_client()
        client.post(
            "/chat/sources/s1/text", headers=A, json={"name": "a", "text": "alice alpha secret"}
        )
        client.post(
            "/chat/sources/s1/text", headers=B, json={"name": "b", "text": "bob bravo secret"}
        )
        for q in [*FUZZ_STRINGS, "secret", ".*", "%", "_"]:
            response = client.get("/chat/sources/s1/search", headers=A, params={"q": q})
            self.assertEqual(response.status_code, 200, repr(q[:40]))
            for hit in response.json()["results"]:
                self.assertNotIn("bravo", str(hit))
        for limit in ("-1", "0", "abc", "999999999999"):
            response = client.get(
                "/chat/sources/s1/search", headers=A, params={"q": "secret", "limit": limit}
            )
            self.assertNotEqual(response.status_code, 500, limit)


# ── 5.6 Admin users ──────────────────────────────────────────────────────


class TestAdminUsers(_ClientMixin, unittest.TestCase):
    def test_ADM_001_email_normalization_and_validation(self):
        client = self._firebase_client()
        created = client.post(
            "/admin/users",
            headers=ADMIN_H,
            json={"email": "  New.User+tag@Example.COM ", "role": "user"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["email"], "new.user+tag@example.com")
        dup = client.post(
            "/admin/users", headers=ADMIN_H, json={"email": "NEW.USER+TAG@example.com"}
        )
        self.assertEqual(dup.status_code, 409)
        for email in (
            "",
            "   ",
            "nope",
            "@example.com",
            "a@",
            "a b@example.com",
            "x" * 400 + "@example.com",
            "<script>@example.com",
        ):
            response = client.post("/admin/users", headers=ADMIN_H, json={"email": email})
            self.assertIn(response.status_code, (400, 409, 422), (email, response.text))
        for role in ("root", "", "ADMIN ", 5):
            response = client.post(
                "/admin/users",
                headers=ADMIN_H,
                json={"email": f"r{role}@example.com", "role": role},
            )
            self.assertIn(response.status_code, (400, 422), (role, response.text))
        for body in ({}, {"email": None}, {"email": ["a@b.c"]}, {"email": {"x": 1}}):
            response = client.post("/admin/users", headers=ADMIN_H, json=body)
            self.assertNotEqual(response.status_code, 500, body)

    def test_ADM_002_cannot_delete_self_or_last_admin(self):
        client = self._firebase_client()
        self.assertEqual(
            client.delete(f"/admin/users/{ADMIN.email}", headers=ADMIN_H).status_code, 400
        )
        self.assertEqual(
            client.delete(
                f"/admin/users/{(ADMIN.email or '').upper()}", headers=ADMIN_H
            ).status_code,
            400,
        )
        demote = client.patch(f"/admin/users/{ADMIN.email}", headers=ADMIN_H, json={"role": "user"})
        self.assertEqual(demote.status_code, 400)
        self.assertEqual(client.get("/account/me", headers=ADMIN_H).json()["role"], "admin")
        self.assertEqual(
            client.delete("/admin/users/ghost@example.com", headers=ADMIN_H).status_code, 404
        )

    def test_ADM_003_role_change_takes_effect(self):
        client = self._firebase_client()
        self.assertEqual(client.get("/admin/users", headers=A).status_code, 403)
        promote = client.patch(
            f"/admin/users/{ALICE.email}", headers=ADMIN_H, json={"role": "admin"}
        )
        self.assertEqual(promote.status_code, 200, promote.text)
        self.assertEqual(client.get("/admin/users", headers=A).status_code, 200)
        self.assertEqual(client.get("/account/me", headers=A).json()["role"], "admin")
        demote = client.patch(f"/admin/users/{ALICE.email}", headers=ADMIN_H, json={"role": "user"})
        self.assertEqual(demote.status_code, 200)
        self.assertEqual(client.get("/admin/users", headers=A).status_code, 403)

    def test_ADM_007_capabilities_payload_fuzz(self):
        client = self._firebase_client()
        for body in (
            {"roles": {"user": {"made_up": True}}},
            {"roles": "nope"},
            {"groups": None},
            {"groups": {"g1": None}},
            {"roles": {"user": {"attachments": "yes"}}},
            {"nested": {"a": {"b": {"c": {"d": 1}}}}},
            [],
            "string",
        ):
            response = client.put("/admin/capabilities", headers=ADMIN_H, json=body)
            self.assertNotEqual(response.status_code, 500, (body, response.text[:200]))
        caps = client.get("/admin/capabilities", headers=ADMIN_H).json()
        self.assertNotIn("made_up", caps["roles"]["user"])


# ── 5.8 / 5.9 Agents and embed ───────────────────────────────────────────


class TestAgentsAndEmbed(_ClientMixin, unittest.TestCase):
    def _agent(self, client, name="Legal"):
        response = client.post(
            "/admin/agents", headers=ADMIN_H, json={"name": name, "description": "d"}
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_AGT_001_agent_name_fuzz_yields_safe_unique_ids(self):
        client = self._firebase_client()
        ids = set()
        for name in [*FUZZ_STRINGS, "../../etc/passwd", "Legal", "Legal", "LEGAL", "a/b\\c"]:
            response = client.post(
                "/admin/agents", headers=ADMIN_H, json={"name": name, "description": ""}
            )
            self.assertNotEqual(response.status_code, 500, (repr(name[:30]), response.text[:200]))
            if response.status_code != 201:
                continue
            agent_id = response.json()["id"]
            self.assertRegex(agent_id, r"^[a-z0-9][a-z0-9-]*$", repr(name[:30]))
            self.assertNotIn(agent_id, ids, repr(name[:30]))
            ids.add(agent_id)

    def test_AGT_002_pinned_session_rejects_other_agent(self):
        client = self._firebase_client()
        legal = self._agent(client, "Legal")
        finance = self._agent(client, "Finance")
        from openbench.chat.session import ChatSession
        from openbench.chat.stores.sqlite import SQLiteSessionStore

        store = SQLiteSessionStore(str(self.tmpdir / "storage" / "sessions.db"), owner=ALICE.email)
        session = ChatSession(session_id="pinned", title="t")
        session.metadata["agentId"] = legal["id"]
        store.save(session)
        body = {"threadId": "pinned", "messages": [{"role": "user", "content": "hi"}]}
        response = client.post(f"/agents/{finance['id']}/awp", headers=A, json=body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(store.load("pinned").metadata["agentId"], legal["id"])

    def test_EMB_001_002_004_embed_key_scope(self):
        client = self._firebase_client()
        legal = self._agent(client, "Legal")
        finance = self._agent(client, "Finance")
        rotated = client.post(f"/admin/agents/{legal['id']}/embed-key", headers=ADMIN_H)
        self.assertEqual(rotated.status_code, 200, rotated.text)
        key = rotated.json().get("embedKey") or rotated.json().get("key")
        self.assertTrue(key)
        self.assertNotIn(key, client.get(f"/agents/{legal['id']}").text)
        good = {"Authorization": f"Bearer {key}"}
        self.assertEqual(
            client.get(f"/agents/{legal['id']}/sessions", headers=good).status_code, 501
        )
        self.assertEqual(
            client.get(f"/agents/{legal['id']}/anything/else", headers=good).status_code, 404
        )
        # Key scoped to Legal cannot reach Finance or any other prefix.
        self.assertEqual(
            client.get(f"/agents/{finance['id']}/sessions", headers=good).status_code, 401
        )
        for path in ("/sessions", "/account/me", "/admin/users", "/chat/sources/s1"):
            self.assertIn(client.get(path, headers=good).status_code, (401, 403), path)
        upload = client.post(
            f"/agents/{legal['id']}/chat/upload",
            headers=good,
            files={"file": ("x.txt", io.BytesIO(b"x"), "text/plain")},
        )
        self.assertEqual(upload.status_code, 404)
        # Wrong / empty / revoked keys.
        for bad in ("", "nope", key[:-1], key + "x"):
            response = client.get(
                f"/agents/{legal['id']}/sessions", headers={"Authorization": f"Bearer {bad}"}
            )
            self.assertEqual(response.status_code, 401, bad)
        self.assertEqual(
            client.delete(f"/admin/agents/{legal['id']}/embed-key", headers=ADMIN_H).status_code,
            200,
        )
        self.assertEqual(
            client.get(f"/agents/{legal['id']}/sessions", headers=good).status_code, 401
        )


# ── 5.14 File serving ────────────────────────────────────────────────────


class TestFileServing(_ClientMixin, unittest.TestCase):
    def test_FILE_001_uploads_traversal_and_owner_marker(self):
        client = self._firebase_client()
        uploaded = _upload(client, A, "doc.txt", b"body", "text/plain").json()
        file_id = uploaded["url"].split("/")[2]
        (self.tmpdir / "uploads" / ".." / "outside.txt").resolve().write_text("outside")
        self.addCleanup(lambda: (self.tmpdir / "outside.txt").unlink(missing_ok=True))
        for path in (
            f"/uploads/{file_id}/.owner",
            f"/uploads/{file_id}/..%2F..%2Foutside.txt",
            f"/uploads/{file_id}/../outside.txt",
            f"/uploads/{file_id}/../../outside.txt",
            "/uploads/../outside.txt",
            "/uploads/%2e%2e/outside.txt",
            f"/uploads/{file_id}",
            f"/uploads/{file_id}/",
            "/uploads/.",
            "/uploads/..",
        ):
            response = client.get(path, headers=A)
            self.assertEqual(response.status_code, 404, path)
            self.assertNotIn("outside", response.text)
            self.assertNotIn(ALICE.email or "", response.text)

    def test_FILE_002_downloads_traversal(self):
        client = self._firebase_client()
        (self.tmpdir / "downloads").mkdir(exist_ok=True)
        (self.tmpdir / "downloads" / "report.txt").write_text("report")
        (self.tmpdir / "secret.txt").write_text("secret")
        self.assertEqual(client.get("/downloads/report.txt", headers=A).status_code, 200)
        for path in (
            "/downloads/../secret.txt",
            "/downloads/..%2Fsecret.txt",
            "/downloads/%2e%2e/secret.txt",
            "/downloads/",
            "/downloads/%00",
        ):
            response = client.get(path, headers=A)
            self.assertIn(response.status_code, (400, 404), path)
            self.assertNotIn("secret", response.text)

    def test_FILE_003_signed_downloads(self):
        client = self._firebase_client({"OPENBENCH_DOWNLOAD_SECRET": "s3cr3t"})
        from openbench.utils.download_tokens import sign_download_url

        (self.tmpdir / "downloads").mkdir(exist_ok=True)
        (self.tmpdir / "downloads" / "report.txt").write_text("report")
        signed = sign_download_url("/downloads/report.txt")
        self.assertEqual(client.get(signed, headers=A).status_code, 200)
        # No token, tampered exp, wrong filename, garbage sig.
        self.assertEqual(client.get("/downloads/report.txt", headers=A).status_code, 403)
        base, query = signed.split("?", 1)
        params = dict(part.split("=", 1) for part in query.split("&"))
        tampered = f"{base}?exp=9999999999&sig={params['sig']}"
        self.assertEqual(client.get(tampered, headers=A).status_code, 403)
        wrong_name = f"/downloads/other.txt?exp={params['exp']}&sig={params['sig']}"
        self.assertIn(client.get(wrong_name, headers=A).status_code, (403, 404))
        self.assertEqual(
            client.get(f"{base}?exp={params['exp']}&sig=deadbeef", headers=A).status_code, 403
        )
        expired = sign_download_url("/downloads/report.txt", now=1)
        self.assertEqual(client.get(expired, headers=A).status_code, 403)

    def test_FILE_006_agent_namespace_unknown_paths_are_json_404(self):
        client = self._firebase_client()
        response = client.get("/agents/nope/sessions/abc", headers=A)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["content-type"].split(";")[0], "application/json")

    def test_FILE_005_published_dashboard_id_fuzz(self):
        client = self._firebase_client()
        for dashboard_id in ("..", "%2e%2e", "x" * 300, "a/../b", "<script>", "nope"):
            response = client.get(f"/d/{dashboard_id}")
            self.assertIn(response.status_code, (400, 404), dashboard_id)
            self.assertNotIn("Traceback", response.text)


if __name__ == "__main__":
    unittest.main()
