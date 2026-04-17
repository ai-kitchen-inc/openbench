"""Firebase Authentication integration for OpenBench.

Optional — install via ``pip install openbench[firebase]``.

Currently ships:

- :class:`FirebaseUser` — dataclass shape of an authenticated user.
- :class:`FirebaseIDVerifier` — verifies Firebase ID tokens (JWTs)
  against a configured Firebase project and returns a
  :class:`FirebaseUser`.

The package is framework-agnostic — it does not depend on FastAPI,
Flask, or any HTTP layer. Consumers wire it into their own
framework by reading the ``Authorization: Bearer <token>`` header,
calling :meth:`FirebaseIDVerifier.verify`, and handling the returned
:class:`FirebaseUser` (or specific :class:`InvalidTokenError`
subclasses on failure).

See ``.tmp/RFC-AUTH-LAYER.md`` §4 for the integration design.
"""

from __future__ import annotations

from openbench.integrations.firebase_auth.drive_oauth import (
    ClientSecrets,
    OAuthError,
    TokenResponse,
    build_authorize_url,
    build_credentials,
    exchange_code,
    load_client_secrets,
    refresh_access_token,
    revoke_refresh_token,
)
from openbench.integrations.firebase_auth.token_store import (
    AESGCMEncryptor,
    DriveToken,
    Encryptor,
    FirestoreTokenStore,
    InMemoryTokenStore,
    NoOpEncryptor,
    TokenStore,
)
from openbench.integrations.firebase_auth.verifier import (
    FirebaseIDVerifier,
    FirebaseUser,
    InvalidTokenError,
    TokenExpiredError,
    TokenRevokedError,
    WrongProjectError,
)

__all__ = [
    "AESGCMEncryptor",
    "ClientSecrets",
    "DriveToken",
    "Encryptor",
    "FirebaseIDVerifier",
    "FirebaseUser",
    "FirestoreTokenStore",
    "InMemoryTokenStore",
    "InvalidTokenError",
    "NoOpEncryptor",
    "OAuthError",
    "TokenExpiredError",
    "TokenResponse",
    "TokenRevokedError",
    "TokenStore",
    "WrongProjectError",
    "build_authorize_url",
    "build_credentials",
    "exchange_code",
    "load_client_secrets",
    "refresh_access_token",
    "revoke_refresh_token",
]
