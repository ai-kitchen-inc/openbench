"""Account and admin REST surface for General Chat.

Registered inside ``create_app()`` **before** the SPA static catch-all
so route ordering never needs post-hoc fixing. Uses the ``/account/*``
and ``/admin/*`` prefixes — never ``/auth/*``, which the
controlled-source-chat wrapper claims for itself after ``create_app()``
returns.

The auth middleware already blocks non-admins from ``/admin*``;
handlers still call :func:`require_role` as defense in depth.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status

from general_chat.admin_store import DuplicateUserError, UnknownUserError
from general_chat.capabilities import CapabilityCache, capability_definitions_payload
from general_chat.persona_templates import (
    PERSONA_SETTINGS_KEY,
    get_template,
    normalize_persona_settings,
    persona_from_settings,
    settings_from_template,
    templates_payload,
)
from general_chat.server.auth import LOCAL_OWNER, auth_enabled, current_owner, current_role

logger = logging.getLogger(__name__)


def require_role(request: Request, role: str) -> None:
    """403 unless the request carries the given role."""
    if current_role(request) != role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: memerlukan peran admin.",
        )


def _requester_email(request: Request) -> str:
    if not auth_enabled():
        return LOCAL_OWNER
    return current_owner(request)


def register_admin_routes(
    app: FastAPI,
    *,
    user_store: Any,
    settings_store: Any,
    capability_cache: CapabilityCache,
    agent_holder: Any,
) -> None:
    """Register /account/* and /admin/* endpoints."""

    # ------------------------------------------------------------------
    # Account (any authenticated user)
    # ------------------------------------------------------------------

    @app.get("/account/me")
    async def account_me(request: Request) -> dict:
        role = current_role(request)
        email = _requester_email(request)
        record = user_store.get(email) if email != LOCAL_OWNER else None
        if role == "admin":
            flags = {
                flag_id: True
                for flag_id in capability_cache.value["roles"].get("user", {})
            }
        else:
            flags = dict(capability_cache.value["roles"].get(role, {}))
        return {
            "email": email,
            "role": role,
            "displayName": record.display_name if record else "",
            "capabilities": flags,
            "global": dict(capability_cache.value["global"]),
        }

    # ------------------------------------------------------------------
    # Admin: users
    # ------------------------------------------------------------------

    @app.get("/admin/users")
    async def list_users(request: Request) -> dict:
        require_role(request, "admin")
        return {"users": [record.to_dict() for record in user_store.list_users()]}

    @app.post("/admin/users", status_code=status.HTTP_201_CREATED)
    async def add_user(request: Request) -> dict:
        require_role(request, "admin")
        body = await request.json()
        email = str(body.get("email", ""))
        role = str(body.get("role", "user"))
        display_name = str(body.get("displayName", "") or "")
        try:
            record = user_store.add(
                email,
                role,
                display_name=display_name,
                added_by=_requester_email(request),
            )
        except DuplicateUserError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pengguna dengan email tersebut sudah terdaftar.",
            ) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return record.to_dict()

    @app.patch("/admin/users/{email}")
    async def update_user(email: str, request: Request) -> dict:
        require_role(request, "admin")
        body = await request.json()
        role = body.get("role")
        display_name = body.get("displayName")
        existing = user_store.get(email)
        if existing is None:
            raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")
        if (
            role is not None
            and existing.role == "admin"
            and str(role) != "admin"
            and user_store.count_admins() <= 1
        ):
            raise HTTPException(
                status_code=400,
                detail="Tidak dapat menurunkan peran admin terakhir.",
            )
        try:
            record = user_store.update(
                email,
                role=str(role) if role is not None else None,
                display_name=str(display_name) if display_name is not None else None,
            )
        except UnknownUserError:
            raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.") from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return record.to_dict()

    @app.delete("/admin/users/{email}")
    async def delete_user(email: str, request: Request) -> dict:
        require_role(request, "admin")
        normalized = email.strip().lower()
        if normalized == _requester_email(request):
            raise HTTPException(
                status_code=400,
                detail="Tidak dapat menghapus akun sendiri.",
            )
        existing = user_store.get(normalized)
        if existing is None:
            raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")
        if existing.role == "admin" and user_store.count_admins() <= 1:
            raise HTTPException(
                status_code=400,
                detail="Tidak dapat menghapus admin terakhir.",
            )
        user_store.remove(normalized)
        return {"ok": True, "email": normalized}

    # ------------------------------------------------------------------
    # Admin: capabilities
    # ------------------------------------------------------------------

    @app.get("/admin/capabilities")
    async def get_capabilities(request: Request) -> dict:
        require_role(request, "admin")
        return {
            "definitions": capability_definitions_payload(),
            **capability_cache.value,
        }

    @app.put("/admin/capabilities")
    async def put_capabilities(request: Request) -> dict:
        require_role(request, "admin")
        body = await request.json()
        previous_global = dict(capability_cache.value["global"])
        merged = capability_cache.update(body, updated_by=_requester_email(request))
        # Global flags steer agent construction (which skills load) —
        # rebuild only when one actually flipped.
        if merged["global"] != previous_global:
            try:
                agent_holder.rebuild()
            except Exception as exc:
                logger.exception("Agent rebuild after capability change failed")
                raise HTTPException(
                    status_code=500,
                    detail=f"Kemampuan tersimpan, tetapi pemuatan ulang agen gagal: {exc}",
                ) from exc
        return {
            "definitions": capability_definitions_payload(),
            **merged,
        }

    # ------------------------------------------------------------------
    # Admin: persona
    # ------------------------------------------------------------------

    def _persona_state() -> dict:
        stored = normalize_persona_settings(settings_store.get(PERSONA_SETTINGS_KEY))
        agent = agent_holder.agent
        persona = getattr(agent, "_persona", None)
        active = persona.summary() if persona else {}
        if stored is not None:
            source = "db"
        else:
            import os

            source = "env" if os.getenv("GENERAL_CHAT_SOUL_DIR") else "files"
        return {"settings": stored, "source": source, "active": active}

    @app.get("/admin/persona")
    async def get_admin_persona(request: Request) -> dict:
        require_role(request, "admin")
        return _persona_state()

    @app.get("/admin/persona/templates")
    async def get_persona_templates(request: Request) -> dict:
        require_role(request, "admin")
        return {"templates": templates_payload()}

    @app.put("/admin/persona")
    async def put_admin_persona(request: Request) -> dict:
        require_role(request, "admin")
        body = await request.json()
        template_id = str(body.get("template", "") or "").strip()
        if template_id and not any(
            body.get(fld) for fld in ("soul", "style", "agents", "goal")
        ):
            template = get_template(template_id)
            if template is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Template persona tidak dikenal: {template_id}",
                )
            value = settings_from_template(template)
        else:
            value = normalize_persona_settings(body)
            if value is None:
                raise HTTPException(
                    status_code=400,
                    detail="Persona kosong: isi minimal salah satu dari soul/style/agents.",
                )
        # Sanity-check the stored value resolves to a persona before saving.
        persona, _, _ = persona_from_settings(value)
        if persona is None:
            raise HTTPException(
                status_code=400,
                detail="Persona kosong: isi minimal salah satu dari soul/style/agents.",
            )
        settings_store.set(PERSONA_SETTINGS_KEY, value, updated_by=_requester_email(request))
        try:
            agent_holder.rebuild()
        except Exception as exc:
            logger.exception("Agent rebuild after persona change failed")
            raise HTTPException(
                status_code=500,
                detail=(
                    "Persona tersimpan, tetapi pemuatan ulang agen gagal — "
                    f"agen lama masih aktif: {exc}"
                ),
            ) from exc
        return {"ok": True, **_persona_state()}
