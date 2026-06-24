"""FastAPI application for General Chat.

A simplified chat server with optional file, URL, text, and image context,
plus a general-purpose Gemini agent. Firebase authentication is enforced
when GENERAL_CHAT_FIREBASE_PROJECT_ID is configured.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from general_chat.agent import create_agent, get_persona_dir, reload_external_mcp_tools
from general_chat.extractor import DoclingContentExtractor
from general_chat.mcp_bootstrap import seed_all_mcp_registry
from general_chat.mcp_registry import MCPRegistryError, MCPServerRegistryStore
from general_chat.server.auth import auth_enabled, require_firebase_user
from general_chat.server.handler import GeneralChatHandler
from general_chat.server.mcp_permissions import GeneralChatMCPPermissionCoordinator
from general_chat.sources import (
    DEFAULT_DISCOVERY_LIMIT,
    SearchDiscoveryAdapter,
    SourceParserRegistry,
    SourceRecord,
    build_source_store,
    image_search_text,
    mark_source_upload_deleted,
    max_source_bytes_from_env,
    source_record_from_file,
    source_record_from_text,
    source_record_from_url,
    upload_file_ids_for_source,
)
from openbench import LocalStorageBackend
from openbench.chat import ChatEngine
from openbench.chat import render_queue as shared_render_queue
from openbench.chat.files import LocalFileStore
from openbench.chat.transport import AGUIActionHandler
from openbench.chat.transport.sessions import AGUISessionHandler
from openbench.mcp.toolhive import ToolHiveError, ToolHiveService

logger = logging.getLogger(__name__)

_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/epub+zip",
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
    "image/gif",
    "image/heic",
    "image/heif",
    "image/tiff",
    "image/bmp",
    "image/svg+xml",
    "audio/mpeg",
    "audio/wav",
    "audio/mp4",
    "audio/ogg",
    "audio/aac",
    "audio/flac",
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-msvideo",
    "application/octet-stream",  # browser fallback
}

# Extension-to-MIME override when the browser sends application/octet-stream
_EXT_MIME_MAP = {
    ".pdf": "application/pdf",
    ".epub": "application/epub+zip",
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
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
}

_AUTH_PROTECTED_PREFIXES = (
    "/awp",
    "/chat",
    "/downloads",
    "/image-search",
    "/mcp",
    "/persona",
    "/sessions",
    "/skills",
    "/toolhive",
    "/uploads",
)


def _requires_auth_path(path: str) -> bool:
    return path in _AUTH_PROTECTED_PREFIXES or any(
        path.startswith(f"{prefix}/") for prefix in _AUTH_PROTECTED_PREFIXES
    )


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


def _gcp_enabled() -> bool:
    return bool(os.getenv("GENERAL_CHAT_GCP_BUCKET"))


def cors_allowed_origins() -> list[str]:
    """Return the CORS allowlist.

    Set GENERAL_CHAT_ALLOWED_ORIGINS to a comma-separated list of origins
    (e.g. the Firebase Hosting URLs) to scope cross-origin access in
    production. Defaults to ``["*"]`` when unset so local/dev and tests keep
    working. Requests still require a valid Firebase token regardless of CORS.
    """
    raw = os.getenv("GENERAL_CHAT_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return ["*"]
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["*"]


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _build_storage_backend(storage_root: str, *, session_id: str = "default"):
    if not _gcp_enabled():
        return LocalStorageBackend(storage_root)
    from openbench.integrations.gcp import GoogleCloudStorageBackend

    return GoogleCloudStorageBackend.from_env(
        user_id=os.getenv("GENERAL_CHAT_GCP_USER_ID", "default"),
        session_id=session_id,
    )


async def _read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"Multipart upload exceeds {max_bytes} bytes. "
                    "Use /chat/uploads/initiate for direct Cloud Storage uploads."
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _is_gcs_source(record: SourceRecord) -> bool:
    metadata = record.metadata or {}
    return bool(metadata.get("gcsObject") or metadata.get("gcsBucket"))


def _queued_gcs_upload_record(
    *,
    session_id: str,
    stored,
    status_label: str = "queued",
) -> SourceRecord:
    metadata = {
        "fileId": stored.id,
        "gcsUri": stored.web_view_link,
        "uploadStatus": "uploaded",
        "parseStatus": status_label,
    }
    if stored.web_view_link and stored.web_view_link.startswith("gs://"):
        without_scheme = stored.web_view_link[len("gs://") :]
        bucket, _, object_name = without_scheme.partition("/")
        if bucket:
            metadata["gcsBucket"] = bucket
        if object_name:
            metadata["gcsObject"] = object_name
    return SourceRecord.create(
        session_id=session_id,
        name=stored.name,
        kind="file",
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        url=stored.web_view_link,
        text="",
        status="processing",
        metadata=metadata,
    )


def create_app() -> FastAPI:
    example_root = get_persona_dir().parent

    default_upload_dir = example_root / "uploads"
    upload_dir = str(Path(os.getenv("GENERAL_CHAT_UPLOAD_DIR", str(default_upload_dir))).resolve())
    os.makedirs(upload_dir, exist_ok=True)

    default_download_dir = example_root / "downloads"
    download_dir = str(Path(os.getenv("GENERAL_CHAT_DOWNLOAD_DIR", str(default_download_dir))).resolve())
    os.makedirs(download_dir, exist_ok=True)

    default_image_search_preview_dir = (
        example_root.parents[1] / "mcp" / "image-search-mcp" / "data" / "previews"
    )
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

    storage = _build_storage_backend(storage_root)
    file_store = LocalFileStore(upload_dir=upload_dir)
    extractor = DoclingContentExtractor()
    source_parser = SourceParserRegistry(document_extractor=extractor)
    source_store = build_source_store(storage_root)
    mcp_registry_store = MCPServerRegistryStore(storage_root)
    toolhive_service = ToolHiveService()
    mcp_permission_coordinator = GeneralChatMCPPermissionCoordinator()
    discovery_adapter = SearchDiscoveryAdapter()
    max_source_bytes = max_source_bytes_from_env()
    multipart_upload_max_bytes = _env_int(
        "GENERAL_CHAT_MULTIPART_UPLOAD_MAX_BYTES",
        25 * 1024 * 1024,
    )
    agent = create_agent()
    chat_memory_store = storage.memory_store() if os.getenv("GENERAL_CHAT_DATABASE_URL") else None

    def _storage_for_session(session_id: str):
        if not _gcp_enabled():
            return storage
        return _build_storage_backend(storage_root, session_id=session_id)

    def _file_store_for_session(session_id: str):
        if not _gcp_enabled():
            return file_store
        return _storage_for_session(session_id).file_store()

    def _mcp_upload_path(stored) -> str:
        destination = Path(upload_dir) / stored.id / Path(stored.name).name
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = Path(stored.path)
            if source.exists() and source.resolve() != destination.resolve():
                shutil.copyfile(source, destination)
        except Exception:
            logger.warning(
                "Failed to mirror chat attachment for MCP file_id=%s",
                getattr(stored, "id", ""),
                exc_info=True,
            )
        return f"/general-chat/uploads/{stored.id}/{Path(stored.name).name}"

    def _attachment_from_stored_file(stored):
        attachment = stored.to_attachment(base_url="/uploads")
        if attachment.type == "image":
            mcp_path = _mcp_upload_path(stored)
            stored.path = mcp_path
            attachment.path = mcp_path
            attachment.extracted_text = image_search_text(stored)
        return attachment

    def _enabled_tool_count(server) -> int:
        return sum(1 for tool in getattr(server, "tools", []) if getattr(tool, "enabled", True))

    def _reload_external_mcp_tools_or_raise(
        *,
        server_ids: set[str] | None = None,
        require_chat_tools: bool = False,
        discovered_tool_count: int = 0,
        enabled_tool_count: int = 0,
    ) -> dict:
        reload_summary = reload_external_mcp_tools(agent, server_ids=server_ids)
        diagnostics = reload_summary.get("diagnostics")
        diagnostic_text = ""
        if isinstance(diagnostics, list) and diagnostics:
            parts = []
            for item in diagnostics:
                if not isinstance(item, dict):
                    continue
                provider = item.get("provider") or "mcp"
                server = item.get("server") or "server"
                error = item.get("connection_error") or item.get("error")
                discovered = item.get("tools_discovered", 0)
                registered = item.get("tools_registered", 0)
                parts.append(
                    f"{provider}/{server}: discovered={discovered}, registered={registered}"
                    + (f", error={error}" if error else "")
                )
            if parts:
                diagnostic_text = " Provider diagnostics: " + " | ".join(parts)
        logger.info(
            "mcp.api.reload discovered=%d enabled=%d available=%s error=%s",
            discovered_tool_count,
            enabled_tool_count,
            reload_summary.get("available_to_chat"),
            reload_summary.get("error"),
        )
        if reload_summary.get("error"):
            raise HTTPException(
                status_code=400,
                detail=(
                    "MCP tools were discovered, but could not be loaded into chat: "
                    f"{reload_summary['error']}{diagnostic_text}"
                ),
            )
        if require_chat_tools and not reload_summary.get("available_to_chat"):
            if discovered_tool_count > 0 and enabled_tool_count == 0:
                detail = (
                    "MCP tools were discovered, but no enabled tools are available to chat. "
                    "Enable at least one discovered tool and load tools again."
                )
            else:
                detail = (
                    "Enabled MCP tools were found, but none were registered with chat. "
                    "Load tools again, and check the MCP server logs if this repeats."
                    f"{diagnostic_text}"
                )
            raise HTTPException(
                status_code=400,
                detail=detail,
            )
        return reload_summary

    def _delete_upload_files_for_records(records: list) -> None:
        for record in records:
            if _is_gcs_source(record):
                continue
            for file_id in upload_file_ids_for_source(record):
                try:
                    file_store.delete(file_id)
                except Exception:
                    logger.warning(
                        "Failed to delete upload file %s for source %s",
                        file_id,
                        getattr(record, "id", ""),
                        exc_info=True,
                    )

    def _cleanup_source_uploads_after_use(records: list) -> None:
        records_with_uploads = [
            record
            for record in records
            if upload_file_ids_for_source(record)
            and not _is_gcs_source(record)
            and getattr(record, "kind", "") not in {"spreadsheet", "image"}
        ]
        if not records_with_uploads:
            return

        _delete_upload_files_for_records(records_with_uploads)
        source_ids = {record.id for record in records_with_uploads}
        session_ids = {record.session_id for record in records_with_uploads}
        for session_id in session_ids:
            current = source_store.list(session_id)
            changed = False
            for record in current:
                if record.id in source_ids and upload_file_ids_for_source(record):
                    mark_source_upload_deleted(record)
                    changed = True
            if changed:
                source_store.save(session_id, current)

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

    # Disable the interactive docs / schema endpoints in deployed environments:
    # they are not behind the auth middleware and would disclose the API surface.
    app = FastAPI(title="General Chat", docs_url=None, redoc_url=None, openapi_url=None)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allowed_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def firebase_auth_middleware(request: Request, call_next):
        if (
            auth_enabled()
            and request.method.upper() != "OPTIONS"
            and _requires_auth_path(request.url.path)
        ):
            try:
                await require_firebase_user(request)
            except HTTPException as exc:
                return JSONResponse(
                    {"detail": exc.detail},
                    status_code=exc.status_code,
                    headers=exc.headers,
                )
        return await call_next(request)

    @app.on_event("startup")
    async def startup() -> None:
        if _env_flag("GENERAL_CHAT_SEED_ALL_MCP", default=False):
            seed_summary = seed_all_mcp_registry(storage_root)
            if seed_summary["errors"]:
                print(f"  MCP seed errors: {seed_summary['errors']}")
            else:
                print(f"  MCP seeded     : {', '.join(seed_summary['seeded']) or '(none)'}")
            reload_external_mcp_tools(agent)
        persona = agent._persona
        summary = persona.summary() if persona else {}
        print("\n  General Chat")
        print(f"  Model          : {agent.model}")
        vlm_summary = getattr(agent, "_vlm_summary", {})
        if isinstance(vlm_summary, dict) and vlm_summary.get("enabled"):
            print(
                "[vision] enabled=True "
                f"model={vlm_summary.get('model')} "
                f"base_url={vlm_summary.get('base_url') or 'google-genai'}"
            )
            print(
                "  Vision model   : "
                f"{vlm_summary.get('provider')} / {vlm_summary.get('model')}"
            )
        else:
            print("[vision] enabled=False model=(none) base_url=(none)")
            print("  Vision model   : disabled")
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
        print(f"  Storage backend: {type(storage).__name__}")
        print(f"  Upload dir     : {upload_dir}")
        print(f"  Download dir   : {download_dir}")
        print(f"  Image previews : {image_search_preview_dir}")
        print(f"  Source max     : {max_source_bytes} bytes")
        print(f"  Multipart max  : {multipart_upload_max_bytes} bytes")
        print(f"  Firebase auth  : {'enabled' if auth_enabled() else 'disabled'}")
        if _gcp_enabled():
            print(f"  GCS bucket     : {os.getenv('GENERAL_CHAT_GCP_BUCKET')}")
        print("  AG-UI          : POST /awp")
        print("  Upload         : POST /chat/upload")
        print("  Attachments    : POST /chat/attachments/upload")
        print("  Direct upload  : POST /chat/uploads/initiate")
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
            secrets = body.get("secrets") if isinstance(body.get("secrets"), dict) else None
            return mcp_registry_store.import_config_json(raw_config, secret_values=secrets)
        except MCPRegistryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/mcp/catalogs/toolhive/import-running")
    async def import_running_toolhive_workloads(request: Request) -> dict:
        body = await request.json()
        names = body.get("names")
        try:
            workloads = toolhive_service.list_workloads()
            if isinstance(names, list) and names:
                requested = {str(name) for name in names}
                workloads = [workload for workload in workloads if workload.name in requested]
            payload = mcp_registry_store.import_toolhive_workloads(workloads)
            return payload
        except ToolHiveError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MCPRegistryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/toolhive/status")
    async def toolhive_status() -> dict:
        return toolhive_service.status().to_dict()

    @app.get("/toolhive/workloads")
    async def toolhive_workloads() -> dict:
        try:
            return {"workloads": [workload.to_dict() for workload in toolhive_service.list_workloads()]}
        except ToolHiveError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/toolhive/workloads")
    async def start_toolhive_workload(request: Request) -> dict:
        body = await request.json()
        try:
            workload = toolhive_service.start_workload(
                str(body.get("target") or body.get("server") or body.get("url") or ""),
                name=str(body.get("name")).strip() if body.get("name") else None,
                allow_remote=bool(body.get("allowRemote") or body.get("allow_remote")),
            )
            return {"workload": workload.to_dict()}
        except ToolHiveError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/toolhive/workloads/{name}/stop")
    async def stop_toolhive_workload(name: str) -> dict:
        try:
            toolhive_service.stop_workload(name)
            return {"ok": True, "name": name}
        except ToolHiveError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/toolhive/workloads/{name}/restart")
    async def restart_toolhive_workload(name: str) -> dict:
        try:
            toolhive_service.restart_workload(name)
            return {"ok": True, "name": name}
        except ToolHiveError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/toolhive/workloads/{name}")
    async def delete_toolhive_workload(name: str) -> dict:
        try:
            toolhive_service.delete_workload(name)
            return {"ok": True, "name": name}
        except ToolHiveError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/toolhive/registry/servers")
    async def toolhive_registry_servers() -> dict:
        try:
            servers = toolhive_service.list_registry_servers()
            return {"servers": [server.to_dict() for server in servers]}
        except ToolHiveError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/mcp/catalogs/{server_id}/refresh")
    async def refresh_mcp_server(server_id: str) -> dict:
        try:
            server = mcp_registry_store.discover_server(server_id)
            reload_summary = _reload_external_mcp_tools_or_raise(
                server_ids={server_id},
                require_chat_tools=bool(server.tools),
                discovered_tool_count=len(server.tools),
                enabled_tool_count=_enabled_tool_count(server),
            )
            return {"server": server.to_dict(detail=True), "reload": reload_summary}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP server not found") from exc
        except MCPRegistryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/mcp/catalogs/{server_id}")
    async def remove_mcp_server(server_id: str) -> dict:
        try:
            mcp_registry_store.remove_server(server_id)
        except MCPRegistryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        reload_summary = reload_external_mcp_tools(agent, server_ids={server_id})
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
        enabled_requested = bool(body.get("enabled", True))
        try:
            server = mcp_registry_store.set_server_enabled(
                server_id,
                enabled_requested,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MCP server not found") from exc
        except MCPRegistryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        reload_summary = _reload_external_mcp_tools_or_raise(
            server_ids={server_id},
            require_chat_tools=enabled_requested and _enabled_tool_count(server) > 0,
            discovered_tool_count=len(server.tools),
            enabled_tool_count=_enabled_tool_count(server),
        )
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
        reload_summary = _reload_external_mcp_tools_or_raise(
            server_ids={server_id},
            require_chat_tools=bool(server.tools),
            discovered_tool_count=len(server.tools),
            enabled_tool_count=_enabled_tool_count(server),
        )
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
        reload_summary = _reload_external_mcp_tools_or_raise(
            server_ids={server_id},
            require_chat_tools=_enabled_tool_count(server) > 0,
            discovered_tool_count=len(server.tools),
            enabled_tool_count=_enabled_tool_count(server),
        )
        return {"server": server.to_dict(detail=True), "reload": reload_summary}

    @app.delete("/mcp/catalogs/servers/{server_id}")
    async def remove_mcp_server_by_id(server_id: str) -> dict:
        try:
            mcp_registry_store.remove_server(server_id)
        except MCPRegistryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        reload_summary = reload_external_mcp_tools(agent, server_ids={server_id})
        return {"ok": True, "serverId": server_id, "reload": reload_summary}

    @app.post("/chat/attachments/upload")
    async def upload_chat_attachment(
        file: UploadFile = File(...),
        session_id: str | None = Form(default=None, alias="sessionId"),
    ) -> dict:
        """Store a transient chat composer attachment for the next message."""
        filename = file.filename or "unnamed"
        mime_type = _resolve_mime(filename, file.content_type or "")
        if mime_type not in _ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported attachment type: {mime_type}")
        target_session_id = session_id or "default"
        content = await _read_upload_limited(file, multipart_upload_max_bytes)
        stored = _file_store_for_session(target_session_id).store(filename, content, mime_type)
        attachment = _attachment_from_stored_file(stored)
        print(
            f"  [chat-attachment-upload] id={stored.id} session={target_session_id!r} "
            f"name={stored.name!r} mime={mime_type} size={stored.size_bytes}B "
            f"path={attachment.path or '(none)'}"
        )
        return attachment.to_dict()

    @app.post("/chat/transcribe")
    async def transcribe_audio(
        file: UploadFile = File(...),
        session_id: str | None = Form(default=None, alias="sessionId"),
    ) -> dict:
        """Transcribe a recorded audio blob to text (mic voice input).

        The browser records ``audio/webm;codecs=opus``, which Gemini does not
        accept, so we transcode to WAV via ffmpeg before transcribing. If ffmpeg
        is unavailable, fall back to the raw bytes.
        """
        import contextlib
        import os
        import tempfile

        content = await _read_upload_limited(file, multipart_upload_max_bytes)
        mime_type = file.content_type or "audio/webm"

        from openbench.intelligence.transcription import get_transcriber
        from openbench.utils.media import transcode_audio_to_wav

        tmp_path: str | None = None
        wav_path: str | None = None
        try:
            suffix = os.path.splitext(file.filename or "")[1] or ".webm"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            wav_path = transcode_audio_to_wav(tmp_path)
            transcriber = get_transcriber()
            if wav_path:
                transcript = transcriber.transcribe(wav_path, mime_type="audio/wav")
            else:
                transcript = transcriber.transcribe(content, mime_type=mime_type)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Transcription failed: {exc}") from exc
        finally:
            for path in (tmp_path, wav_path):
                if path and os.path.exists(path):
                    with contextlib.suppress(OSError):
                        os.unlink(path)
        return {"transcript": transcript.strip()}

    @app.post("/chat/upload")
    async def upload_file(
        file: UploadFile = File(...),
        session_id: str | None = Form(default=None, alias="sessionId"),
    ):
        """Store an uploaded source file and persist extracted text for a session."""
        filename = file.filename or "unnamed"
        mime_type = _resolve_mime(filename, file.content_type or "")
        target_session_id = session_id or "default"
        declared_size = getattr(file, "size", None)
        if isinstance(declared_size, int) and declared_size > multipart_upload_max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"Multipart upload exceeds {multipart_upload_max_bytes} bytes. "
                    "Use /chat/uploads/initiate for direct Cloud Storage uploads."
                ),
            )

        content = await _read_upload_limited(file, multipart_upload_max_bytes)
        user_file_store = _file_store_for_session(target_session_id)
        stored = user_file_store.store(filename, content, mime_type)
        if _gcp_enabled():
            record = _queued_gcs_upload_record(session_id=target_session_id, stored=stored)
            source_store.upsert(record)
            print(
                f"  [source-upload-queued] id={record.id} session={target_session_id!r} "
                f"name={stored.name!r} mime={mime_type} size={stored.size_bytes}B "
                f"file_id={stored.id}"
            )
            return {
                **record.to_dict(include_text=False),
                "url": record.url,
                "type": record.kind,
            }

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
        # that the agent can use as optional context.
        result["url"] = record.url or attachment.url
        result["type"] = attachment.type
        return result

    @app.post("/chat/uploads/initiate")
    async def initiate_large_upload(request: Request) -> dict:
        """Create a direct-to-GCS resumable upload target for large files."""
        if not _gcp_enabled():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Direct Cloud Storage uploads require GENERAL_CHAT_GCP_BUCKET.",
            )
        body = await request.json()
        filename = str(body.get("filename") or body.get("name") or "unnamed")
        session_id = str(body.get("sessionId") or "default")
        declared_size = body.get("sizeBytes", body.get("size"))
        size_bytes = int(declared_size) if declared_size is not None else None
        mime_type = _resolve_mime(filename, str(body.get("mimeType") or body.get("type") or ""))
        user_file_store = _file_store_for_session(session_id)
        upload = user_file_store.create_resumable_upload_session(
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            session_id=session_id,
            origin=request.headers.get("origin"),
        )
        record = SourceRecord.create(
            session_id=session_id,
            name=Path(filename).name or "unnamed",
            kind="file",
            mime_type=mime_type,
            size_bytes=size_bytes or 0,
            url=f"gs://{upload.bucket}/{upload.object_name}",
            text="",
            status="processing",
            metadata={
                "fileId": upload.file_id,
                "gcsBucket": upload.bucket,
                "gcsObject": upload.object_name,
                "uploadStatus": "reserved",
                "parseStatus": "waiting_for_upload",
            },
        )
        source_store.upsert(record)
        return {
            **upload.to_dict(),
            "source": record.to_dict(include_text=False),
            "status": "reserved",
        }

    @app.post("/chat/uploads/complete")
    async def complete_large_upload(request: Request) -> dict:
        """Verify a direct GCS upload and mark its source as queued."""
        if not _gcp_enabled():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Direct Cloud Storage uploads require GENERAL_CHAT_GCP_BUCKET.",
            )
        body = await request.json()
        file_id = str(body.get("fileId") or "")
        session_id = str(body.get("sessionId") or "default")
        if not file_id:
            raise HTTPException(status_code=400, detail="fileId is required.")
        user_file_store = _file_store_for_session(session_id)
        stored = user_file_store.verify_uploaded_object(file_id)
        if stored is None:
            raise HTTPException(
                status_code=404,
                detail="Uploaded object was not found in Cloud Storage.",
            )
        record = source_store.find_by_upload_file_id(file_id, session_id=session_id)
        if record is None:
            record = SourceRecord.create(
                session_id=session_id,
                name=stored.name,
                kind="file",
                mime_type=stored.mime_type,
                size_bytes=stored.size_bytes,
                url=stored.web_view_link,
                text="",
                status="processing",
                metadata={"fileId": file_id},
            )
        metadata = dict(record.metadata or {})
        parse_status = str(metadata.get("parseStatus") or "")
        if record.status in {"ready", "failed"} or parse_status in {"ready", "failed"}:
            metadata.update(
                {
                    "fileId": file_id,
                    "uploadStatus": "uploaded",
                    "gcsUri": stored.web_view_link or record.url or "",
                }
            )
            record.metadata = metadata
            source_store.upsert(record)
            return {
                "status": metadata.get("parseStatus") or record.status,
                "fileId": file_id,
                "source": record.to_dict(include_text=False),
            }
        metadata.update(
            {
                "fileId": file_id,
                "uploadStatus": "uploaded",
                "parseStatus": "queued",
                "gcsUri": stored.web_view_link or record.url or "",
            }
        )
        record.metadata = metadata
        record.size_bytes = stored.size_bytes
        record.mime_type = stored.mime_type
        record.status = "processing"
        source_store.upsert(record)
        return {
            "status": "queued",
            "fileId": file_id,
            "source": record.to_dict(include_text=False),
        }

    @app.get("/chat/uploads/{file_id}")
    async def get_large_upload(
        file_id: str,
        sessionId: str | None = None,
        includeText: bool = False,
    ) -> dict:
        record = source_store.find_by_upload_file_id(file_id, session_id=sessionId)
        if record is None:
            raise HTTPException(status_code=404, detail="Upload not found.")
        file_id_value = str((record.metadata or {}).get("fileId") or file_id)
        return {
            "status": (record.metadata or {}).get("parseStatus") or record.status,
            "fileId": file_id_value,
            "source": record.to_dict(include_text=includeText),
        }

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
        records = source_store.list(thread_id)
        target = next((record for record in records if record.id == source_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="Source not found")
        _delete_upload_files_for_records([target])
        deleted = source_store.delete(thread_id, source_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Source not found")
        return {"ok": True, "sourceId": source_id}

    @app.delete("/chat/sources/{thread_id}")
    async def clear_sources(thread_id: str) -> dict:
        """Remove all stored sources for a session."""
        _delete_upload_files_for_records(source_store.list(thread_id))
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
            memory_store=chat_memory_store,
            source_records=source_records,
            on_stream_complete=_cleanup_source_uploads_after_use,
            mcp_permission_coordinator=mcp_permission_coordinator,
        )
        return await handler.handle(request)

    @app.post("/chat/action")
    async def chat_action(request: Request):
        body = await request.json()
        session_id = _resolve_request_session_id(body)
        session = _resolve_session(session_id)
        engine = _build_engine(session)
        handler = AGUIActionHandler(engine=engine)

        @handler.on("mcp_permission_decision")
        def handle_mcp_permission(action):
            return mcp_permission_coordinator.resolve_action(action)

        return await handler.handle(request)

    @app.get("/chat/actions")
    async def list_actions() -> dict:
        handler = AGUIActionHandler(engine=None)
        handler.register("mcp_permission_decision", lambda action: [])
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
        _delete_upload_files_for_records(source_store.list(session_id))
        source_store.clear(session_id)
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
