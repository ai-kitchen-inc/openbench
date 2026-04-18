"""FastAPI application for LCI Mini.

Wires the Lici agent (with persona loaded from ``soul/``) through
ChatEngine + AG-UI transport, giving each thread its own SQLite-backed
persistent memory.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lci_mini.agent import create_lici_agent, get_persona_dir
from lci_mini.auth import AuthConfig
from lci_mini.auth.drive import get_token_store
from lci_mini.auth.endpoints import build_drive_router
from lci_mini.server.handler import LiciAGUIHandler
from lci_mini.server.request_scope import (
    configure_render_queue,
    require_firebase_user,
    resolve_agent,
    resolve_session_for_thread,
    resolve_storage_backend,
)
from openbench import LocalStorageBackend, StorageBackend
from openbench.chat import render_queue as shared_render_queue
from openbench.chat.files import FileContentExtractor, FileStore
from openbench.chat.transport import AGUIActionHandler
from openbench.chat.transport.sessions import AGUISessionHandler


def _build_storage_backend() -> tuple[StorageBackend, str]:
    """Legacy Phase-2 shim retained for tests + documentation.

    Returns ``(backend, human_label)`` for the **startup-level** storage
    decision — used only for the display agent (/persona, /skills) and
    the startup banner. Per-request storage now lives in
    :mod:`lci_mini.server.request_scope`.

    Selection:
    - ``LCI_MINI_DRIVE_ROOT`` + ``LCI_MINI_SERVICE_ACCOUNT`` → shared
      service-account Drive backend (legacy multi-tenant-unsafe mode).
    - Otherwise → :class:`LocalStorageBackend` at
      ``examples/lci-mini/.openbench/`` (override via
      ``LCI_MINI_STORAGE_ROOT``).
    """
    drive_root = os.getenv("LCI_MINI_DRIVE_ROOT")
    if drive_root:
        service_account = os.getenv("LCI_MINI_SERVICE_ACCOUNT")
        if not service_account:
            raise RuntimeError(
                "LCI_MINI_DRIVE_ROOT is set but LCI_MINI_SERVICE_ACCOUNT is not. "
                "Provide a service-account JSON path to use the Drive backend, "
                "or unset LCI_MINI_DRIVE_ROOT to fall back to local storage."
            )
        from openbench.integrations.gdrive import GoogleDriveStorageBackend

        backend: StorageBackend = GoogleDriveStorageBackend(
            root_folder_id=drive_root,
            service_account_file=service_account,
        )
        return backend, f"GoogleDrive(folder={drive_root})"

    default_root = get_persona_dir().parent / ".openbench"
    storage_root = os.getenv("LCI_MINI_STORAGE_ROOT", str(default_root))
    return LocalStorageBackend(storage_root), f"Local(root={storage_root})"


def _build_display_backend() -> tuple[StorageBackend, str]:
    """Backend used for the process-wide display agent (/persona, /skills).

    In Firebase-auth mode we don't have a real user at startup, so we
    route display metadata through a shared local backend that lives
    next to Lici's persona. Actual chat traffic never flows through
    this — it uses per-request resolution.
    """
    try:
        return _build_storage_backend()
    except Exception:
        default_root = get_persona_dir().parent / ".openbench"
        return LocalStorageBackend(default_root), f"Local(root={default_root})"


def create_app() -> FastAPI:
    """Create and configure the LCI Mini FastAPI app.

    Does NOT call :func:`load_dotenv` — that's the job of the entry
    point (``server.py``). Keeping ``create_app()`` env-pure means tests
    can monkeypatch the environment without a stray ``.env`` on disk
    overwriting the test setup.
    """
    # The request-scope module (see server/request_scope.py) builds a
    # per-request StorageBackend / BaseAgent / ChatEngine based on the
    # authenticated user. In "disabled" and "none" auth modes every
    # request resolves to the same synthetic uid, so the Phase-2
    # single-tenant deployment still works unchanged.

    # Wire ChatEngine to every render-items queue we know about so tool
    # results surface as rich A2UI components in the next assistant turn.
    # Two sources today:
    #
    #   1. xql skill — project skill, has its own ContextVar queue (pushes
    #      ObTable items for every query/pareto/group result)
    #   2. openbench.chat.render_queue — shared queue that SDK skills push
    #      to (e.g. export-excel adds an ObFileCard when it writes an xlsx)
    #
    # Merge them in a single callback so ChatEngine sees one unified list.
    xql_mod = sys.modules.get("openbench_skill_xql")
    xql_get = getattr(xql_mod, "get_render_items", None) if xql_mod else None
    xql_clear = getattr(xql_mod, "clear_render_items", None) if xql_mod else None

    def render_items_fn() -> list[dict]:
        items: list[dict] = []
        if xql_get is not None:
            xql_items = xql_get()
            items.extend(xql_items)
        shared_items = shared_render_queue.get_items()
        items.extend(shared_items)
        if items:
            xql_count = len(xql_items) if xql_get else 0
            print(
                f"  [render] {len(items)} render item(s): "
                f"xql={xql_count}, shared={len(shared_items)}"
            )
            for i, item in enumerate(items):
                item_type = item.get("type", item.get("headers", "?"))
                item_name = item.get("title", item.get("name", ""))
                print(f"  [render]   [{i}] type={item_type} name={item_name!r}")
        return items

    def clear_render_items_fn() -> None:
        if xql_clear is not None:
            xql_clear()
        shared_render_queue.clear()

    # Install callbacks on the request-scope module so per-request
    # ChatEngines inherit the same render-queue plumbing.
    configure_render_queue(render_items_fn, clear_render_items_fn)

    db_path = os.getenv("LCI_MINI_MEMORY_DB", "lci_mini_memory.db")

    # A single "display" agent + label for /persona, /skills, startup
    # banner — these endpoints show process-wide metadata (Lici's
    # persona, loaded skills) that does not vary per user. Built with a
    # throwaway LocalStorageBackend so the factory is happy.
    display_backend, display_storage_label = _build_display_backend()
    display_agent = create_lici_agent(scratchpad=display_backend.scratchpad_store())

    # upload_dir defaults to <example_root>/uploads/ — absolute path so the
    # file store works regardless of which directory uvicorn was launched
    # from (CLI, manual, Cloud Run, etc).
    default_upload_dir = get_persona_dir().parent / "uploads"
    upload_dir = os.getenv("LCI_MINI_UPLOAD_DIR", str(default_upload_dir))
    upload_dir = str(Path(upload_dir).expanduser().resolve())
    os.makedirs(upload_dir, exist_ok=True)
    file_store = FileStore(upload_dir=upload_dir)
    extractor = FileContentExtractor()

    # download_dir is where the export-excel skill (and any other file-
    # producing tool) writes its output. It must be a directory the
    # server also mounts as static HTTP so the frontend can download
    # what the agent produced. Defaults to <example_root>/downloads/.
    default_download_dir = get_persona_dir().parent / "downloads"
    download_dir = os.getenv("LCI_MINI_DOWNLOAD_DIR", str(default_download_dir))
    download_dir = str(Path(download_dir).expanduser().resolve())
    os.makedirs(download_dir, exist_ok=True)

    # profile_dir is where the data-context-extractor SDK skill stores
    # column profile caches (LLM-inferred column→role mappings). Keyed
    # by file content hash so the same file never needs re-mapping.
    default_profile_dir = get_persona_dir().parent / "profiles"
    profile_dir = os.getenv("OPENBENCH_PROFILE_DIR", str(default_profile_dir))
    profile_dir = str(Path(profile_dir).expanduser().resolve())
    os.makedirs(profile_dir, exist_ok=True)
    os.environ["OPENBENCH_PROFILE_DIR"] = profile_dir
    # Tell the export-excel skill (and any future SDK skill that honors
    # these env vars) where to write and how to URL-address the result.
    os.environ["OPENBENCH_EXPORT_DIR"] = download_dir
    os.environ["OPENBENCH_EXPORT_URL_BASE"] = "/downloads"

    app = FastAPI(title="LCI Mini — Persona + Skill Layer Demo")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    persona = display_agent._persona
    auth_mode = AuthConfig.from_env().mode

    @app.on_event("startup")
    async def startup() -> None:
        summary = persona.summary() if persona else {}
        print("\n  LCI Mini — Persona Layer Demo")
        print(f"  Model          : {display_agent.model}")
        print(f"  Auth mode      : {auth_mode}")
        print(f"  Persona source : {summary.get('source', '(none)')}")
        if persona:
            print(f"  SOUL.md        : {summary['soul_chars']:>5} chars")
            print(f"  STYLE.md       : {summary['style_chars']:>5} chars")
            print(f"  AGENTS.md      : {summary['agents_chars']:>5} chars")
            print(f"  Persona total  : {summary['total_chars']:>5} chars")
        if display_agent._skill_registry:
            skill_summary = display_agent._skill_registry.summary()
            print(
                f"  Skills loaded  : {skill_summary['total']} "
                f"(tools={skill_summary['total_tools']}, "
                f"context={skill_summary['context_chars']} chars)"
            )
            for s in display_agent._skill_registry.all():
                tool_names = [name for name, _, _ in s.tools]
                label = f"tools={tool_names}" if tool_names else "knowledge-only"
                print(f"    - {s.name} v{s.version}: {label}")
        print(f"  Memory DB      : {db_path}")
        print(f"  Display storage: {display_storage_label}")
        print(f"  Upload dir     : {upload_dir}")
        print(f"  Download dir   : {download_dir}")
        print(f"  Profile dir    : {profile_dir}")
        print("  AG-UI          : POST /awp")
        print("  Upload         : POST /chat/upload")
        print("  Download       : GET  /downloads/<filename>")
        print("  Actions        : POST /chat/action")
        print("  Sessions API   : GET/DELETE /sessions[/{id}]")
        print("  Auth           : GET  /auth/me, /auth/drive/*\n")

    @app.get("/")
    async def root() -> dict:
        return {
            "service": "lci-mini",
            "persona": persona.summary() if persona else None,
            "docs": "/health",
        }

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "lci-mini"}

    # After the Drive OAuth dance, the browser is on the backend
    # (e.g. http://localhost:8004/auth/drive/callback). Bounce it back
    # to the frontend so the user lands on the chat UI, not on the
    # backend's health JSON. Configurable via LCI_MINI_FRONTEND_URL so
    # Cloud Run deployments can target the Firebase Hosting origin.
    frontend_url = os.getenv("LCI_MINI_FRONTEND_URL", "http://localhost:5173/")
    app.include_router(build_drive_router(redirect_home=frontend_url))

    @app.get("/auth/me")
    async def auth_me(user=Depends(require_firebase_user)) -> dict:
        """Return the authenticated user + Drive connection status.

        The frontend reads this once on app bootstrap to:
        1. Build the "signed in as …" UI
        2. Decide whether to show the "Connect Google Drive" prompt
           (only when Drive OAuth is configured on the backend AND the
           user isn't already connected).

        Returning everything in one round-trip avoids a
        sign-in → /auth/me → /auth/drive/status waterfall.
        """
        from lci_mini.auth.config import DriveOAuthConfig

        drive_cfg = DriveOAuthConfig.from_env()
        drive_configured = drive_cfg.enabled

        drive_connected = False
        drive_folder_id: str | None = None
        drive_email: str | None = None
        try:
            drive_token = get_token_store().load(user.uid)
        except Exception:  # pragma: no cover — defensive
            drive_token = None
        if drive_token is not None:
            drive_connected = True
            drive_folder_id = drive_token.openbench_folder_id
            drive_email = drive_token.connected_email
        return {
            "uid": user.uid,
            "email": user.email,
            "name": user.name,
            "emailVerified": user.email_verified,
            "mode": auth_mode,
            "drive": {
                "configured": drive_configured,
                "connected": drive_connected,
                "folderId": drive_folder_id,
                "email": drive_email,
            },
        }

    @app.get("/persona")
    async def persona_info(_user=Depends(require_firebase_user)) -> dict:
        """Expose the composed persona so the UI can show what's loaded."""
        if not persona:
            return {"loaded": False}
        return {
            "loaded": True,
            **persona.summary(),
            "soul": persona.soul,
            "style": persona.style,
            "agents": persona.agents,
        }

    @app.get("/skills")
    async def skills_info(_user=Depends(require_firebase_user)) -> dict:
        """Expose loaded skills so the UI can show which capabilities are wired.

        Returns one entry per skill with name, version, source path, tool
        names, and reference files. Used by the frontend sidebar badge to
        render a compact skill inventory. Reads from the process-wide
        display agent — skill set is uniform across users.
        """
        registry = display_agent._skill_registry
        if registry is None:
            return {"loaded": False, "skills": []}
        items = [
            {
                "name": skill.name,
                "version": skill.version,
                "description": skill.description,
                "has_tools": skill.has_tools,
                "tools": [name for name, _, _ in skill.tools],
                "references": list(skill.references.keys()),
                "triggers": skill.triggers,
                "dependencies": skill.dependencies,
                "source": skill.source,
                "context_chars": len(skill.get_context()),
            }
            for skill in registry.all()
        ]
        return {
            "loaded": True,
            "summary": registry.summary(),
            "skills": items,
        }

    @app.post("/chat/upload")
    async def upload_file(
        file: UploadFile = File(...),
        _user=Depends(require_firebase_user),
    ):
        """Store an uploaded file on disk and return attachment metadata.

        The returned ``id`` is what the frontend includes in subsequent
        /awp chat requests; the server resolves that id back to a disk
        path and makes it available to the xql skill.
        """
        content = await file.read()
        stored = file_store.store(
            file.filename or "unnamed",
            content,
            file.content_type or "application/octet-stream",
        )
        stored.extracted_text = await asyncio.to_thread(extractor.extract, stored)
        print(
            f"  [upload] id={stored.id} name={stored.name!r} "
            f"size={stored.size_bytes}B path={stored.path}"
        )
        attachment = stored.to_attachment(base_url="/uploads")
        result = attachment.to_dict()
        if stored.extracted_text:
            result["extractedText"] = stored.extracted_text[:2000]
        return result

    @app.post("/awp")
    async def agent_endpoint(
        request: Request,
        storage: StorageBackend = Depends(resolve_storage_backend),
        agent=Depends(resolve_agent),
    ):
        """AG-UI endpoint — per-user engine built from resolved storage.

        Storage + agent are resolved per-request so each user's
        ChatSessions land in their own store (Drive or per-user local).
        Existing sessions are loaded by threadId from the body so chat
        history survives across turns without a process-global engine.
        """
        body = await request.json()

        # Attachments can live on forwardedProps.attachments OR top-level
        forwarded = body.get("forwardedProps") or {}
        attachments_list = forwarded.get("attachments") or body.get("attachments") or []

        file_paths: list[str] = []
        unresolved: list[str] = []
        for att in attachments_list:
            file_id = att.get("id")
            if not file_id:
                continue
            stored = file_store.get(file_id)
            if stored is not None:
                file_paths.append(stored.path)
            else:
                unresolved.append(file_id)

        if attachments_list:
            print(
                f"  [awp] {len(attachments_list)} attachment(s): "
                f"resolved={len(file_paths)} unresolved={unresolved}"
            )
            if file_paths:
                print(f"  [awp]   paths: {file_paths}")

        # Push resolved paths into the xql skill's ContextVar so xql_catalog
        # can pick them up without the LLM having to know the disk path.
        xql_mod = sys.modules.get("openbench_skill_xql")
        if xql_mod is not None and hasattr(xql_mod, "set_uploaded_files"):
            xql_mod.set_uploaded_files(file_paths or None)

        thread_id = body.get("threadId")
        session_store = storage.session_store()
        session = resolve_session_for_thread(thread_id, session_store)
        from lci_mini.server.request_scope import build_engine

        engine = build_engine(agent=agent, session=session, session_store=session_store)
        handler = LiciAGUIHandler(engine=engine, db_path=db_path)
        return await handler.handle(request)

    @app.post("/chat/action")
    async def chat_action(
        request: Request,
        storage: StorageBackend = Depends(resolve_storage_backend),
        agent=Depends(resolve_agent),
    ):
        body = await request.json()
        thread_id = body.get("threadId")
        session_store = storage.session_store()
        session = resolve_session_for_thread(thread_id, session_store)
        from lci_mini.server.request_scope import build_engine

        engine = build_engine(agent=agent, session=session, session_store=session_store)
        handler = AGUIActionHandler(engine=engine)
        return await handler.handle(request)

    @app.get("/chat/actions")
    async def list_actions() -> dict:
        # Registered-action names are process-wide (no user state), so
        # resolving a throwaway handler with the display engine is fine.
        handler = AGUIActionHandler(engine=None)
        return {"actions": handler.get_registered_actions()}

    # ── Session CRUD (for the chat-ui SessionSidebar) ──

    @app.get("/sessions")
    async def list_sessions(
        limit: int = 50,
        offset: int = 0,
        storage: StorageBackend = Depends(resolve_storage_backend),
    ) -> list[dict]:
        handler = AGUISessionHandler(session_store=storage.session_store())
        return handler.list(limit=limit, offset=offset)

    @app.get("/sessions/{session_id}")
    async def get_session(
        session_id: str,
        storage: StorageBackend = Depends(resolve_storage_backend),
    ):
        from fastapi import HTTPException

        handler = AGUISessionHandler(session_store=storage.session_store())
        data = handler.get(session_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return data

    @app.delete("/sessions/{session_id}")
    async def delete_session(
        session_id: str,
        storage: StorageBackend = Depends(resolve_storage_backend),
    ) -> dict:
        handler = AGUISessionHandler(session_store=storage.session_store())
        handler.delete(session_id)
        return {"ok": True, "sessionId": session_id}

    # Serve uploaded files for frontend preview links
    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

    # Serve agent-produced downloads (export-excel, etc.). URL prefix
    # matches OPENBENCH_EXPORT_URL_BASE so the file render items the
    # export-excel skill builds actually resolve to real HTTP URLs.
    app.mount("/downloads", StaticFiles(directory=download_dir), name="downloads")

    # Optional: serve built frontend in production (Cloud Run single-container mode)
    static_dir = os.environ.get("LCI_MINI_STATIC_DIR")
    if static_dir and os.path.isdir(static_dir):
        static_root = Path(static_dir).resolve()

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            # Resolve and assert containment to prevent path traversal
            # (e.g. GET /../../../etc/passwd).
            file_path = (static_root / full_path).resolve()
            if not str(file_path).startswith(str(static_root)):
                from fastapi.responses import JSONResponse

                return JSONResponse({"error": "Not found"}, status_code=404)
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(static_root / "index.html")

        assets_dir = static_root / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    return app
