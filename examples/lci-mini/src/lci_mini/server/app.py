"""FastAPI application for LCI Mini.

Wires the Lici agent (with persona loaded from ``soul/``) through
ChatEngine + AG-UI transport, giving each thread its own SQLite-backed
persistent memory.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lci_mini.agent import create_lici_agent, get_persona_dir
from lci_mini.server.handler import LiciAGUIHandler
from openbench.chat import ChatEngine
from openbench.chat.transport import AGUIActionHandler


def create_app() -> FastAPI:
    """Create and configure the LCI Mini FastAPI app."""
    # Load .env from the example directory if present
    load_dotenv(get_persona_dir().parent / ".env")

    agent = create_lici_agent()
    engine = ChatEngine(agent=agent)

    db_path = os.getenv("LCI_MINI_MEMORY_DB", "lci_mini_memory.db")
    agui_handler = LiciAGUIHandler(engine=engine, db_path=db_path)
    action_handler = AGUIActionHandler(engine=engine)

    app = FastAPI(title="LCI Mini — Persona Layer Demo")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    persona = agent._persona

    @app.on_event("startup")
    async def startup() -> None:
        summary = persona.summary() if persona else {}
        print("\n  LCI Mini — Persona Layer Demo")
        print(f"  Model          : {agent.model}")
        print(f"  Persona source : {summary.get('source', '(none)')}")
        if persona:
            print(f"  SOUL.md        : {summary['soul_chars']:>5} chars")
            print(f"  STYLE.md       : {summary['style_chars']:>5} chars")
            print(f"  AGENTS.md      : {summary['agents_chars']:>5} chars")
            print(f"  Persona total  : {summary['total_chars']:>5} chars")
        if agent._skill_registry:
            skill_summary = agent._skill_registry.summary()
            print(
                f"  Skills loaded  : {skill_summary['total']} "
                f"(tools={skill_summary['total_tools']}, "
                f"context={skill_summary['context_chars']} chars)"
            )
            for s in agent._skill_registry.all():
                tool_names = [name for name, _, _ in s.tools]
                label = f"tools={tool_names}" if tool_names else "knowledge-only"
                print(f"    - {s.name} v{s.version}: {label}")
        print(f"  Memory DB      : {db_path}")
        print("  AG-UI          : POST /awp")
        print("  Actions        : POST /chat/action\n")

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

    @app.get("/persona")
    async def persona_info() -> dict:
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
    async def skills_info() -> dict:
        """Expose loaded skills so the UI can show which capabilities are wired.

        Returns one entry per skill with name, version, source path, tool
        names, and reference files. Used by the frontend sidebar badge to
        render a compact skill inventory.
        """
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

    @app.post("/awp")
    async def agent_endpoint(request: Request):
        return await agui_handler.handle(request)

    @app.post("/chat/action")
    async def chat_action(request: Request):
        return await action_handler.handle(request)

    @app.get("/chat/actions")
    async def list_actions():
        return {"actions": action_handler.get_registered_actions()}

    # Optional: serve built frontend in production (Cloud Run single-container mode)
    static_dir = os.environ.get("LCI_MINI_STATIC_DIR")
    if static_dir and os.path.isdir(static_dir):

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            file_path = os.path.join(static_dir, full_path)
            if os.path.isfile(file_path):
                return FileResponse(file_path)
            return FileResponse(os.path.join(static_dir, "index.html"))

        app.mount(
            "/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets"
        )

    return app
