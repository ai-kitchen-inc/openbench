"""Tests for openbench.utils.net_guard (SSRF guard for server-side fetches)."""

from __future__ import annotations

import socket
import unittest
from unittest import mock

from openbench.utils import net_guard

PUBLIC_ADDRINFO = [(2, 1, 6, "", ("93.184.216.34", 0))]
PRIVATE_ADDRINFO = [(2, 1, 6, "", ("10.0.0.7", 0))]


def _response(
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    chunks: list[bytes] | None = None,
    redirect: bool = False,
):
    response = mock.Mock()
    response.status_code = status_code
    response.headers = headers or {}
    response.is_redirect = redirect
    response.is_permanent_redirect = False
    response.encoding = "utf-8"
    response.iter_content = lambda chunk_size: iter(chunks or [])
    response.raise_for_status = mock.Mock()
    response.close = mock.Mock()
    return response


def _session(responses: list) -> mock.Mock:
    session = mock.MagicMock()
    session.__enter__.return_value = session
    session.get.side_effect = responses
    return session


class TestIsPublicIp(unittest.TestCase):
    def test_public_addresses(self):
        for address in ("8.8.8.8", "93.184.216.34", "2606:4700:4700::1111"):
            self.assertTrue(net_guard.is_public_ip(address), address)

    def test_non_public_addresses(self):
        for address in (
            "127.0.0.1",
            "10.0.0.1",
            "172.16.5.4",
            "192.168.1.1",
            "169.254.169.254",
            "0.0.0.0",
            "224.0.0.1",
            "::1",
            "fe80::1",
            "fc00::1",
            "::ffff:127.0.0.1",
            "::ffff:10.0.0.1",
            "not-an-ip",
            "",
        ):
            self.assertFalse(net_guard.is_public_ip(address), address)


class TestBlockedHostReason(unittest.TestCase):
    def test_empty_host_is_invalid(self):
        self.assertEqual(net_guard.blocked_host_reason(""), net_guard.BLOCK_INVALID)

    def test_local_names(self):
        for host in ("localhost", "metadata", "metadata.google.internal", "x.local", "db.internal"):
            self.assertEqual(net_guard.blocked_host_reason(host), net_guard.BLOCK_LOCAL, host)

    def test_private_literals_including_alternate_spellings(self):
        for host in (
            "127.0.0.1",
            "10.1.2.3",
            "169.254.169.254",
            "[::1]",
            "127.1",
            "2130706433",
            "0x7f000001",
        ):
            self.assertEqual(net_guard.blocked_host_reason(host), net_guard.BLOCK_PRIVATE, host)

    def test_public_literal_is_allowed(self):
        self.assertIsNone(net_guard.blocked_host_reason("93.184.216.34"))

    def test_hostname_resolving_to_private_address_is_blocked(self):
        with mock.patch("socket.getaddrinfo", return_value=PRIVATE_ADDRINFO):
            self.assertEqual(
                net_guard.blocked_host_reason("intranet.example.com"), net_guard.BLOCK_PRIVATE
            )

    def test_any_private_answer_blocks_the_host(self):
        mixed = PUBLIC_ADDRINFO + PRIVATE_ADDRINFO
        with mock.patch("socket.getaddrinfo", return_value=mixed):
            self.assertEqual(
                net_guard.blocked_host_reason("rebind.example.com"), net_guard.BLOCK_PRIVATE
            )

    def test_unresolvable_host_is_not_a_block(self):
        with mock.patch("socket.getaddrinfo", side_effect=socket.gaierror):
            self.assertIsNone(net_guard.blocked_host_reason("nxdomain.example.com"))


class TestValidatePublicUrl(unittest.TestCase):
    def test_returns_stripped_url(self):
        with mock.patch("socket.getaddrinfo", return_value=PUBLIC_ADDRINFO):
            self.assertEqual(
                net_guard.validate_public_url("  https://example.com/a?b=1 "),
                "https://example.com/a?b=1",
            )

    def test_rejects_non_http_schemes_and_garbage(self):
        for url in ("ftp://example.com/x", "file:///etc/passwd", "gopher://x/", "not-a-url", "", None):
            with self.assertRaises(ValueError, msg=repr(url)):
                net_guard.validate_public_url(url)  # type: ignore[arg-type]

    def test_rejects_private_targets(self):
        for url in (
            "http://localhost:8080/health",
            "http://127.0.0.1/",
            "http://10.0.0.5/",
            "http://169.254.169.254/computeMetadata/v1/",
            "http://metadata.google.internal/",
            "http://[::1]/",
            "http://2130706433/",
        ):
            with self.assertRaises(ValueError, msg=url):
                net_guard.validate_public_url(url)

    def test_rejects_overlong_url(self):
        with self.assertRaisesRegex(ValueError, "too long"):
            net_guard.validate_public_url("https://example.com/" + "a" * 9000)


class TestSafeGet(unittest.TestCase):
    def test_fetches_a_public_url(self):
        session = _session(
            [_response(headers={"content-type": "image/png; charset=binary"}, chunks=[b"ab", b"cd"])]
        )
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_ADDRINFO),
            mock.patch("requests.Session", return_value=session),
        ):
            result = net_guard.safe_get("https://example.com/x.png", max_bytes=100)
        self.assertEqual(result.content, b"abcd")
        self.assertEqual(result.content_type, "image/png")
        self.assertEqual(result.final_url, "https://example.com/x.png")
        self.assertFalse(result.truncated)
        # Redirects are never delegated to requests.
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])

    def test_private_url_is_rejected_before_any_request(self):
        session = _session([])
        with mock.patch("requests.Session", return_value=session):
            with self.assertRaises(ValueError):
                net_guard.safe_get("http://169.254.169.254/latest/meta-data", max_bytes=100)
        session.get.assert_not_called()

    def test_redirect_to_private_hop_is_not_followed(self):
        session = _session(
            [
                _response(
                    status_code=302,
                    headers={"location": "http://127.0.0.1:8080/admin"},
                    redirect=True,
                )
            ]
        )
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_ADDRINFO),
            mock.patch("requests.Session", return_value=session),
        ):
            with self.assertRaises(ValueError):
                net_guard.safe_get("https://example.com/start", max_bytes=100)
        # Only the first, public hop was requested.
        self.assertEqual(session.get.call_count, 1)

    def test_public_redirect_is_followed_and_reported(self):
        session = _session(
            [
                _response(status_code=302, headers={"location": "/next"}, redirect=True),
                _response(headers={"content-type": "text/plain"}, chunks=[b"ok"]),
            ]
        )
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_ADDRINFO),
            mock.patch("requests.Session", return_value=session),
        ):
            result = net_guard.safe_get("https://example.com/start", max_bytes=100)
        self.assertEqual(result.final_url, "https://example.com/next")
        self.assertEqual(result.content, b"ok")

    def test_redirect_loop_is_bounded(self):
        hop = lambda: _response(  # noqa: E731
            status_code=302, headers={"location": "/again"}, redirect=True
        )
        session = _session([hop() for _ in range(10)])
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_ADDRINFO),
            mock.patch("requests.Session", return_value=session),
        ):
            with self.assertRaisesRegex(ValueError, "Too many redirects"):
                net_guard.safe_get("https://example.com/start", max_bytes=100, max_redirects=3)
        self.assertEqual(session.get.call_count, 4)

    def test_redirect_without_location_is_an_error(self):
        session = _session([_response(status_code=302, redirect=True)])
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_ADDRINFO),
            mock.patch("requests.Session", return_value=session),
        ):
            with self.assertRaisesRegex(ValueError, "no target"):
                net_guard.safe_get("https://example.com/start", max_bytes=100)

    def test_oversized_body_raises_by_default(self):
        session = _session([_response(chunks=[b"x" * 60, b"y" * 60])])
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_ADDRINFO),
            mock.patch("requests.Session", return_value=session),
        ):
            with self.assertRaisesRegex(ValueError, "exceeds"):
                net_guard.safe_get("https://example.com/big", max_bytes=100)

    def test_oversized_body_can_be_truncated(self):
        session = _session([_response(chunks=[b"x" * 60, b"y" * 60])])
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_ADDRINFO),
            mock.patch("requests.Session", return_value=session),
        ):
            result = net_guard.safe_get("https://example.com/big", max_bytes=100, truncate=True)
        self.assertEqual(len(result.content), 100)
        self.assertTrue(result.truncated)

    def test_response_is_always_closed(self):
        response = _response(chunks=[b"ok"])
        with (
            mock.patch("socket.getaddrinfo", return_value=PUBLIC_ADDRINFO),
            mock.patch("requests.Session", return_value=_session([response])),
        ):
            net_guard.safe_get("https://example.com/x", max_bytes=100)
        response.close.assert_called_once()


class TestVendoredCopies(unittest.TestCase):
    """Standalone MCP images cannot import openbench, so they carry a copy.

    The copies must stay identical to the SDK module: a fix made in one place
    and not the others would leave a server unguarded.
    """

    def test_vendored_copies_match_the_sdk_module(self):
        from pathlib import Path

        repo = Path(__file__).resolve().parents[1]
        original = Path(net_guard.__file__).read_text(encoding="utf-8")
        for relative in (
            "mcp/generic-api-mcp/app/net_guard.py",
            "mcp/image-search-mcp/app/net_guard.py",
        ):
            copy = (repo / relative).read_text(encoding="utf-8")
            self.assertEqual(copy, original, f"{relative} drifted from openbench/utils/net_guard.py")


if __name__ == "__main__":
    unittest.main()
