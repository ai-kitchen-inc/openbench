"""Tests for drive_oauth helpers.

Mocks :mod:`urllib.request` so tests run without network.
"""

from __future__ import annotations

import io
import json
import unittest
import urllib.error
import urllib.parse
from typing import Any
from unittest.mock import MagicMock, patch

from openbench.integrations.firebase_auth.drive_oauth import (
    DEFAULT_SCOPES,
    OAuthError,
    TokenResponse,
    build_authorize_url,
    exchange_code,
    load_client_secrets,
    refresh_access_token,
    revoke_refresh_token,
)

# ---------------------------------------------------------------------------
# build_authorize_url
# ---------------------------------------------------------------------------


class TestBuildAuthorizeUrl(unittest.TestCase):
    def test_includes_required_params(self):
        url = build_authorize_url(
            client_id="cid",
            redirect_uri="https://example.com/cb",
            scopes=list(DEFAULT_SCOPES),
            state="csrf-123",
        )
        parts = urllib.parse.urlparse(url)
        self.assertEqual(parts.netloc, "accounts.google.com")
        self.assertEqual(parts.path, "/o/oauth2/v2/auth")
        query = dict(urllib.parse.parse_qsl(parts.query))
        self.assertEqual(query["client_id"], "cid")
        self.assertEqual(query["redirect_uri"], "https://example.com/cb")
        self.assertEqual(query["response_type"], "code")
        self.assertEqual(query["access_type"], "offline")
        self.assertEqual(query["prompt"], "consent")
        self.assertEqual(query["state"], "csrf-123")
        self.assertIn("drive.file", query["scope"])

    def test_scope_is_space_separated(self):
        url = build_authorize_url(
            client_id="cid",
            redirect_uri="https://x/cb",
            scopes=["a", "b", "c"],
            state="s",
        )
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        self.assertEqual(query["scope"], "a b c")

    def test_includes_login_hint_when_provided(self):
        url = build_authorize_url(
            client_id="c",
            redirect_uri="https://x/cb",
            scopes=["s"],
            state="s",
            login_hint="jane@example.com",
        )
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        self.assertEqual(query["login_hint"], "jane@example.com")

    def test_login_hint_omitted_by_default(self):
        url = build_authorize_url(
            client_id="c", redirect_uri="https://x/cb", scopes=["s"], state="s"
        )
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        self.assertNotIn("login_hint", query)

    def test_rejects_empty_required_params(self):
        base = {
            "client_id": "c",
            "redirect_uri": "https://x/cb",
            "scopes": ["s"],
            "state": "s",
        }
        for missing in base:
            payload = {**base, missing: "" if missing != "scopes" else []}
            with self.assertRaises(ValueError):
                build_authorize_url(**payload)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_urlopen_response(payload: dict[str, Any], status: int = 200) -> MagicMock:
    """Simulate urllib.request.urlopen's context-manager response."""
    body = json.dumps(payload).encode("utf-8")

    class _Resp:
        def __init__(self) -> None:
            self._io = io.BytesIO(body)
            self.status = status

        def read(self) -> bytes:
            return self._io.read()

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    return _Resp()


def _fake_http_error(status: int, body: str = "") -> urllib.error.HTTPError:
    err = urllib.error.HTTPError(
        url="https://oauth2.googleapis.com/token",
        code=status,
        msg="Bad Request",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(body.encode("utf-8")),
    )
    return err


# ---------------------------------------------------------------------------
# exchange_code
# ---------------------------------------------------------------------------


class TestExchangeCode(unittest.TestCase):
    def test_happy_path_returns_tokens(self):
        payload = {
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/drive.file",
            "token_type": "Bearer",
        }
        with patch("urllib.request.urlopen", return_value=_fake_urlopen_response(payload)):
            tok = exchange_code(
                client_id="cid",
                client_secret="sec",
                redirect_uri="https://x/cb",
                code="abc",
            )
        self.assertIsInstance(tok, TokenResponse)
        self.assertEqual(tok.access_token, "at-1")
        self.assertEqual(tok.refresh_token, "rt-1")
        self.assertEqual(tok.scope, "https://www.googleapis.com/auth/drive.file")
        self.assertGreater(tok.expires_at, 0)

    def test_body_shape_sent_to_google(self):
        captured: dict[str, Any] = {}

        def _spy(req: Any, timeout: float = 10) -> Any:
            captured["data"] = req.data
            captured["url"] = req.full_url
            return _fake_urlopen_response(
                {"access_token": "x", "refresh_token": "r", "expires_in": 3600}
            )

        with patch("urllib.request.urlopen", side_effect=_spy):
            exchange_code(
                client_id="cid",
                client_secret="sec",
                redirect_uri="https://x/cb",
                code="abc",
            )
        form = dict(urllib.parse.parse_qsl(captured["data"].decode("utf-8")))
        self.assertEqual(form["grant_type"], "authorization_code")
        self.assertEqual(form["code"], "abc")
        self.assertEqual(form["client_id"], "cid")
        self.assertEqual(form["client_secret"], "sec")
        self.assertEqual(form["redirect_uri"], "https://x/cb")

    def test_empty_code_rejected(self):
        with self.assertRaises(ValueError):
            exchange_code(client_id="c", client_secret="s", redirect_uri="r", code="")

    def test_http_error_surfaces_as_oauth_error(self):
        err = _fake_http_error(400, json.dumps({"error": "invalid_grant"}))
        with patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(OAuthError) as ctx:
                exchange_code(client_id="c", client_secret="s", redirect_uri="r", code="x")
            self.assertIn("400", str(ctx.exception))
            self.assertIn("invalid_grant", str(ctx.exception))

    def test_missing_access_token_in_response(self):
        payload = {"refresh_token": "only-refresh", "expires_in": 3600}
        with patch("urllib.request.urlopen", return_value=_fake_urlopen_response(payload)):
            with self.assertRaises(OAuthError) as ctx:
                exchange_code(client_id="c", client_secret="s", redirect_uri="r", code="x")
            self.assertIn("missing access_token", str(ctx.exception))


# ---------------------------------------------------------------------------
# refresh_access_token
# ---------------------------------------------------------------------------


class TestRefreshAccessToken(unittest.TestCase):
    def test_sends_refresh_grant(self):
        captured: dict[str, Any] = {}

        def _spy(req: Any, timeout: float = 10) -> Any:
            captured["data"] = req.data
            return _fake_urlopen_response({"access_token": "new-at", "expires_in": 3500})

        with patch("urllib.request.urlopen", side_effect=_spy):
            tok = refresh_access_token(client_id="c", client_secret="s", refresh_token="rt-1")
        self.assertEqual(tok.access_token, "new-at")
        # Refresh responses do NOT include a refresh_token
        self.assertIsNone(tok.refresh_token)
        form = dict(urllib.parse.parse_qsl(captured["data"].decode("utf-8")))
        self.assertEqual(form["grant_type"], "refresh_token")
        self.assertEqual(form["refresh_token"], "rt-1")

    def test_empty_refresh_rejected(self):
        with self.assertRaises(ValueError):
            refresh_access_token(client_id="c", client_secret="s", refresh_token="")

    def test_invalid_grant_surfaces_as_oauth_error(self):
        err = _fake_http_error(400, '{"error":"invalid_grant"}')
        with patch("urllib.request.urlopen", side_effect=err), self.assertRaises(OAuthError):
            refresh_access_token(client_id="c", client_secret="s", refresh_token="rt")


# ---------------------------------------------------------------------------
# revoke_refresh_token
# ---------------------------------------------------------------------------


class TestRevokeRefreshToken(unittest.TestCase):
    def test_returns_true_on_200(self):
        class _Resp:
            status = 200

            def __enter__(self) -> Any:
                return self

            def __exit__(self, *args: Any) -> None:
                pass

        with patch("urllib.request.urlopen", return_value=_Resp()):
            self.assertTrue(revoke_refresh_token("rt"))

    def test_returns_false_on_http_error(self):
        err = _fake_http_error(400, "")
        with patch("urllib.request.urlopen", side_effect=err):
            self.assertFalse(revoke_refresh_token("rt"))

    def test_returns_false_for_empty_token(self):
        self.assertFalse(revoke_refresh_token(""))


# ---------------------------------------------------------------------------
# load_client_secrets
# ---------------------------------------------------------------------------


class TestLoadClientSecrets(unittest.TestCase):
    def test_reads_web_section(self, tmp_path=None):
        import json as _json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cs.json"
            p.write_text(
                _json.dumps(
                    {
                        "web": {
                            "client_id": "c",
                            "client_secret": "s",
                            "redirect_uris": ["https://x/cb", "https://y/cb"],
                        }
                    }
                )
            )
            cs = load_client_secrets(str(p))
            self.assertEqual(cs.client_id, "c")
            self.assertEqual(cs.client_secret, "s")
            self.assertEqual(cs.redirect_uris, ("https://x/cb", "https://y/cb"))

    def test_reads_installed_section(self):
        import json as _json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cs.json"
            p.write_text(_json.dumps({"installed": {"client_id": "c", "client_secret": "s"}}))
            cs = load_client_secrets(str(p))
            self.assertEqual(cs.client_id, "c")

    def test_missing_required_fields_raises(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cs.json"
            p.write_text('{"web": {"client_id": "c"}}')
            with self.assertRaises(ValueError):
                load_client_secrets(str(p))

    def test_missing_root_raises(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cs.json"
            p.write_text('{"other": {}}')
            with self.assertRaises(ValueError):
                load_client_secrets(str(p))


if __name__ == "__main__":
    unittest.main()
