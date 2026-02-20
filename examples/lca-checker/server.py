"""
FastAPI server for the LCA Compliance Checker demo.

Provides endpoints:
  - POST /awp          -> SSE (AG-UI protocol event stream)
  - POST /chat/action  -> JSON (A2UI button clicks, form submits)
  - POST /chat/upload  -> JSON (file upload, returns attachment metadata)

Features:
  - Task Planning: agent decomposes complex reviews into steps
  - Parallel Tool Execution: multiple compliance checks run concurrently
  - Persistent Memory: conversations persist across server restarts (SQLite)

Requires GOOGLE_API_KEY for the Gemini agent.

Run:
    export GOOGLE_API_KEY=your-key-here
    uvicorn server:app --port 8002 --reload
"""

import asyncio
import copy
import os
import sys
import threading

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from openbench.chat import ChatEngine
from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.files import FileContentExtractor, FileStore
from openbench.chat.transport import ActionData, AGUIActionHandler, AGUIHandler
from openbench.intelligence.base import AgentMemory, BaseAgent, MessageRole
from openbench.intelligence.memory import PersistentMemory, SQLiteMemoryStore

# ── Agent: Gemini (required) ──

if not os.getenv("GOOGLE_API_KEY"):
    print("\n  ERROR: GOOGLE_API_KEY is required.")
    print("  Set it with: export GOOGLE_API_KEY=your-key-here\n")
    sys.exit(1)

from lca_agent import (
    clear_render_items,
    create_lca_agent,
    get_render_items,
    set_attachments,
)

# ── Persistent Memory Setup ──

DB_PATH = os.getenv("CHAT_MEMORY_DB", "lca_checker_memory.db")


# ── Custom AG-UI Handler with Persistent Memory ──


class AgenticAGUIHandler(AGUIHandler):
    """AG-UI handler with per-session persistent memory for LCA reviews."""

    def __init__(self, engine, db_path: str = "lca_checker_memory.db"):
        super().__init__(engine)
        self._memory_store = SQLiteMemoryStore(db_path=db_path)
        self._current_session_id: str | None = None
        self._session_lock = threading.Lock()

    def _get_or_create_session(self, session_id):
        """Track current session_id for agent creation, then delegate."""
        with self._session_lock:
            self._current_session_id = session_id
        return super()._get_or_create_session(session_id)

    def _create_request_agent(self):
        """Create a request-scoped agent with persistent memory."""
        agent = self.engine.agent
        if not isinstance(agent, BaseAgent):
            return agent

        agent_copy = copy.copy(agent)

        with self._session_lock:
            session_id = self._current_session_id

        if session_id and self._memory_store:
            agent_copy.memory = PersistentMemory(
                store=self._memory_store,
                session_id=session_id,
            )
        else:
            agent_copy.memory = AgentMemory()

        # Add system prompt if not already present
        if (
            not agent_copy.memory.messages
            or agent_copy.memory.messages[0].role != MessageRole.SYSTEM
        ):
            agent_copy.memory.add_system(agent._system_prompt)

        # Share LLM provider and tools (thread-safe, read-only)
        agent_copy._llm = agent._llm
        agent_copy.tools = agent.tools
        return agent_copy


agent = create_lca_agent(
    model="gemini-2.5-flash",
    temperature=0.3,
    enable_planning=True,
    parallel_tool_execution=True,
)

# Wire: Agent -> ChatEngine -> AG-UI Transport
engine = ChatEngine(
    agent=agent,
    render_items_fn=get_render_items,
    clear_render_items_fn=clear_render_items,
)
agui_handler = AgenticAGUIHandler(engine=engine, db_path=DB_PATH)
action_handler = AGUIActionHandler(engine=engine)


@action_handler.on("submit_compliance_review")
def handle_compliance_review(action: ActionData):
    """Handle compliance review form submission."""
    data = action.context
    study_id = data.get("study_id", "")
    notes = data.get("reviewer_notes", "")

    from lca_engine import (
        check_iso_compliance,
        check_pcr_compliance,
        check_pedoman_klh_compliance,
        generate_compliance_summary,
    )
    from mock_data import COMPANY_PROFILES, LCA_STUDIES

    study = LCA_STUDIES.get(study_id)
    if not study:
        components = [
            A2UIComponent(
                id="error-callout",
                component="ObCallout",
                properties={
                    "variant": "warning",
                    "title": "Study Not Found",
                    "message": f"LCA study '{study_id}' not found.",
                },
            ),
            A2UIComponent(
                id="root",
                component="Column",
                properties={"children": ["error-callout"], "gap": "12px"},
            ),
        ]
        return [engine.builder.build_update_components(action.surface_id, components)]

    # Run compliance checks
    iso_result = check_iso_compliance(study, "all")
    company_id = study.get("company_id")
    company = COMPANY_PROFILES.get(company_id) if company_id else None
    industry = company["industry"] if company else ""

    pcr_result = check_pcr_compliance(study, industry) if industry else None
    klh_result = check_pedoman_klh_compliance(study)
    summary = generate_compliance_summary(iso_result, pcr_result, klh_result)

    # Build result components
    variant = "success" if summary["overall_score"] >= 80 else "warning"
    callout_msg = (
        f"Score: {summary['overall_score']}% ({summary['status']})\n"
        f"Passed: {summary['passed']}/{summary['total_checks']}"
    )
    if notes:
        callout_msg += f"\n\nReviewer notes: {notes}"

    # Summary table rows
    table_headers = ["Phase", "Passed", "Failed"]
    table_rows = []
    from standards_data import ISO_REQUIREMENTS

    for phase, checks in iso_result.items():
        phase_title = ISO_REQUIREMENTS.get(phase, {}).get("title", phase)
        p = sum(1 for c in checks if c["status"] == "pass")
        f = sum(1 for c in checks if c["status"] == "fail")
        table_rows.append([phase_title, str(p), str(f)])

    components = [
        A2UIComponent(
            id="review-callout",
            component="ObCallout",
            properties={
                "variant": variant,
                "title": f"Compliance Review: {study_id}",
                "message": callout_msg,
            },
        ),
        A2UIComponent(
            id="review-table",
            component="ObTable",
            properties={
                "headers": table_headers,
                "rows": table_rows,
                "compact": True,
            },
        ),
        A2UIComponent(
            id="root",
            component="Column",
            properties={
                "children": ["review-callout", "review-table"],
                "gap": "12px",
            },
        ),
    ]

    return [engine.builder.build_update_components(action.surface_id, components)]


@action_handler.on("submit_form")
def handle_form_submit(action: ActionData):
    """Replace form with submission confirmation."""
    data = action.context
    filled = {k: v for k, v in data.items() if v}

    if not filled:
        components = [
            A2UIComponent(
                id="confirm-callout",
                component="ObCallout",
                properties={
                    "variant": "warning",
                    "title": "No data submitted",
                    "message": "The form was submitted without any values.",
                },
            ),
            A2UIComponent(
                id="root",
                component="Column",
                properties={"children": ["confirm-callout"], "gap": "12px"},
            ),
        ]
    else:
        headers = ["Field", "Value"]
        rows = [[k, str(v)] for k, v in filled.items()]

        components = [
            A2UIComponent(
                id="confirm-callout",
                component="ObCallout",
                properties={
                    "variant": "success",
                    "title": "Form submitted successfully",
                    "message": f"{len(filled)} field(s) received.",
                },
            ),
            A2UIComponent(
                id="confirm-table",
                component="ObTable",
                properties={
                    "headers": headers,
                    "rows": rows,
                    "compact": True,
                },
            ),
            A2UIComponent(
                id="root",
                component="Column",
                properties={
                    "children": ["confirm-callout", "confirm-table"],
                    "gap": "12px",
                },
            ),
        ]

    return [engine.builder.build_update_components(action.surface_id, components)]


# File upload
file_store = FileStore(upload_dir="./uploads")
extractor = FileContentExtractor()

app = FastAPI(title="LCA Compliance Checker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    print("\n  LCA Compliance Checker")
    print(f"  Agent: Gemini ({agent.model})")
    print(f"  Memory DB: {DB_PATH}")
    print("  Features: planning, parallel-tools, persistent-memory")
    print("  AG-UI: POST http://localhost:8002/awp")
    print("  Action: POST http://localhost:8002/chat/action")
    print("  Upload: POST http://localhost:8002/chat/upload\n")


@app.post("/chat/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file for chat attachments (LCA reports, profiles)."""
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


@app.post("/awp")
async def agent_endpoint(request: Request):
    """AG-UI protocol endpoint with persistent memory."""
    body = await request.json()

    # Resolve uploaded file paths
    forwarded = body.get("forwardedProps") or {}
    attachments_list = forwarded.get("attachments") or body.get("attachments") or []

    file_metas = []
    for att in attachments_list:
        file_id = att.get("id")
        if not file_id:
            continue
        stored = file_store.get(file_id)
        if not stored:
            continue
        file_metas.append(
            {
                "name": stored.name,
                "path": stored.path,
                "mime_type": stored.mime_type,
            }
        )
    set_attachments(file_metas or None)

    return await agui_handler.handle(request)


@app.post("/chat/action")
async def chat_action(request: Request):
    """REST endpoint for A2UI actions."""
    return await action_handler.handle(request)


@app.get("/chat/actions")
async def list_actions():
    """Schema endpoint: list registered action names."""
    return {"actions": action_handler.get_registered_actions()}


# Mount static files AFTER route definitions
os.makedirs("./uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="./uploads"), name="uploads")
