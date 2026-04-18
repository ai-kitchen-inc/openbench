"""Tests for :mod:`openbench.integrations.firebase_auth.token_store`.

Uses :class:`InMemoryTokenStore` and a real :class:`AESGCMEncryptor`
(the ``cryptography`` package is assumed present — it ships via the
``[security]`` extras and is already part of the repo's dev env).

The :class:`FirestoreTokenStore` is exercised via a mocked Firestore
client so we don't need an emulator running.
"""

from __future__ import annotations

import base64
import os
import sys
import types
import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

from openbench.integrations.firebase_auth import (
    AESGCMEncryptor,
    DriveToken,
    FirestoreTokenStore,
    InMemoryTokenStore,
    NoOpEncryptor,
)


def _random_key() -> bytes:
    return os.urandom(32)


def _sample_token(uid: str = "user-1") -> DriveToken:
    return DriveToken(
        uid=uid,
        refresh_token="rt-very-secret",
        client_id="client-abc",
        client_secret="secret-xyz",
        scopes=("https://www.googleapis.com/auth/drive.file",),
        openbench_folder_id="folder-1",
        connected_email="jane@example.com",
    )


# ---------------------------------------------------------------------------
# AESGCMEncryptor
# ---------------------------------------------------------------------------


class TestAESGCMEncryptor(unittest.TestCase):
    def test_key_must_be_32_bytes(self):
        with self.assertRaises(ValueError):
            AESGCMEncryptor(b"short")

    def test_roundtrip(self):
        enc = AESGCMEncryptor(_random_key())
        ct = enc.encrypt("secret-value")
        self.assertNotEqual(ct, "secret-value")
        self.assertEqual(enc.decrypt(ct), "secret-value")

    def test_roundtrip_unicode(self):
        enc = AESGCMEncryptor(_random_key())
        self.assertEqual(enc.decrypt(enc.encrypt("Halo — 你好 🌍")), "Halo — 你好 🌍")

    def test_different_nonces_produce_different_ciphertext(self):
        enc = AESGCMEncryptor(_random_key())
        c1 = enc.encrypt("same plaintext")
        c2 = enc.encrypt("same plaintext")
        self.assertNotEqual(c1, c2)

    def test_ciphertext_from_other_key_fails(self):
        from cryptography.exceptions import InvalidTag

        enc1 = AESGCMEncryptor(_random_key())
        enc2 = AESGCMEncryptor(_random_key())
        ct = enc1.encrypt("x")
        with self.assertRaises(InvalidTag):
            enc2.decrypt(ct)

    def test_short_ciphertext_rejected(self):
        enc = AESGCMEncryptor(_random_key())
        with self.assertRaises(ValueError):
            enc.decrypt(base64.urlsafe_b64encode(b"tiny").decode("ascii"))

    def test_from_env_happy_path(self, monkeypatch=None):
        key_b64 = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
        os.environ["TEST_ENC_KEY"] = key_b64
        try:
            enc = AESGCMEncryptor.from_env("TEST_ENC_KEY")
            self.assertEqual(enc.decrypt(enc.encrypt("ping")), "ping")
        finally:
            os.environ.pop("TEST_ENC_KEY", None)

    def test_from_env_missing_var(self):
        os.environ.pop("TEST_ENC_KEY_MISSING", None)
        with self.assertRaises(RuntimeError) as ctx:
            AESGCMEncryptor.from_env("TEST_ENC_KEY_MISSING")
        self.assertIn("TEST_ENC_KEY_MISSING", str(ctx.exception))

    def test_from_env_invalid_base64(self):
        os.environ["TEST_ENC_KEY_BAD"] = "%%not-base64%%"
        try:
            with self.assertRaises(RuntimeError):
                AESGCMEncryptor.from_env("TEST_ENC_KEY_BAD")
        finally:
            os.environ.pop("TEST_ENC_KEY_BAD", None)


# ---------------------------------------------------------------------------
# NoOpEncryptor
# ---------------------------------------------------------------------------


class TestNoOpEncryptor(unittest.TestCase):
    def test_passthrough(self):
        enc = NoOpEncryptor()
        self.assertEqual(enc.encrypt("hello"), "hello")
        self.assertEqual(enc.decrypt("hello"), "hello")


# ---------------------------------------------------------------------------
# InMemoryTokenStore
# ---------------------------------------------------------------------------


class TestInMemoryTokenStore(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryTokenStore(encryptor=AESGCMEncryptor(_random_key()))

    def test_save_and_load(self):
        tok = _sample_token()
        self.store.save(tok)
        loaded = self.store.load(tok.uid)
        assert loaded is not None
        self.assertEqual(loaded.uid, tok.uid)
        self.assertEqual(loaded.refresh_token, tok.refresh_token)
        self.assertEqual(loaded.client_secret, tok.client_secret)
        self.assertEqual(loaded.scopes, tok.scopes)
        self.assertEqual(loaded.connected_email, tok.connected_email)

    def test_load_missing_returns_none(self):
        self.assertIsNone(self.store.load("nope"))

    def test_save_overwrites(self):
        self.store.save(_sample_token())
        newer = DriveToken(
            uid="user-1",
            refresh_token="rt-2",
            client_id="c",
            client_secret="s",
        )
        self.store.save(newer)
        loaded = self.store.load("user-1")
        assert loaded is not None
        self.assertEqual(loaded.refresh_token, "rt-2")

    def test_delete_removes(self):
        self.store.save(_sample_token())
        self.store.delete("user-1")
        self.assertIsNone(self.store.load("user-1"))

    def test_delete_missing_is_noop(self):
        self.store.delete("never-existed")

    def test_stored_value_is_encrypted_not_plaintext(self):
        """Refresh token must never touch the in-memory dict as plaintext."""
        self.store.save(_sample_token())
        raw = self.store._data["user-1"]  # peek internals
        self.assertNotIn("rt-very-secret", raw["refresh_token_enc"])
        self.assertNotIn("secret-xyz", raw["client_secret_enc"])


# ---------------------------------------------------------------------------
# FirestoreTokenStore — mocked firestore client
# ---------------------------------------------------------------------------


class TestFirestoreTokenStore(unittest.TestCase):
    def setUp(self):
        # Install a fake firebase_admin.firestore module so the lazy
        # import inside FirestoreTokenStore._build_client resolves.
        self._saved_modules = {}
        for name in ("firebase_admin", "firebase_admin.firestore"):
            self._saved_modules[name] = sys.modules.get(name)
        fake_fb = types.ModuleType("firebase_admin")
        fake_fs = types.ModuleType("firebase_admin.firestore")
        self.firestore_client = MagicMock()
        fake_fs.client = MagicMock(return_value=self.firestore_client)  # type: ignore[attr-defined]
        fake_fb.firestore = fake_fs  # type: ignore[attr-defined]
        sys.modules["firebase_admin"] = fake_fb
        sys.modules["firebase_admin.firestore"] = fake_fs

        self.encryptor = AESGCMEncryptor(_random_key())
        self.store = FirestoreTokenStore(encryptor=self.encryptor)
        # In-memory fake for the collection() / document() surface
        self.docs: dict[str, dict[str, Any]] = {}

        def _collection(_name: str) -> Any:
            col = MagicMock()

            def _document(uid: str) -> Any:
                doc = MagicMock()
                doc.set.side_effect = lambda payload: self.docs.__setitem__(uid, dict(payload))

                def _get() -> Any:
                    snap = MagicMock()
                    if uid in self.docs:
                        snap.exists = True
                        snap.to_dict.return_value = self.docs[uid]
                    else:
                        snap.exists = False
                        snap.to_dict.return_value = None
                    return snap

                doc.get.side_effect = _get
                doc.delete.side_effect = lambda: self.docs.pop(uid, None)
                return doc

            col.document.side_effect = _document
            return col

        self.firestore_client.collection.side_effect = _collection

    def tearDown(self):
        for name, mod in self._saved_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def test_save_encrypts_before_writing(self):
        tok = _sample_token()
        self.store.save(tok)
        stored = self.docs["user-1"]
        self.assertNotIn("rt-very-secret", stored["refresh_token_enc"])
        self.assertNotIn("secret-xyz", stored["client_secret_enc"])
        self.assertEqual(stored["uid"], "user-1")

    def test_load_roundtrip(self):
        tok = _sample_token()
        self.store.save(tok)
        loaded = self.store.load("user-1")
        assert loaded is not None
        self.assertEqual(loaded.refresh_token, "rt-very-secret")
        self.assertEqual(loaded.client_secret, "secret-xyz")
        self.assertEqual(loaded.scopes, tok.scopes)

    def test_load_missing_returns_none(self):
        self.assertIsNone(self.store.load("nope"))

    def test_delete_removes(self):
        self.store.save(_sample_token())
        self.store.delete("user-1")
        self.assertIsNone(self.store.load("user-1"))

    def test_default_collection_name_is_drive_tokens(self):
        self.store.save(_sample_token())
        self.firestore_client.collection.assert_called_with("drive_tokens")

    def test_custom_collection_name(self):
        store = FirestoreTokenStore(encryptor=self.encryptor, collection="tokens_v2")
        store.save(_sample_token())
        self.firestore_client.collection.assert_called_with("tokens_v2")

    def test_requires_encryptor(self):
        with self.assertRaises(ValueError):
            FirestoreTokenStore(encryptor=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Serialization edge cases
# ---------------------------------------------------------------------------


class TestSerialization(unittest.TestCase):
    def test_revoked_at_preserved(self):
        enc = AESGCMEncryptor(_random_key())
        store = InMemoryTokenStore(encryptor=enc)
        revoked_when = datetime(2026, 4, 18, 10, 0, tzinfo=timezone.utc)
        tok = DriveToken(
            uid="u",
            refresh_token="r",
            client_id="c",
            client_secret="s",
            revoked_at=revoked_when,
        )
        store.save(tok)
        loaded = store.load("u")
        assert loaded is not None
        self.assertEqual(loaded.revoked_at, revoked_when)

    def test_timestamps_roundtrip(self):
        store = InMemoryTokenStore(encryptor=AESGCMEncryptor(_random_key()))
        tok = _sample_token()
        store.save(tok)
        loaded = store.load(tok.uid)
        assert loaded is not None
        self.assertEqual(loaded.created_at, tok.created_at)
        self.assertEqual(loaded.updated_at, tok.updated_at)


class TestFileTokenStore(unittest.TestCase):
    """The on-disk token store — bridges dev (InMemory) and prod (Firestore)."""

    def setUp(self):
        import tempfile

        from openbench.integrations.firebase_auth import FileTokenStore

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = FileTokenStore(root_dir=self._tmp.name, encryptor=NoOpEncryptor())

    def test_round_trip(self):
        tok = _sample_token()
        self.store.save(tok)
        loaded = self.store.load(tok.uid)
        assert loaded is not None
        self.assertEqual(loaded.uid, tok.uid)
        self.assertEqual(loaded.refresh_token, tok.refresh_token)
        self.assertEqual(loaded.openbench_folder_id, tok.openbench_folder_id)

    def test_load_missing_returns_none(self):
        self.assertIsNone(self.store.load("never-saved"))

    def test_delete(self):
        tok = _sample_token()
        self.store.save(tok)
        self.store.delete(tok.uid)
        self.assertIsNone(self.store.load(tok.uid))

    def test_delete_missing_is_noop(self):
        self.store.delete("never-saved")

    def test_persists_across_instances(self):
        from openbench.integrations.firebase_auth import FileTokenStore

        tok = _sample_token("user-persist")
        self.store.save(tok)
        second = FileTokenStore(root_dir=self._tmp.name, encryptor=NoOpEncryptor())
        loaded = second.load("user-persist")
        assert loaded is not None
        self.assertEqual(loaded.refresh_token, tok.refresh_token)

    def test_filename_safe_for_odd_uid(self):
        odd = _sample_token("auth0|oauth2/foo:bar")
        self.store.save(odd)
        files = os.listdir(self._tmp.name)
        self.assertEqual(len(files), 1)
        self.assertNotIn("/", files[0])
        self.assertNotIn(":", files[0])
        loaded = self.store.load("auth0|oauth2/foo:bar")
        assert loaded is not None
        self.assertEqual(loaded.uid, "auth0|oauth2/foo:bar")

    def test_corrupt_file_returns_none(self):
        tok = _sample_token("user-x")
        self.store.save(tok)
        files = [f for f in os.listdir(self._tmp.name) if f.endswith(".json")]
        assert files
        with open(os.path.join(self._tmp.name, files[0]), "w") as fp:
            fp.write("{not valid json")
        self.assertIsNone(self.store.load("user-x"))

    def test_save_is_atomic_no_leftover_tmp(self):
        tok = _sample_token("user-y")
        self.store.save(tok)
        entries = os.listdir(self._tmp.name)
        self.assertTrue(any(e.endswith(".json") for e in entries))
        self.assertFalse(any(e.endswith(".tmp") for e in entries))

    def test_encryptor_applied(self):
        import secrets as _secrets

        from openbench.integrations.firebase_auth import FileTokenStore

        enc = AESGCMEncryptor(_secrets.token_bytes(32))
        store = FileTokenStore(root_dir=self._tmp.name, encryptor=enc)
        tok = _sample_token("user-e")
        store.save(tok)
        loaded = store.load("user-e")
        assert loaded is not None
        self.assertEqual(loaded.refresh_token, tok.refresh_token)

        # Plaintext refresh token must not appear on disk.
        for name in os.listdir(self._tmp.name):
            if name.endswith(".json"):
                with open(os.path.join(self._tmp.name, name)) as fp:
                    blob = fp.read()
                self.assertNotIn(tok.refresh_token, blob)


if __name__ == "__main__":
    unittest.main()
