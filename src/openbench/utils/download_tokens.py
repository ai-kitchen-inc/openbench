"""HMAC-signed, expiring tokens for ``/downloads`` links.

Agent-generated exports (Excel, PDF, Markdown, dashboards) are served
from a public download mount because they render as plain anchor links,
and browser navigation carries no Authorization header. Signing embeds
the auth in the URL itself: ``?exp=<unix>&sig=<hmac>``.

Enabled only when ``OPENBENCH_DOWNLOAD_SECRET`` is set. With no secret,
:func:`sign_download_url` is a no-op and :func:`verify_download_token`
always passes, so deployments and examples that never set the secret
keep today's public-by-unguessable-URL behavior bit-identical.

The signature covers only the served filename (not the full URL), so a
token stays valid regardless of the URL base — the dashboard-generator
MCP runs out-of-process and only knows base + filename.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

_DEFAULT_TTL_SECONDS = 86400  # 24 hours


def download_secret() -> str | None:
    """Return the shared signing secret, or ``None`` when signing is off."""
    secret = os.environ.get("OPENBENCH_DOWNLOAD_SECRET", "").strip()
    return secret or None


def download_ttl_seconds() -> int:
    """Signed-link lifetime; ``OPENBENCH_DOWNLOAD_TTL_SECONDS`` overrides."""
    raw = os.environ.get("OPENBENCH_DOWNLOAD_TTL_SECONDS", "")
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_TTL_SECONDS
    return value if value > 0 else _DEFAULT_TTL_SECONDS


def _signature(name: str, exp: int, secret: str) -> str:
    payload = f"{name}:{exp}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def sign_download_url(url: str, *, now: float | None = None) -> str:
    """Append ``?exp=&sig=`` to a download URL (identity when signing is off)."""
    secret = download_secret()
    if secret is None:
        return url
    name = url.rsplit("/", 1)[-1]
    exp = int(now if now is not None else time.time()) + download_ttl_seconds()
    return f"{url}?exp={exp}&sig={_signature(name, exp, secret)}"


def verify_download_token(name: str, exp: str, sig: str, *, now: float | None = None) -> bool:
    """Check a signed-download token (always ``True`` when signing is off)."""
    secret = download_secret()
    if secret is None:
        return True
    try:
        exp_val = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_val < (now if now is not None else time.time()):
        return False
    return hmac.compare_digest(_signature(name, exp_val, secret), sig or "")
