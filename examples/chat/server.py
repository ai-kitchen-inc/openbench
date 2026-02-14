"""
FastAPI chat server for the demo.

Provides two transports:
  - WebSocket at /chat/ws     (bidirectional, for actions)
  - SSE at POST /chat/stream  (progressive streaming, preferred for messages)

Auto-detects GOOGLE_API_KEY:
  - If set:  uses real Gemini agent (BaseAgent + tools + reasoning loop)
  - If not:  falls back to MockAgent (no API key needed)

Run:
    uvicorn server:app --port 8000 --reload
"""

import os

from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from openbench.chat import ChatEngine
from openbench.chat.transport.sse import ChatSSEHandler
from openbench.chat.transport.websocket import ChatWebSocketServer

# ── Agent selection: real Gemini or mock ──

if os.getenv("GOOGLE_API_KEY"):
    from gemini_agent import create_gemini_agent

    agent = create_gemini_agent()
    agent_mode = "gemini"
else:
    from mock_agent import MockAgent

    agent = MockAgent()
    agent_mode = "mock"

# Wire: Agent -> ChatEngine -> Transports
engine = ChatEngine(agent=agent)
ws_server = ChatWebSocketServer(engine=engine)
sse_handler = ChatSSEHandler(engine=engine)

app = FastAPI(title="OpenBench Chat Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    mode_label = (
        f"Gemini ({agent.model})" if agent_mode == "gemini" else "MockAgent (no API key)"
    )
    print(f"\n  OpenBench Chat Demo")
    print(f"  Agent: {mode_label}")
    print(f"  WebSocket: ws://localhost:8000/chat/ws")
    print(f"  SSE:       POST http://localhost:8000/chat/stream\n")


@app.websocket("/chat/ws")
async def chat_ws(websocket: WebSocket):
    await ws_server.handle(websocket)


@app.post("/chat/stream")
async def chat_stream(request: Request):
    """SSE endpoint for progressive message streaming.

    Streams step-by-step progress and A2UI messages as SSE events.
    Each event is delivered immediately via HTTP chunked transfer encoding.
    """
    body = await request.json()
    return StreamingResponse(
        sse_handler.stream(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/")
async def root():
    return {
        "status": "ok",
        "agent": agent_mode,
        "endpoints": {
            "websocket": "ws://localhost:8000/chat/ws",
            "sse": "POST /chat/stream",
        },
    }
