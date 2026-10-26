"""Credential redaction for database URLs (OpenBench fork addition).

Tool results and log lines must never carry the DSN password: the MCP
server's output is rendered verbatim into the chat for any signed-in user.
This module is dependency-free so it can be imported by the stdio server,
the HTTP variant, and the test suite alike.
"""

from __future__ import annotations

import re

_USERINFO_RE = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)(?P<userinfo>[^@/\s]*)@")

MASK = "***"


def redact_dsn(url: str | None) -> str:
    """Return ``url`` with the userinfo password replaced by ``***``.

    ``postgresql://user:secret@host/db`` -> ``postgresql://user:***@host/db``.
    URLs without a password (or without userinfo at all) are returned
    unchanged apart from stripping whitespace. ``None``/empty -> ``""``.
    Query-string style secrets (``?password=``) are masked too, since some
    drivers accept them there.
    """
    if not url:
        return ""
    text = str(url).strip()
    match = _USERINFO_RE.match(text)
    if match:
        userinfo = match.group("userinfo")
        user, sep, _password = userinfo.partition(":")
        if sep:
            text = f"{match.group('scheme')}{user}:{MASK}@{text[match.end() :]}"
    return re.sub(
        r"(?i)([?&](?:password|passwd|pwd)=)[^&#\s]*",
        rf"\1{MASK}",
        text,
    )
