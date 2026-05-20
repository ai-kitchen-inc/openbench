"""FastAPI application for General Chat.

A simplified chat server with document upload (PDF, DOCX, PPTX) parsed via
Docling, and a general-purpose Gemini agent. No authentication required.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from general_chat.agent import create_agent, get_persona_dir, reload_external_mcp_tools
from general_chat.extractor import DoclingContentExtractor
from general_chat.mcp_registry import MCPRegistryError, MCPServerRegistryStore
from general_chat.server.handler import GeneralChatHandler
from general_chat.sources import (
    DEFAULT_DISCOVERY_LIMIT,
    SearchDiscoveryAdapter,
    SourceParserRegistry,
    SourceStore,
    max_source_bytes_from_env,
    source_record_from_file,
    source_record_from_text,
    source_record_from_url,
)
from openbench import LocalStorageBackend
from openbench.chat import ChatEngine
from openbench.chat import render_queue as shared_render_queue
from openbench.chat.files import LocalFileStore
from openbench.chat.transport import AGUIActionHandler
from openbench.chat.transport.sessions import AGUISessionHandler

logger = logging.getLogger(__name__)

_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/plain",
    "text/csv",
    "text/markdown",
    "application/json",
    "image/png",
    "image/jpeg",
    "image/webp",
    "application/octet-stream",  # browser fallback
}

# Extension-to-MIME override when the browser sends application/octet-stream
_EXT_MIME_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _resolve_mime(filename: str, content_type: str) -> str:
    """Return the best MIME type for a file, using extension as a tiebreaker."""
    if content_type and content_type != "application/octet-stream":
        return content_type
    ext = Path(filename).suffix.lower()
    return _EXT_MIME_MAP.get(ext, "application/octet-stream")


def _resolve_request_session_id(body: dict) -> str | None:
    """Resolve the chat session id the same way AGUIHandler does."""
    forwarded = body.get("forwardedProps") or {}
    return forwarded.get("sessionId") or body.get("threadId")


def create_app() -> FastAPI:
    example_root = get_persona_dir().parent

    default_upload_dir = example_root / "uploads"
    upload_dir = str(Path(os.getenv("GENERAL_CHAT_UPLOAD_DIR", str(default_upload_dir))).resolve())
    os.makedirs(upload_dir, exist_ok=True)

    default_download_dir = example_root / "downloads"
    download_dir = str(Path(os.getenv("GENERAL_CHAT_DOWNLOAD_DIR", str(default_download_dir))).resolve())
    os.makedirs(download_dir, exist_ok=True)

    default_image_search_preview_dir = example_root.parent / "image-search-mcp" / "data" / "previews"
    image_search_preview_dir = str(
        Path(
            os.getenv(
                "GENERAL_CHAT_IMAGE_SEARCH_PREVIEW_DIR",
                str(default_image_search_preview_dir),
            )
        ).resolve()
    )
    os.makedirs(image_search_preview_dir, exist_ok=True)

    default_storage_root = example_root / ".openbench"
    storage_root = str(Path(os.getenv("GENERAL_CHAT_STORAGE_ROOT", str(default_storage_root))).resolve())
    os.environ["GENERAL_CHAT_MCP_REGISTRY_ROOT"] = storage_root

    default_profile_dir = example_root / "profiles"
    profile_dir = str(Path(os.getenv("OPENBENCH_PROFILE_DIR", str(default_profile_dir))).resolve())
    os.makedirs(profile_dir, exist_ok=True)
    os.environ["OPENBENCH_PROFILE_DIR"] = profile_dir
    os.environ["OPENBENCH_EXPORT_DIR"] = download_dir
    os.environ["OPENBENCH_EXPORT_URL_BASE"] = "/downloads"

    db_path = os.getenv("GENERAL_CHAT_MEMORY_DB", "general_chat_memory.db")

    storage = LocalStorageBackend(storage_root)
    file_store = LocalFileStore(upload_dir=upload_dir)
    extractor = DoclingContentExtractor()
    source_parser = SourceParserRegistry(document_extractor=extractor)
    source_store = SourceStore(storage_root)
    mcp_registry_store = MCPServerRegistryStore(storage_root)
    discovery_adapter = SearchDiscoveryAdapter()
    max_source_bytes = max_source_bytes_from_env()
    agent = create_agent()

    def render_items_fn() -> list[dict]:
        items = shared_render_queue.get_items()
        return items

    def clear_render_items_fn() -> None:
        shared_render_queue.clear()

    def _build_engine(session) -> ChatEngine:
        return ChatEngine(
            agent=agent,
            session=session,
            session_store=storage.session_store(),
            render_items_fn=render_items_fn,
            clear_render_items_fn=clear_render_items_fn,
        )

    def _resolve_session(thread_id: str | None):
        session_store = storage.session_store()
        if thread_id:
            try:
                existing = session_store.load(thread_id)
            except Exception:
                existing = None
            if existing is not None:
                return existing
        from openbench.chat.session import ChatSession

        session = ChatSession(session_id=thread_id or None)
        session_store.save(session)
        return session

    app = FastAPI(title="General Chat — Document-Aware Assistant")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup() -> None:
        persona = agent._persona
        summary = persona.summary() if persona else {}
        print("\n  General Chat — Document-Aware Assistant")
        print(f"  Model          : {agent.model}")
        print(f"  Persona source : {summary.get('source', '(none)')}")
        if persona:
            print(f"  Persona total  : {summary['total_chars']:>5} chars")
        if agent._skill_registry:
            skill_summary = agent._skill_registry.summary()
            print(
                f"  Skills loaded  : {skill_summary['total']} "
                f"(tools={skill_summary['total_tools']}, "
                f"context={skill_summary['context_chars']} chars)"
            )
        print(f"  Memory DB      : {db_path}")
        print(f"  Storage root   : {storage_root}")
        print(f"  Upload dir     : {upload_dir}")
        print(f"  Download dir   : {download_dir}")
        print(f"  Image previews : {image_search_preview_dir}")
        print(f"  Source max     : {max_source_bytes} bytes")
        print("  AG-UI          : POST /awp")
        print("  Upload         : POST /chat/upload")
        print("  Sessions API   : GET/DELETE /sessions[/{id}]\n")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "general-chat"}

    @app.get("/persona")
    async def persona_info() -> dict:
        persona = agent._persona
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
    async def skills_info() -> dict:
        registry = agent._skill_registry
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

    @app.get("/mcp/tools")
    async def mcp_tools_info() -> dict:
        summary = getattr(agent, "_mcp_summary", None)
        external_summary = getattr(agent, "_external_mcp_summary", None)
        if not isinstance(summary, dict):
            summary = {
                "enabled": False,
                "mode": os.getenv("GENERAL_CHAT_MCP_MODE", "local"),
                "tools": [],
            }
        if not isinstance(external_summary, dict):
            external_summary = {"enabled": False, "tools": []}
        tools = summary.get("tools", [])
        external_tools = external_summary.get("tools", [])
        all_tools = [*tools, *external_tools]
        return {
            **summary,
            "enabled": bool(summary.get("enabled") or external_summary.get("enabled")),
            "registry": external_summary,
            "tool_count": len(all_tools),
            "tools": all_tools,
            "provider_tool_names": [item.get("adapter_name") for item in all_tools],
            "namespaced_tool_names": [item.get("name") for item in all_tools],
        }

    @app.get("/mcp/catalogs")
    async def list_mcp_servers() -> dict:
        return mcp_registry_store.list_payload()

    @app.post("/mcp/catalogs/import")
    async def import_mcp_servers(request: Request) -> dict:
        body = await request.json()
        try:
            if isinstance(body.get("config"), str):
                raw_config = body["config"]
            elif "mcpServers" in body:
                import json

                raw_config = json.dumps(body)
            else:
                raise MCPRegistryError("Paste a JSON object containing mcpServers.")
            return mcp_registry_store.import_config_json(raw_config)
        except MCPRegistryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/mcp/catalogs/{server_id}/refresh")
    async def refresh_mcp_server(server_id: str) -> dict:
        try:
            server = mcp_registry_store.discover_server(server_id)
            reload_summary = reload_external_mcp_tools(agent)
            return {"server": server.to_dict(detail=True), "reload": reload_summary}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP server not found") from exc
        except MCPRegistryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/mcp/catalogs/{server_id}")
    async def remove_mcp_server(server_id: str) -> dict:
        mcp_registry_store.remove_server(server_id)
        reload_summary = reload_external_mcp_tools(agent)
        return {"ok": True, "serverId": server_id, "reload": reload_summary}

    @app.get("/mcp/catalogs/servers/{server_id}")
    async def get_mcp_server(server_id: str) -> dict:
        try:
            return mcp_registry_store.get_server(server_id).to_dict(detail=True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP server not found") from exc

    @app.post("/mcp/catalogs/servers/{server_id}/enable")
    async def enable_mcp_server(server_id: str, request: Request) -> dict:
        body = await request.json()
        try:
            server = mcp_registry_store.set_server_enabled(
                server_id,
                bool(body.get("enabled", True)),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP server not found") from exc
        except MCPRegistryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        reload_summary = reload_external_mcp_tools(agent)
        return {
            "server": server.to_dict(detail=True),
            "reload": reload_summary,
        }

    @app.post("/mcp/catalogs/servers/{server_id}/discover")
    async def discover_mcp_server(server_id: str) -> dict:
        try:
            server = mcp_registry_store.discover_server(server_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP server not found") from exc
        reload_summary = reload_external_mcp_tools(agent)
        return {"server": server.to_dict(detail=True), "reload": reload_summary}

    @app.post("/mcp/catalogs/servers/{server_id}/tools/{tool_name}/enable")
    async def enable_mcp_tool(server_id: str, tool_name: str, request: Request) -> dict:
        body = await request.json()
        try:
            server = mcp_registry_store.set_tool_enabled(
                server_id,
                tool_name,
                bool(body.get("enabled", True)),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP server or tool not found") from exc
        reload_summary = reload_external_mcp_tools(agent)
        return {"server": server.to_dict(detail=True), "reload": reload_summary}

    @app.delete("/mcp/catalogs/servers/{server_id}")
    async def remove_mcp_server_by_id(server_id: str) -> dict:
        mcp_registry_store.remove_server(server_id)
        reload_summary = reload_external_mcp_tools(agent)
        return {"ok": True, "serverId": server_id, "reload": reload_summary}

    @app.post("/chat/upload")
    async def upload_file(
        file: UploadFile = File(...),
        session_id: str | None = Form(default=None, alias="sessionId"),
    ):
        """Store an uploaded source file and persist extracted text for a session."""
        content = await file.read()
        filename = file.filename or "unnamed"
        mime_type = _resolve_mime(filename, file.content_type or "")
        target_session_id = session_id or "default"

        stored = file_store.store(filename, content, mime_type)
        record = source_record_from_file(
            session_id=target_session_id,
            stored_file=stored,
            parser=source_parser,
            max_bytes=max_source_bytes,
        )
        source_store.add(record)
        stored.extracted_text = record.text

        print(
            f"  [source-upload] id={record.id} session={target_session_id!r} "
            f"name={stored.name!r} "
            f"mime={mime_type} size={stored.size_bytes}B "
            f"status={record.status} text_len={len(record.text)}"
        )

        attachment = stored.to_attachment(base_url="/uploads")
        result = {**attachment.to_dict(), **record.to_dict(include_text=True)}
        # Include the full extracted text — Docling content can be large but
        # Gemini's 1M token window handles it. Truncating here loses information
        # that the agent needs to answer document questions.
        result["url"] = record.url or attachment.url
        result["type"] = attachment.type
        return result

    @app.get("/chat/sources/discover")
    async def discover_sources(q: str = "", limit: int = DEFAULT_DISCOVERY_LIMIT) -> dict:
        query = q.strip()
        if not query:
            return {"query": "", "results": []}
        try:
            response = discovery_adapter.search(query, limit=limit)
        except Exception as exc:
            # External discovery providers (DuckDuckGo/Grounded search) can fail due to
            # transient network, SSL, or upstream provider issues. Keep the API stable
            # for the frontend and degrade to an empty result set instead of raising 500.
            logger.warning("Source discovery failed for query %r: %s", query, exc, exc_info=True)
            return {
                "query": query,
                "results": [],
                "warning": "Discovery provider is temporarily unavailable. Try again later.",
            }
        payload = {
            "query": response.query,
            "results": [result.to_dict() for result in response.results],
        }
        if response.warning:
            payload["warning"] = response.warning
        return payload

    @app.get("/chat/sources/{thread_id}")
    async def list_sources(thread_id: str) -> list[dict]:
        return [record.to_dict(include_text=False) for record in source_store.list(thread_id)]

    @app.post("/chat/sources/{thread_id}")
    async def store_sources(thread_id: str, request: Request):
        """Backward-compatible text-context endpoint used by older frontends."""
        body = await request.json()
        context_text = str(body.get("context", ""))
        if context_text.strip():
            record = source_record_from_text(
                session_id=thread_id,
                name=str(body.get("name") or "Pasted source context"),
                text=context_text,
                parser=source_parser,
            )
            source_store.add(record)
            return record.to_dict(include_text=True)
        return {"ok": True}

    @app.post("/chat/sources/{thread_id}/text")
    async def add_text_source(thread_id: str, request: Request) -> dict:
        body = await request.json()
        record = source_record_from_text(
            session_id=thread_id,
            name=str(body.get("name") or "Pasted text"),
            text=str(body.get("text") or ""),
            parser=source_parser,
        )
        source_store.add(record)
        return record.to_dict(include_text=True)

    @app.post("/chat/sources/{thread_id}/url")
    async def add_url_source(thread_id: str, request: Request) -> dict:
        body = await request.json()
        record = source_record_from_url(
            session_id=thread_id,
            url=str(body.get("url") or ""),
            parser=source_parser,
            max_bytes=max_source_bytes,
        )
        source_store.add(record)
        return record.to_dict(include_text=True)

    @app.get("/chat/sources/{thread_id}/search")
    async def search_sources(thread_id: str, q: str = "", limit: int = 20) -> dict:
        return {"query": q, "results": source_store.search(thread_id, q, limit=limit)}

    @app.delete("/chat/sources/{thread_id}/{source_id}")
    async def delete_source(thread_id: str, source_id: str) -> dict:
        deleted = source_store.delete(thread_id, source_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Source not found")
        return {"ok": True, "sourceId": source_id}

    @app.delete("/chat/sources/{thread_id}")
    async def clear_sources(thread_id: str) -> dict:
        """Remove all stored sources for a session."""
        source_store.clear(thread_id)
        return {"ok": True}

    @app.post("/awp")
    async def agent_endpoint(request: Request):
        """AG-UI endpoint — streams assistant responses via SSE."""
        body = await request.json()
        session_id = _resolve_request_session_id(body)
        source_records = source_store.list(session_id) if session_id else []
        session = _resolve_session(session_id)
        engine = _build_engine(session)
        handler = GeneralChatHandler(
            engine=engine,
            db_path=db_path,
            source_records=source_records,
        )
        return await handler.handle(request)

    @app.post("/chat/action")
    async def chat_action(request: Request):
        body = await request.json()
        session_id = _resolve_request_session_id(body)
        session = _resolve_session(session_id)
        engine = _build_engine(session)
        handler = AGUIActionHandler(engine=engine)
        return await handler.handle(request)

    @app.get("/chat/actions")
    async def list_actions() -> dict:
        handler = AGUIActionHandler(engine=None)
        return {"actions": handler.get_registered_actions()}

    @app.get("/sessions")
    async def list_sessions(limit: int = 50, offset: int = 0) -> list[dict]:
        handler = AGUISessionHandler(session_store=storage.session_store())
        return handler.list(limit=limit, offset=offset)

    @app.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        handler = AGUISessionHandler(session_store=storage.session_store())
        data = handler.get(session_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return data

    @app.delete("/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict:
        handler = AGUISessionHandler(session_store=storage.session_store())
        handler.delete(session_id)
        return {"ok": True, "sessionId": session_id}

    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")
    app.mount("/downloads", StaticFiles(directory=download_dir), name="downloads")
    app.mount(
        "/image-search/previews",
        StaticFiles(directory=image_search_preview_dir),
        name="image-search-previews",
    )

    static_dir = os.environ.get("GENERAL_CHAT_STATIC_DIR")
    if static_dir and os.path.isdir(static_dir):
        static_root = Path(static_dir).resolve()

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
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
