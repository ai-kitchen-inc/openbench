"""
FastAPI chat server for the demo.

Provides three endpoints:
  - POST /chat/stream  -> SSE (progressive message streaming)
  - POST /chat/action  -> JSON (button clicks, form submits)
  - POST /chat/upload  -> JSON (file upload, returns attachment metadata)

Requires GOOGLE_API_KEY for the Gemini agent.

Run:
    export GOOGLE_API_KEY=your-key-here
    uvicorn server:app --port 8000 --reload
"""

import asyncio
import os
import sys

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from openbench.chat import ChatEngine
from openbench.chat.files import FileContentExtractor, FileStore
from openbench.chat.transport.sse import ChatSSEHandler

# ── Agent: Gemini (required) ──

if not os.getenv("GOOGLE_API_KEY"):
    print("\n  ERROR: GOOGLE_API_KEY is required.")
    print("  Set it with: export GOOGLE_API_KEY=your-key-here\n")
    sys.exit(1)

from gemini_agent import clear_render_items, create_gemini_agent, get_render_items, set_attachments

agent = create_gemini_agent()

# Wire: Agent -> ChatEngine -> Transport (with render items from visualization tools)
engine = ChatEngine(agent=agent, render_items_fn=get_render_items)
sse_handler = ChatSSEHandler(engine=engine)

# File upload
file_store = FileStore(upload_dir="./uploads")
extractor = FileContentExtractor()

app = FastAPI(title="OpenBench Chat Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    print("\n  OpenBench Chat Demo")
    print(f"  Agent: Gemini ({agent.model})")
    print("  SSE:    POST http://localhost:8000/chat/stream")
    print("  Action: POST http://localhost:8000/chat/action")
    print("  Upload: POST http://localhost:8000/chat/upload\n")


@app.post("/chat/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file for chat attachments.

    Stores the file on disk, extracts text content (PDF, text files),
    and returns metadata for the frontend to attach to messages.
    """
    content = await file.read()
    stored = file_store.store(
        file.filename or "unnamed",
        content,
        file.content_type or "application/octet-stream",
    )
    stored.extracted_text = await asyncio.to_thread(extractor.extract, stored)

    attachment = stored.to_attachment(base_url="/uploads")
    result = attachment.to_dict()
    if stored.extracted_text:
        result["extractedText"] = stored.extracted_text[:2000]
    return result


@app.post("/chat/stream")
async def chat_stream(request: Request):
    """SSE endpoint for progressive message streaming.

    Streams step-by-step progress and A2UI messages as SSE events.
    Each event is delivered immediately via HTTP chunked transfer encoding.
    """
    body = await request.json()

    # Clear render items from previous request before agent executes
    clear_render_items()

    # Resolve uploaded file paths so agent tools can read full content from disk
    file_metas = []
    for att in body.get("attachments", []):
        file_id = att.get("id")
        if not file_id:
            continue
        stored = file_store.get(file_id)
        if not stored:
            continue
        file_metas.append({
            "name": stored.name,
            "path": stored.path,
            "mime_type": stored.mime_type,
        })
    set_attachments(file_metas or None)

    return StreamingResponse(
        sse_handler.stream(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/chat/action")
async def chat_action(request: Request):
    """REST endpoint for A2UI actions (button clicks, form submits).

    Returns response messages as a JSON array.
    """
    body = await request.json()
    result = await asyncio.to_thread(
        engine.invoke,
        {
            "content": f"[Action: {body.get('name')}]",
            "action": {
                "name": body.get("name"),
                "surfaceId": body.get("surfaceId"),
                "sourceComponentId": body.get("sourceComponentId"),
                "context": body.get("context", {}),
            },
        },
    )
    return result.get("messages", [])


@app.get("/")
async def root():
    return {
        "status": "ok",
        "agent": "gemini",
        "model": agent.model,
        "endpoints": {
            "sse": "POST /chat/stream",
            "action": "POST /chat/action",
            "upload": "POST /chat/upload",
        },
    }


# Mount static files AFTER route definitions so routes take priority
os.makedirs("./uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="./uploads"), name="uploads")
