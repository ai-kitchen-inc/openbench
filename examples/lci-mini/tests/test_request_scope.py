"""Tests for per-request storage / agent / engine wiring (M3).

Validates that every chat endpoint resolves a StorageBackend and a
BaseAgent based on the caller's Firebase UID + Drive connection state,
that existing sessions survive across turns via threadId loading, and
that the agent cache invalidates correctly when a user connects or
disconnects Drive.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_agent_cache() -> None:
    from lci_mini.server.request_scope import reset_agent_cache

    reset_agent_cache()


def _reset_token_store() -> None:
    from lci_mini.auth.drive import reset_token_store_for_tests

    reset_token_store_for_tests()


def _seed_drive_token(
    uid: str,
    *,
    folder_id: str = "folder-user",
    refresh_token: str = "rt-live",
    email: str | None = "jane@example.com",
) -> None:
    """Seed a DriveToken into the (in-memory) token store."""
    from lci_mini.auth.drive import get_token_store

    from openbench.integrations.firebase_auth import DriveToken

    store = get_token_store()
    store.save(
        DriveToken(
            uid=uid,
            refresh_token=refresh_token,
            client_id="client-id",
            client_secret="client-secret",
            scopes=("https://www.googleapis.com/auth/drive.file",),
            openbench_folder_id=folder_id,
            connected_email=email,
        )
    )


# ---------------------------------------------------------------------------
# per_user_local_root
# ---------------------------------------------------------------------------


class TestPerUserLocalRoot:
    """Path derivation varies with auth mode."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / "root"))
        _reset_agent_cache()
        _reset_token_store()
        yield
        _reset_agent_cache()
        _reset_token_store()

    def test_disabled_mode_returns_flat_root(self, monkeypatch, tmp_path):
        from lci_mini.server.request_scope import per_user_local_root

        monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")
        monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
        root = per_user_local_root("dev")
        # Flat — no users/<uid>/ suffix in dev mode
        assert str(root) == str(tmp_path / "root")

    def test_none_mode_returns_flat_root(self, monkeypatch, tmp_path):
        from lci_mini.server.request_scope import per_user_local_root

        monkeypatch.delenv("OPENBENCH_AUTH_DISABLED", raising=False)
        monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
        assert str(per_user_local_root("anonymous")) == str(tmp_path / "root")

    def test_firebase_mode_returns_sharded_path(self, monkeypatch, tmp_path):
        from lci_mini.server.request_scope import per_user_local_root

        monkeypatch.delenv("OPENBENCH_AUTH_DISABLED", raising=False)
        monkeypatch.setenv("FIREBASE_PROJECT_ID", "demo")
        root = per_user_local_root("user-42")
        assert root == tmp_path / "root" / "users" / "us" / "user-42"

    def test_two_firebase_users_get_distinct_dirs(self, monkeypatch):
        from lci_mini.server.request_scope import per_user_local_root

        monkeypatch.setenv("FIREBASE_PROJECT_ID", "demo")
        a = per_user_local_root("alice")
        b = per_user_local_root("bob")
        assert a != b
        assert "alice" in str(a) and "bob" in str(b)

    def test_unsafe_uid_is_hashed(self, monkeypatch, tmp_path):
        from lci_mini.server.request_scope import per_user_local_root

        monkeypatch.setenv("FIREBASE_PROJECT_ID", "demo")
        root = per_user_local_root("../evil")
        assert ".." not in str(root.relative_to(tmp_path / "root" / "users"))


# ---------------------------------------------------------------------------
# resolve_storage_backend
# ---------------------------------------------------------------------------


class TestResolveStorageBackend:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")
        monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / "root"))
        monkeypatch.delenv("LCI_MINI_DRIVE_ROOT", raising=False)
        monkeypatch.delenv("LCI_MINI_SERVICE_ACCOUNT", raising=False)
        _reset_agent_cache()
        _reset_token_store()
        yield
        _reset_agent_cache()
        _reset_token_store()

    def test_without_drive_token_returns_local_backend(self):
        from lci_mini.server.request_scope import resolve_storage_backend

        from openbench import LocalStorageBackend
        from openbench.integrations.firebase_auth import FirebaseUser

        user = FirebaseUser(uid="dev")
        backend = resolve_storage_backend(user=user)
        assert isinstance(backend, LocalStorageBackend)

    def test_with_drive_token_returns_drive_backend(self):
        from lci_mini.server.request_scope import resolve_storage_backend

        from openbench.integrations.firebase_auth import FirebaseUser
        from openbench.integrations.gdrive import GoogleDriveStorageBackend

        _seed_drive_token("dev", folder_id="folder-xyz")
        user = FirebaseUser(uid="dev")
        backend = resolve_storage_backend(user=user)
        assert isinstance(backend, GoogleDriveStorageBackend)
        assert backend.root_folder_id == "folder-xyz"

    def test_legacy_service_account_env_wins(self, monkeypatch):
        """LCI_MINI_DRIVE_ROOT + LCI_MINI_SERVICE_ACCOUNT overrides per-user."""
        from lci_mini.server.request_scope import resolve_storage_backend

        from openbench.integrations.firebase_auth import FirebaseUser
        from openbench.integrations.gdrive import GoogleDriveStorageBackend

        monkeypatch.setenv("LCI_MINI_DRIVE_ROOT", "shared-folder")
        monkeypatch.setenv("LCI_MINI_SERVICE_ACCOUNT", "/fake/sa.json")
        # Seed a DIFFERENT per-user token; service-account mode should win.
        _seed_drive_token("dev", folder_id="personal-folder")
        user = FirebaseUser(uid="dev")
        backend = resolve_storage_backend(user=user)
        assert isinstance(backend, GoogleDriveStorageBackend)
        assert backend.root_folder_id == "shared-folder"

    def test_legacy_env_missing_sa_raises(self, monkeypatch):
        from lci_mini.server.request_scope import resolve_storage_backend

        from openbench.integrations.firebase_auth import FirebaseUser

        monkeypatch.setenv("LCI_MINI_DRIVE_ROOT", "shared-folder")
        monkeypatch.delenv("LCI_MINI_SERVICE_ACCOUNT", raising=False)
        with pytest.raises(RuntimeError, match="LCI_MINI_SERVICE_ACCOUNT"):
            resolve_storage_backend(user=FirebaseUser(uid="dev"))

    def test_drive_build_failure_falls_back_to_local(self, monkeypatch):
        from lci_mini.server import request_scope

        from openbench import LocalStorageBackend
        from openbench.integrations.firebase_auth import FirebaseUser

        _seed_drive_token("dev")
        # Simulate the Drive SDK blowing up on construction
        monkeypatch.setattr(
            request_scope,
            "_build_drive_backend",
            lambda _tok: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        backend = request_scope.resolve_storage_backend(user=FirebaseUser(uid="dev"))
        assert isinstance(backend, LocalStorageBackend)


# ---------------------------------------------------------------------------
# Agent cache
# ---------------------------------------------------------------------------


class TestUserAgentCache:
    @pytest.fixture(autouse=True)
    def _setup(self):
        _reset_agent_cache()
        yield
        _reset_agent_cache()

    def test_same_uid_same_sig_returns_cached_agent(self):
        from lci_mini.server.request_scope import UserAgentCache

        cache = UserAgentCache()
        build_calls = {"n": 0}

        def build():
            build_calls["n"] += 1
            return object()

        a1 = cache.get_or_build("u1", "sig-a", build)
        a2 = cache.get_or_build("u1", "sig-a", build)
        assert a1 is a2
        assert build_calls["n"] == 1

    def test_different_uid_gets_independent_agents(self):
        from lci_mini.server.request_scope import UserAgentCache

        cache = UserAgentCache()
        a = cache.get_or_build("alice", "sig", lambda: object())
        b = cache.get_or_build("bob", "sig", lambda: object())
        assert a is not b

    def test_signature_change_invalidates_cache(self):
        """Connecting/disconnecting Drive changes signature → new agent."""
        from lci_mini.server.request_scope import UserAgentCache

        cache = UserAgentCache()
        before = cache.get_or_build("u1", "local", lambda: object())
        after = cache.get_or_build("u1", "drive:abc", lambda: object())
        assert before is not after

    def test_expired_ttl_rebuilds(self):
        from lci_mini.server.request_scope import UserAgentCache

        cache = UserAgentCache(ttl=0.01)
        a1 = cache.get_or_build("u", "sig", lambda: object())
        import time as _time

        _time.sleep(0.02)
        a2 = cache.get_or_build("u", "sig", lambda: object())
        assert a1 is not a2

    def test_stale_signature_entries_evicted_on_rebuild(self):
        """Old signature for a uid is dropped when a new one is cached."""
        from lci_mini.server.request_scope import UserAgentCache

        cache = UserAgentCache()
        cache.get_or_build("u", "sig-old", lambda: object())
        cache.get_or_build("u", "sig-new", lambda: object())
        # Only (u, sig-new) should remain
        assert ("u", "sig-old") not in cache._cache
        assert ("u", "sig-new") in cache._cache


# ---------------------------------------------------------------------------
# storage_signature
# ---------------------------------------------------------------------------


class TestStorageSignature(unittest.TestCase):
    def test_no_token_is_local(self):
        from lci_mini.server.request_scope import storage_signature

        self.assertEqual(storage_signature(None), "local")

    def test_token_produces_drive_prefix(self):
        from lci_mini.server.request_scope import storage_signature

        from openbench.integrations.firebase_auth import DriveToken

        token = DriveToken(
            uid="u",
            refresh_token="rt-aaaaaaaaaaaaaaaaaaaa",
            client_id="c",
            client_secret="s",
            openbench_folder_id="folder",
        )
        sig = storage_signature(token)
        assert sig.startswith("drive:")

    def test_different_refresh_tokens_differ(self):
        from lci_mini.server.request_scope import storage_signature

        from openbench.integrations.firebase_auth import DriveToken

        def mk(rt: str) -> Any:
            return DriveToken(
                uid="u",
                refresh_token=rt,
                client_id="c",
                client_secret="s",
                openbench_folder_id="folder",
            )

        self.assertNotEqual(
            storage_signature(mk("rt-aaaaaaaaaaaaaaaaaaaaaa")),
            storage_signature(mk("rt-bbbbbbbbbbbbbbbbbbbbbb")),
        )


# ---------------------------------------------------------------------------
# /auth/me now carries Drive status
# ---------------------------------------------------------------------------


class TestAuthMeDriveStatus:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
        monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / "root"))
        monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")
        monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
        monkeypatch.delenv("LCI_MINI_DRIVE_ROOT", raising=False)
        _reset_agent_cache()
        _reset_token_store()
        yield
        _reset_agent_cache()
        _reset_token_store()

    def test_returns_disconnected_by_default(self):
        from lci_mini.server.app import create_app

        client = TestClient(create_app())
        data = client.get("/auth/me").json()
        assert data["uid"] == "dev"
        assert data["drive"]["connected"] is False
        assert data["drive"]["folderId"] is None

    def test_returns_connected_when_token_present(self):
        from lci_mini.server.app import create_app

        _seed_drive_token("dev", folder_id="f-1", email="u@x.com")
        client = TestClient(create_app())
        data = client.get("/auth/me").json()
        assert data["drive"]["connected"] is True
        assert data["drive"]["folderId"] == "f-1"
        assert data["drive"]["email"] == "u@x.com"


# ---------------------------------------------------------------------------
# /sessions loads from the per-user backend
# ---------------------------------------------------------------------------


class TestSessionsEndpointsResolveStorage:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
        monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")
        monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / "root"))
        monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
        monkeypatch.delenv("LCI_MINI_DRIVE_ROOT", raising=False)
        _reset_agent_cache()
        _reset_token_store()
        yield
        _reset_agent_cache()
        _reset_token_store()

    def test_sessions_list_reads_from_resolved_backend(self, tmp_path):
        from lci_mini.server.app import create_app

        from openbench.chat.session import ChatSession
        from openbench.chat.stores.sqlite import SQLiteSessionStore

        # Seed at the flat "dev" root — same path resolve_storage_backend
        # produces in disabled-auth mode
        sessions_db = tmp_path / "root" / "sessions.db"
        sessions_db.parent.mkdir(parents=True, exist_ok=True)
        store = SQLiteSessionStore(str(sessions_db))
        session = ChatSession(session_id="s-seed", title="Seeded")
        session.add_user_message("hi")
        store.save(session)

        client = TestClient(create_app())
        resp = client.get("/sessions")
        assert resp.status_code == 200
        ids = {s["sessionId"] for s in resp.json()}
        assert "s-seed" in ids

    def test_get_unknown_session_returns_404(self):
        from lci_mini.server.app import create_app

        client = TestClient(create_app())
        assert client.get("/sessions/does-not-exist").status_code == 404


# ---------------------------------------------------------------------------
# /downloads/{id}/{name} resolves via storage.output_store()
# ---------------------------------------------------------------------------


class TestDownloadsEndpointResolvesOutputStore:
    """The dynamic download route must go through the per-user
    output_store so Drive-connected users get THEIR files, and local
    users get files from THEIR per-user dir — no cross-contamination."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-test-key")
        monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")
        monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / "root"))
        monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
        monkeypatch.delenv("LCI_MINI_DRIVE_ROOT", raising=False)
        _reset_agent_cache()
        _reset_token_store()
        yield
        _reset_agent_cache()
        _reset_token_store()

    def test_download_returns_file_bytes(self, tmp_path):
        from lci_mini.server.app import create_app

        from openbench.chat.files import LocalFileStore

        # Seed a file via the SAME root the app resolves to.
        store = LocalFileStore(upload_dir=str(tmp_path / "root" / "downloads"))
        stored = store.store("result.xlsx", b"fake-xlsx-bytes", "application/vnd.ms-excel")

        client = TestClient(create_app())
        resp = client.get(f"/downloads/{stored.id}/{stored.name}")
        assert resp.status_code == 200
        assert resp.content == b"fake-xlsx-bytes"
        # Filename preserved in the Content-Disposition so the browser
        # downloads under the original name, not the file id.
        cd = resp.headers.get("content-disposition", "")
        assert "result.xlsx" in cd

    def test_download_unknown_id_returns_404(self):
        from lci_mini.server.app import create_app

        client = TestClient(create_app())
        resp = client.get("/downloads/never-stored/out.xlsx")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /awp preserves session across turns via threadId
# ---------------------------------------------------------------------------


class TestSessionPersistenceAcrossTurns:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENBENCH_AUTH_DISABLED", "1")
        monkeypatch.setenv("LCI_MINI_STORAGE_ROOT", str(tmp_path / "root"))
        monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
        _reset_agent_cache()
        _reset_token_store()
        yield
        _reset_agent_cache()
        _reset_token_store()

    def test_resolve_session_for_thread_loads_existing(self, tmp_path):
        from lci_mini.server.request_scope import resolve_session_for_thread

        from openbench.chat.session import ChatSession
        from openbench.chat.stores.sqlite import SQLiteSessionStore

        db = tmp_path / "sessions.db"
        store = SQLiteSessionStore(str(db))
        seeded = ChatSession(session_id="s-xyz", title="Seeded")
        seeded.add_user_message("prior turn content")
        store.save(seeded)

        loaded = resolve_session_for_thread("s-xyz", store)
        assert loaded.session_id == "s-xyz"
        # History survives
        assert any("prior turn" in m.content for m in loaded.messages if m.content)

    def test_resolve_session_for_thread_creates_new_when_missing(self, tmp_path):
        from lci_mini.server.request_scope import resolve_session_for_thread

        from openbench.chat.stores.sqlite import SQLiteSessionStore

        store = SQLiteSessionStore(str(tmp_path / "sessions.db"))
        loaded = resolve_session_for_thread("brand-new-thread", store)
        assert loaded.session_id == "brand-new-thread"
        assert len(loaded.messages) == 0

    def test_resolve_session_no_thread_id_returns_fresh(self):
        from lci_mini.server.request_scope import resolve_session_for_thread

        loaded = resolve_session_for_thread(None, None)
        assert len(loaded.messages) == 0

    def test_resolve_session_swallows_store_load_errors(self):
        from lci_mini.server.request_scope import resolve_session_for_thread

        broken = MagicMock()
        broken.load.side_effect = RuntimeError("db fried")
        loaded = resolve_session_for_thread("some-id", broken)
        # Gets a fresh session keyed on the requested id — chat doesn't crash
        assert loaded.session_id == "some-id"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
