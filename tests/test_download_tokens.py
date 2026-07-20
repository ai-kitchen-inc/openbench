"""Tests for HMAC-signed /downloads tokens (openbench.utils.download_tokens)."""

from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from openbench.utils.download_tokens import (
    download_secret,
    download_ttl_seconds,
    sign_download_url,
    verify_download_token,
)

URL = "/downloads/report-abc123.xlsx"


def _parse(signed: str) -> tuple[str, str, str]:
    parts = urlparse(signed)
    query = parse_qs(parts.query)
    name = parts.path.rsplit("/", 1)[-1]
    return name, query["exp"][0], query["sig"][0]


class TestNoSecret(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.dict("os.environ", {"OPENBENCH_DOWNLOAD_SECRET": ""}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_secret_off(self) -> None:
        self.assertIsNone(download_secret())

    def test_sign_is_identity(self) -> None:
        self.assertEqual(sign_download_url(URL), URL)

    def test_verify_always_passes(self) -> None:
        self.assertTrue(verify_download_token("anything.pdf", "", ""))


class TestSigned(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.dict(
            "os.environ",
            {"OPENBENCH_DOWNLOAD_SECRET": "test-secret", "OPENBENCH_DOWNLOAD_TTL_SECONDS": ""},
            clear=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_round_trip(self) -> None:
        name, exp, sig = _parse(sign_download_url(URL, now=1_000_000))
        self.assertEqual(name, "report-abc123.xlsx")
        self.assertTrue(verify_download_token(name, exp, sig, now=1_000_000))

    def test_expired_rejected(self) -> None:
        name, exp, sig = _parse(sign_download_url(URL, now=1_000_000))
        after_expiry = int(exp) + 1
        self.assertFalse(verify_download_token(name, exp, sig, now=after_expiry))

    def test_tampered_sig_rejected(self) -> None:
        name, exp, sig = _parse(sign_download_url(URL, now=1_000_000))
        bad_sig = ("0" if sig[0] != "0" else "1") + sig[1:]
        self.assertFalse(verify_download_token(name, exp, bad_sig, now=1_000_000))

    def test_tampered_name_rejected(self) -> None:
        _name, exp, sig = _parse(sign_download_url(URL, now=1_000_000))
        self.assertFalse(verify_download_token("other-file.xlsx", exp, sig, now=1_000_000))

    def test_non_numeric_exp_rejected(self) -> None:
        name, _exp, sig = _parse(sign_download_url(URL, now=1_000_000))
        self.assertFalse(verify_download_token(name, "soon", sig, now=1_000_000))
        self.assertFalse(verify_download_token(name, "", sig, now=1_000_000))

    def test_missing_sig_rejected(self) -> None:
        name, exp, _sig = _parse(sign_download_url(URL, now=1_000_000))
        self.assertFalse(verify_download_token(name, exp, "", now=1_000_000))

    def test_default_ttl(self) -> None:
        self.assertEqual(download_ttl_seconds(), 86400)
        name, exp, _sig = _parse(sign_download_url(URL, now=1_000_000))
        self.assertEqual(int(exp), 1_000_000 + 86400)

    def test_ttl_override(self) -> None:
        with patch.dict("os.environ", {"OPENBENCH_DOWNLOAD_TTL_SECONDS": "3600"}, clear=False):
            self.assertEqual(download_ttl_seconds(), 3600)
            name, exp, sig = _parse(sign_download_url(URL, now=1_000_000))
            self.assertEqual(int(exp), 1_000_000 + 3600)
            self.assertTrue(verify_download_token(name, exp, sig, now=1_000_000 + 3599))
            self.assertFalse(verify_download_token(name, exp, sig, now=1_000_000 + 3601))

    def test_invalid_ttl_falls_back(self) -> None:
        for raw in ("abc", "-5", "0"):
            with patch.dict(
                "os.environ", {"OPENBENCH_DOWNLOAD_TTL_SECONDS": raw}, clear=False
            ):
                self.assertEqual(download_ttl_seconds(), 86400)


if __name__ == "__main__":
    unittest.main()
