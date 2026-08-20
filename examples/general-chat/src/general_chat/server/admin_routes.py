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

from fastapi import FastAPI, HTTPException, Request, Response, status

from general_chat.admin_store import DuplicateUserError, UnknownUserError
from general_chat.capabilities import CapabilityCache, capability_definitions_payload
from general_chat.pricing import invalid_pricing_values
from general_chat.privacy import PrivacySettingsCache, invalid_privacy_values
from general_chat.quotas import invalid_quota_values, quota_status
from general_chat.usage_store import current_month
from general_chat.persona_templates import (
    PERSONA_SETTINGS_KEY,
    get_template,
    normalize_persona_settings,
    persona_from_settings,
    settings_from_template,
    templates_payload,
)
from general_chat.runtime_settings import (
    RuntimeSettingsCache,
    invalid_runtime_values,
    runtime_settings_options,
)
from general_chat.server.auth import LOCAL_OWNER, auth_enabled, current_owner, current_role
from general_chat.source_index import set_vector_store

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
    runtime_settings_cache: RuntimeSettingsCache,
    agent_holder: Any,
    privacy_cache: PrivacySettingsCache,
    retention_sweep: Any,
    audit_store: Any,
    audit: Any,
    pricing_cache: Any,
    quota_cache: Any,
    usage_store: Any,
) -> None:
    """Register /account/* and /admin/* endpoints.

    ``audit`` is the app's ``_audit(request, action, target, detail)``
    helper; ``audit_store`` backs the read/export endpoints.
    """

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
            # Local-dev signal: when True the UI may offer the
            # "view as user" role toggle (X-Local-Role header).
            "authDisabled": not auth_enabled(),
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
        audit(request, "user.add", target=record.email, detail={"role": record.role})
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
        audit(request, "user.update", target=record.email, detail={"role": record.role})
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
        audit(request, "user.delete", target=normalized)
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
        audit(request, "capabilities.update")
        return {
            "definitions": capability_definitions_payload(),
            **merged,
        }

    # ------------------------------------------------------------------
    # Admin: runtime model settings
    # ------------------------------------------------------------------

    @app.get("/admin/runtime-settings")
    async def get_runtime_settings(request: Request) -> dict:
        require_role(request, "admin")
        return {
            "values": dict(runtime_settings_cache.value),
            "options": runtime_settings_options(),
        }

    @app.put("/admin/runtime-settings")
    async def put_runtime_settings(request: Request) -> dict:
        require_role(request, "admin")
        body = await request.json()
        invalid = invalid_runtime_values(body)
        if invalid:
            key, value = next(iter(invalid.items()))
            raise HTTPException(
                status_code=400,
                detail=f"Nilai tidak valid untuk {key}: {value!r}",
            )
        previous_llm_model = runtime_settings_cache.value.get("llm_model")
        previous_vector_store = runtime_settings_cache.value.get("vector_store")
        merged = runtime_settings_cache.update(body, updated_by=_requester_email(request))
        vector_store_changed = merged.get("vector_store") != previous_vector_store
        if vector_store_changed:
            set_vector_store(merged.get("vector_store"))
        # The LLM model steers agent construction, and the vector store is
        # captured by the agent's source-retrieval bindings — rebuild once
        # when either actually changed (same contract as capability flags).
        if merged.get("llm_model") != previous_llm_model or vector_store_changed:
            try:
                agent_holder.rebuild()
            except Exception as exc:
                logger.exception("Agent rebuild after settings change failed")
                raise HTTPException(
                    status_code=500,
                    detail=f"Pengaturan tersimpan, tetapi pemuatan ulang agen gagal: {exc}",
                ) from exc
        audit(request, "runtime_settings.update", detail=dict(merged))
        return {"values": merged, "options": runtime_settings_options()}

    # ------------------------------------------------------------------
    # Admin: privacy
    # ------------------------------------------------------------------

    def _privacy_payload() -> dict:
        return {
            "retentionDays": privacy_cache.value["retention_days"],
            "piiRedaction": privacy_cache.value["pii_redaction"],
        }

    @app.get("/admin/privacy")
    async def get_privacy(request: Request) -> dict:
        require_role(request, "admin")
        return _privacy_payload()

    @app.put("/admin/privacy")
    async def put_privacy(request: Request) -> dict:
        require_role(request, "admin")
        body = await request.json()
        partial = {}
        if isinstance(body, dict):
            if "retentionDays" in body:
                partial["retention_days"] = body["retentionDays"]
            if "piiRedaction" in body:
                partial["pii_redaction"] = body["piiRedaction"]
        invalid = invalid_privacy_values(partial)
        if invalid:
            key, value = next(iter(invalid.items()))
            raise HTTPException(
                status_code=400,
                detail=f"Nilai pengaturan privasi tidak valid untuk {key}: {value!r}",
            )
        privacy_cache.update(partial, updated_by=_requester_email(request))
        audit(request, "privacy.update", detail=dict(privacy_cache.value))
        return _privacy_payload()

    @app.post("/admin/privacy/sweep")
    async def run_privacy_sweep(request: Request) -> dict:
        require_role(request, "admin")
        summary = retention_sweep()
        audit(request, "privacy.sweep", detail=dict(summary))
        return {
            "deletedSessions": summary["deleted_sessions"],
            "ownersScanned": summary["owners_scanned"],
        }

    # ------------------------------------------------------------------
    # Usage metering (user-facing summary + admin dashboard)
    # ------------------------------------------------------------------

    def _month_param(month: str) -> str:
        month = month.strip()
        if month and len(month) == 7 and month[4] == "-":
            return month
        return current_month()

    @app.get("/account/usage")
    async def account_usage(request: Request) -> dict:
        """The requester's own usage — available to every role (warn-only)."""
        email = _requester_email(request)
        month = current_month()
        summary = usage_store.summarize_owner(email, month)
        limit = quota_cache.quota_for(email)
        return {
            "month": month,
            **summary,
            "quota": quota_status(limit, summary["totalTokens"]),
            "recent": [record.to_dict() for record in usage_store.recent(email, limit=20)],
        }

    @app.get("/admin/usage")
    async def admin_usage(request: Request, month: str = "") -> dict:
        require_role(request, "admin")
        resolved_month = _month_param(month)
        users = usage_store.summarize_all(resolved_month)
        totals = {
            "promptTokens": sum(u["promptTokens"] for u in users),
            "completionTokens": sum(u["completionTokens"] for u in users),
            "totalTokens": sum(u["totalTokens"] for u in users),
            "costUsd": sum(u["costUsd"] for u in users),
            "calls": sum(u["calls"] for u in users),
        }
        enriched = []
        for user in users:
            limit = quota_cache.quota_for(user["owner"])
            enriched.append(
                {**user, "quota": quota_status(limit, user["totalTokens"])}
            )
        return {"month": resolved_month, "totals": totals, "users": enriched}

    @app.get("/admin/pricing")
    async def get_pricing(request: Request) -> dict:
        require_role(request, "admin")
        return dict(pricing_cache.value)

    @app.put("/admin/pricing")
    async def put_pricing(request: Request) -> dict:
        require_role(request, "admin")
        body = await request.json()
        invalid = invalid_pricing_values(body)
        if invalid:
            key, value = next(iter(invalid.items()))
            raise HTTPException(
                status_code=400,
                detail=f"Nilai harga tidak valid untuk {key}: {value!r}",
            )
        merged = pricing_cache.update(body, updated_by=_requester_email(request))
        audit(request, "pricing.update")
        return dict(merged)

    @app.get("/admin/quotas")
    async def get_quotas(request: Request) -> dict:
        require_role(request, "admin")
        return {
            "defaultMonthlyTokens": quota_cache.value["default_monthly_tokens"],
            "overrides": dict(quota_cache.value["overrides"]),
        }

    @app.put("/admin/quotas")
    async def put_quotas(request: Request) -> dict:
        require_role(request, "admin")
        body = await request.json()
        partial = {}
        if isinstance(body, dict):
            if "defaultMonthlyTokens" in body:
                partial["default_monthly_tokens"] = body["defaultMonthlyTokens"]
            if "overrides" in body:
                partial["overrides"] = body["overrides"]
        invalid = invalid_quota_values(partial)
        if invalid:
            key, value = next(iter(invalid.items()))
            raise HTTPException(
                status_code=400,
                detail=f"Nilai kuota tidak valid untuk {key}: {value!r}",
            )
        merged = quota_cache.update(partial, updated_by=_requester_email(request))
        audit(request, "quota.update")
        return {
            "defaultMonthlyTokens": merged["default_monthly_tokens"],
            "overrides": dict(merged["overrides"]),
        }

    # ------------------------------------------------------------------
    # Admin: audit trail
    # ------------------------------------------------------------------

    def _audit_filters(
        actor: str, action: str, since: str, until: str
    ) -> dict[str, str | None]:
        return {
            "actor": actor.strip() or None,
            "action": action.strip() or None,
            "since": since.strip() or None,
            "until": until.strip() or None,
        }

    @app.get("/admin/audit")
    async def list_audit(
        request: Request,
        actor: str = "",
        action: str = "",
        since: str = "",
        until: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        require_role(request, "admin")
        filters = _audit_filters(actor, action, since, until)
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        items = audit_store.list(**filters, limit=limit, offset=offset)
        return {
            "items": [record.to_dict() for record in items],
            "total": audit_store.count(**filters),
        }

    @app.get("/admin/audit/export")
    async def export_audit(
        request: Request,
        actor: str = "",
        action: str = "",
        since: str = "",
        until: str = "",
    ) -> Response:
        require_role(request, "admin")
        filters = _audit_filters(actor, action, since, until)
        audit(request, "audit.export", detail={k: v for k, v in filters.items() if v})

        import csv
        import io
        import json as json_module
        from datetime import date

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["ts", "actor", "role", "action", "target", "status", "detail"])
        offset = 0
        page_size = 500
        while True:
            page = audit_store.list(**filters, limit=page_size, offset=offset)
            for record in page:
                writer.writerow(
                    [
                        record.ts,
                        record.actor,
                        record.role,
                        record.action,
                        record.target,
                        record.status,
                        json_module.dumps(record.detail, ensure_ascii=False),
                    ]
                )
            if len(page) < page_size:
                break
            offset += page_size
        filename = f"audit-{date.today().isoformat()}.csv"
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

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
        audit(request, "persona.update")
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
