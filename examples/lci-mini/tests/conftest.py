"""Pytest shared fixtures for the lci-mini test suite.

Why this file exists
--------------------

``create_app()`` calls :func:`dotenv.load_dotenv` on startup, which means
any ``examples/lci-mini/.env`` on disk leaks into ``os.environ`` during
tests. For developers who have a real Firebase config in their .env
(FIREBASE_PROJECT_ID, VITE_FIREBASE_*, etc.), this collides with tests
that set OPENBENCH_AUTH_DISABLED=1 for dev bypass and triggers a
``RuntimeError`` from ``AuthConfig.from_env``.

The autouse fixture below clears every env var the auth + storage
layers consult, so each test starts from a deterministic blank slate
and must explicitly opt into any auth mode it wants to exercise.
"""

from __future__ import annotations

import pytest

_AUTH_ENV_VARS = (
    "FIREBASE_PROJECT_ID",
    "FIREBASE_ADMIN_CREDENTIALS",
    "OPENBENCH_AUTH_DISABLED",
    "GOOGLE_OAUTH_CLIENT_SECRETS",
    "DRIVE_OAUTH_REDIRECT_URL",
    "SESSION_SECRET",
    "DRIVE_TOKEN_ENCRYPTION_KEY",
    "LCI_MINI_DRIVE_ROOT",
    "LCI_MINI_SERVICE_ACCOUNT",
)


@pytest.fixture(autouse=True)
def _isolate_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with a clean auth/storage env.

    Individual tests re-set whichever variables they need via
    ``monkeypatch.setenv`` — this fixture just guarantees nothing
    leaks in from the developer's local .env.
    """
    for name in _AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
