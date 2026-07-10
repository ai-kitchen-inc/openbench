"""FastAPI wrapper: General Chat backend + local auth + role guard.

``build_app()`` composes the unmodified General Chat ``create_app()``
and layers on top:

- ``POST /auth/login`` / ``POST /auth/logout`` / ``GET /auth/me`` —
  local two-account auth (see :mod:`controlled_source_chat.auth`).
- An outermost HTTP middleware that requires a bearer token on every
  protected path, maps the account to the General Chat data owner
  (``request.state.owner_override``), and blocks guests from all
  source/tool management endpoints.
- ``GET /controlled/sources`` — read-only view of the admin-curated
  source list so guests can fact-check citations.

Firebase auth stays disabled (``OPENBENCH_AUTH_DISABLED=1``); this
middleware is the only gatekeeper.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from controlled_source_chat.auth import (
    ROLE_GUEST,
    resolve_bearer,
    issue_token,
    verify_credentials,
)
from general_chat.server.app import _requires_auth_path, create_app
from general_chat.sources import build_source_store

_PREVIEW_CHARS = 500

# Endpoint families guests must not reach. Sources and tools are curated by
# the admin; guests only chat. Each entry is (methods, prefix) where methods
# is None for "all methods".
_GUEST_BLOCKED: tuple[tuple[frozenset[str] | None, str], ...] = (
    (None, "/chat/upload"),
    (None, "/chat/uploads"),
    (None, "/chat/attachments"),
    (None, "/chat/sources"),
    (None, "/mcp"),
    (None, "/toolhive"),
    (None, "/functions"),
    (None, "/dashboard"),
    (None, "/persona"),
    (None, "/skills"),
    (None, "/image-search"),
)


def shared_sources_owner() -> str:
    return os.getenv("GENERAL_CHAT_SHARED_SOURCES_OWNER", "admin").strip().lower() or "admin"


def shared_sources_thread() -> str:
    return os.getenv("GENERAL_CHAT_SHARED_SOURCES_THREAD", "controlled-sources").strip() or (
        "controlled-sources"
    )


def _is_guest_blocked(method: str, path: str) -> bool:
    for methods, prefix in _GUEST_BLOCKED:
        if path == prefix or path.startswith(f"{prefix}/"):
            if methods is None or method.upper() in methods:
                return True
    return False


def build_app() -> FastAPI:
    app = create_app()
    storage_root = os.getenv("GENERAL_CHAT_STORAGE_ROOT", "").strip()
    if not storage_root:
        # Must match create_app's storage root, so require the explicit env
        # (server.py sets it) instead of guessing a second default here.
        raise RuntimeError(
            "GENERAL_CHAT_STORAGE_ROOT must be set before build_app() "
            "so the curated-source view reads the same store as General Chat."
        )
    source_store = build_source_store(storage_root)

    @app.post("/auth/login")
    async def login(request: Request) -> dict:
        body = await request.json()
        account = verify_credentials(
            str(body.get("username") or ""), str(body.get("password") or "")
        )
        if account is None:
            raise HTTPException(status_code=401, detail="Invalid username or password.")
        return {
            "token": issue_token(account),
            "username": account.username,
            "role": account.role,
        }

    @app.post("/auth/logout")
    async def logout() -> dict:
        # Tokens are stateless; the client discards its copy.
        return {"ok": True}

    @app.get("/auth/me")
    async def me(request: Request) -> dict:
        account = resolve_bearer(request.headers.get("authorization", ""))
        if account is None:
            raise HTTPException(
                status_code=401,
                detail="Authentication required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return {"username": account.username, "role": account.role}

    @app.get("/controlled/sources")
    async def controlled_sources() -> list[dict]:
        """Read-only curated source list — the guest fact-check surface."""
        records = source_store.for_owner(shared_sources_owner()).list(shared_sources_thread())
        payload = []
        for record in records:
            item = record.to_dict(include_text=False)
            text = (record.text or "").strip()
            item["textPreview"] = text[:_PREVIEW_CHARS]
            item["textTruncated"] = len(text) > _PREVIEW_CHARS
            payload.append(item)
        return payload

    @app.middleware("http")
    async def local_auth_middleware(request: Request, call_next):
        path = request.url.path
        if (
            request.method.upper() == "OPTIONS"
            or path == "/health"
            or path.startswith("/auth/")
        ):
            return await call_next(request)
        if not (_requires_auth_path(path) or path.startswith("/controlled")):
            return await call_next(request)
        account = resolve_bearer(request.headers.get("authorization", ""))
        if account is None:
            return JSONResponse(
                {"detail": "Authentication required."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.owner_override = account.username
        if account.role == ROLE_GUEST and _is_guest_blocked(request.method, path):
            return JSONResponse(
                {"detail": "Guests cannot manage sources or tools."},
                status_code=403,
            )
        return await call_next(request)

    return app
