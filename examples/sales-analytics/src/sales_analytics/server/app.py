"""FastAPI application for Sales Analytics demo.

Minimal server: persona + SDK skills only. No project skills, no xql,
no domain-specific render queue. Uses the shared render_queue from
openbench.chat for chart/file visualization.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from openbench.chat import ChatEngine
from openbench.chat import render_queue as shared_render_queue
from openbench.chat.files import FileContentExtractor, FileStore
from openbench.chat.transport import AGUIActionHandler, AGUIHandler
from sales_analytics.agent import create_analyst_agent, get_persona_dir


def create_app() -> FastAPI:
    """Create the Sales Analytics FastAPI app."""
    load_dotenv(get_persona_dir().parent / ".env")

    agent = create_analyst_agent()

    # SDK skills push to the shared render queue (charts, files).
    # No project skill queue to merge — just the shared one.
    engine = ChatEngine(
        agent=agent,
        render_items_fn=shared_render_queue.get_items,
        clear_render_items_fn=shared_render_queue.clear,
    )

    agui_handler = AGUIHandler(engine)
    action_handler = AGUIActionHandler(engine=engine)

    # Directories
    example_root = get_persona_dir().parent
    upload_dir = str((example_root / "uploads").resolve())
    download_dir = str((example_root / "downloads").resolve())
    profile_dir = str((example_root / "profiles").resolve())

    for d in (upload_dir, download_dir, profile_dir):
        os.makedirs(d, exist_ok=True)

    os.environ["OPENBENCH_EXPORT_DIR"] = download_dir
    os.environ["OPENBENCH_EXPORT_URL_BASE"] = "/downloads"
    os.environ["OPENBENCH_PROFILE_DIR"] = profile_dir

    file_store = FileStore(upload_dir=upload_dir)
    extractor = FileContentExtractor()

    app = FastAPI(title="Sales Analytics — SDK Skills Demo")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup() -> None:
        print("\n  Sales Analytics — SDK Skills Demo")
        print(f"  Model        : {agent.model}")
        print(f"  Persona      : {get_persona_dir()}")
        print(f"  Upload dir   : {upload_dir}")
        print(f"  Download dir : {download_dir}")
        print(f"  Profile dir  : {profile_dir}")
        if agent._skill_registry:
            s = agent._skill_registry.summary()
            print(f"  SDK skills   : {s['total']} ({s['total_tools']} tools)")
        print("  AG-UI        : POST /awp\n")

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "sales-analytics"}

    @app.post("/chat/upload")
    async def upload_file(file: UploadFile = File(...)):
        content = await file.read()
        stored = file_store.store(
            file.filename or "unnamed",
            content,
            file.content_type or "application/octet-stream",
        )
        stored.extracted_text = extractor.extract(stored)
        attachment = stored.to_attachment(base_url="/uploads")
        result = attachment.to_dict()
        if stored.extracted_text:
            result["extractedText"] = stored.extracted_text[:2000]
        return result

    @app.post("/awp")
    async def agent_endpoint(request):

        return await agui_handler.handle(request)

    @app.post("/chat/action")
    async def chat_action(request):

        return await action_handler.handle(request)

    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")
    app.mount("/downloads", StaticFiles(directory=download_dir), name="downloads")

    return app
