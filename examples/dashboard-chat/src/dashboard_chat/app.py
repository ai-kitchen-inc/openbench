"""FastAPI app for Dashboard Chat.

Composes the whole backend: local bearer auth, per-user database
connections (schema introspection only), the per-user dashboard spec
store, guarded chart-data execution, and the single-conversation AG-UI
chat stream. The LLM never sees row data — the only endpoints that
touch rows serve the frontend charts directly.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from dashboard_chat.agent import create_agent
from dashboard_chat.auth import (
    ROLE_ADMIN,
    Account,
    issue_token,
    resolve_bearer,
    verify_credentials,
)
from dashboard_chat.connections import (
    build_connection_store,
    introspect_schema,
    normalize_sqlite_url,
    redact_url,
    test_connection,
)
from dashboard_chat.dashboards import build_dashboard_store
from dashboard_chat.handler import DashboardChatHandler, session_id_for
from dashboard_chat.sqlguard import execute_select
from dashboard_chat.users import (
    BuiltinUserError,
    DuplicateUserError,
    UnknownUserError,
    get_user_store,
    storage_root,
)
from openbench.chat.engine import ChatEngine
from openbench.chat.stores.sqlite import SQLiteSessionStore
from openbench.intelligence.memory import SQLiteMemoryStore

logger = logging.getLogger(__name__)

# Every route family except login/health requires a bearer token.
_PUBLIC_PATHS = ("/health", "/auth/login")


def _account_from(request: Request) -> Account:
    account = getattr(request.state, "account", None)
    if account is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return account


def _require_admin(request: Request) -> Account:
    account = _account_from(request)
    if account.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return account


def create_app() -> FastAPI:
    root = storage_root()
    root.mkdir(parents=True, exist_ok=True)

    connection_store = build_connection_store(root)
    dashboard_store = build_dashboard_store(root)
    memory_db = os.getenv("DASHBOARD_CHAT_MEMORY_DB", "").strip() or str(root / "memory.db")
    memory_store = SQLiteMemoryStore(db_path=memory_db)
    session_store = SQLiteSessionStore(root / "sessions.db")

    agent = create_agent()
    engine = ChatEngine(agent=agent, session_store=session_store)
    handler = DashboardChatHandler(
        engine,
        memory_store=memory_store,
        connection_store=connection_store,
        dashboard_store=dashboard_store,
    )

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── auth ───────────────────────────────────────────────────────────

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
        account = _account_from(request)
        return {"username": account.username, "role": account.role}

    # ── admin: user management ─────────────────────────────────────────

    @app.get("/admin/users")
    async def list_users(request: Request) -> list[dict]:
        _require_admin(request)
        return [record.to_public_dict() for record in get_user_store().list_users()]

    @app.post("/admin/users", status_code=201)
    async def add_user(request: Request) -> dict:
        _require_admin(request)
        body = await request.json()
        try:
            record = get_user_store().add(
                str(body.get("username") or ""),
                str(body.get("password") or ""),
                str(body.get("role") or ""),
            )
        except DuplicateUserError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return record.to_public_dict()

    @app.delete("/admin/users/{username}")
    async def delete_user(username: str, request: Request) -> dict:
        account = _require_admin(request)
        if (username or "").strip().lower() == account.username:
            raise HTTPException(status_code=400, detail="You cannot delete your own account.")
        try:
            get_user_store().remove(username)
        except BuiltinUserError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except UnknownUserError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        return {"ok": True}

    # ── database connection ────────────────────────────────────────────

    @app.get("/db/status")
    async def db_status(request: Request) -> dict:
        account = _account_from(request)
        record = connection_store.get(account.username)
        if record is None:
            return {"connected": False}
        table_count: int | None = None
        try:
            engine_ref = connection_store.engine_for(account.username)
            if engine_ref is not None:
                table_count = len(introspect_schema(engine_ref).get("tables", []))
        except Exception:
            logger.warning("db_status introspection failed", exc_info=True)
        return {
            "connected": True,
            "dialect": record.dialect,
            "urlRedacted": redact_url(record.url),
            "tableCount": table_count,
        }

    @app.post("/db/connect")
    async def db_connect(request: Request) -> dict:
        account = _account_from(request)
        body = await request.json()
        url = str(body.get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="A SQLAlchemy database URL is required.")
        # Relative sqlite paths anchor to the example root (where sample.db lives).
        url = normalize_sqlite_url(url, root.parent)
        try:
            test_connection(url)
        except ModuleNotFoundError as exc:
            hints = {"psycopg2": "pip install psycopg2-binary", "MySQLdb": "pip install pymysql"}
            hint = hints.get(exc.name or "", f"pip install {exc.name}")
            raise HTTPException(
                status_code=400,
                detail=f"Database driver '{exc.name}' is not installed. Run: {hint}",
            ) from None
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not connect: {exc}") from None
        record = connection_store.set(account.username, url)
        engine_ref = connection_store.engine_for(account.username)
        try:
            schema = introspect_schema(engine_ref)
        except Exception as exc:
            connection_store.remove(account.username)
            raise HTTPException(
                status_code=400, detail=f"Connected but schema introspection failed: {exc}"
            ) from None
        return {
            "ok": True,
            "dialect": record.dialect,
            "tables": [table["name"] for table in schema["tables"]],
        }

    @app.delete("/db/connection")
    async def db_disconnect(request: Request) -> dict:
        account = _account_from(request)
        connection_store.remove(account.username)
        return {"ok": True}

    @app.get("/db/schema")
    async def db_schema(request: Request) -> dict:
        account = _account_from(request)
        engine_ref = connection_store.engine_for(account.username)
        if engine_ref is None:
            raise HTTPException(status_code=409, detail="No database connected.")
        return introspect_schema(engine_ref)

    # ── dashboard ──────────────────────────────────────────────────────

    @app.get("/dashboard")
    async def get_dashboard(request: Request) -> dict:
        account = _account_from(request)
        spec = dashboard_store.get(account.username)
        if spec is None:
            raise HTTPException(status_code=404, detail="No dashboard yet.")
        return spec

    @app.get("/dashboard/panels/{panel_id}/data")
    async def get_panel_data(panel_id: str, request: Request) -> dict:
        account = _account_from(request)
        spec = dashboard_store.get(account.username)
        if spec is None:
            raise HTTPException(status_code=404, detail="No dashboard yet.")
        panel = next((p for p in spec.get("panels", []) if p.get("id") == panel_id), None)
        if panel is None:
            raise HTTPException(status_code=404, detail="Unknown panel.")
        engine_ref = connection_store.engine_for(account.username)
        if engine_ref is None:
            raise HTTPException(status_code=409, detail="No database connected.")
        try:
            result = execute_select(engine_ref, str(panel.get("sql") or ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Query failed: {exc}") from None
        return result.to_dict()

    # ── chat ───────────────────────────────────────────────────────────

    @app.post("/awp")
    async def chat_stream(request: Request):
        account = _account_from(request)
        return await handler.handle_owned(request, account.username)

    @app.get("/sessions")
    async def list_sessions(request: Request) -> list[dict]:
        account = _account_from(request)
        session = session_store.load(session_id_for(account.username))
        if session is None:
            return []
        return [
            {
                "sessionId": session.session_id,
                "title": session.title,
                "createdAt": session.created_at.isoformat(),
                "updatedAt": session.updated_at.isoformat(),
                "messageCount": len(session.messages),
                "preview": "",
            }
        ]

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: str, request: Request) -> dict:
        account = _account_from(request)
        if session_id != session_id_for(account.username):
            raise HTTPException(status_code=404, detail="Session not found")
        session = session_store.load(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session.to_dict()

    @app.delete("/sessions/{session_id}")
    async def delete_session(session_id: str, request: Request) -> dict:
        """Clear the caller's conversation (session + persistent memory)."""
        account = _account_from(request)
        own_id = session_id_for(account.username)
        if session_id != own_id:
            raise HTTPException(status_code=404, detail="Session not found")
        session_store.delete(own_id)
        memory_store.delete_session(own_id)
        with handler._sessions_lock:
            handler._sessions.pop(own_id, None)
        return {"ok": True, "sessionId": own_id}

    # ── misc ───────────────────────────────────────────────────────────

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "service": "dashboard-chat"}

    @app.middleware("http")
    async def bearer_auth_middleware(request: Request, call_next):
        path = request.url.path
        if request.method.upper() == "OPTIONS" or path in _PUBLIC_PATHS:
            return await call_next(request)
        account = resolve_bearer(request.headers.get("authorization", ""))
        if account is None:
            return JSONResponse(
                {"detail": "Authentication required."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.account = account
        return await call_next(request)

    _mount_static_spa(app)
    return app


def _mount_static_spa(app: FastAPI) -> None:
    """Serve the built SPA when DASHBOARD_CHAT_STATIC_DIR is set (prod-style)."""
    static_dir = os.getenv("DASHBOARD_CHAT_STATIC_DIR", "").strip()
    if not static_dir:
        return
    dist = Path(static_dir)
    index = dist / "index.html"
    if not index.is_file():
        logger.warning("DASHBOARD_CHAT_STATIC_DIR set but %s not found", index)
        return
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)
