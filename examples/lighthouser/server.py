"""
FastAPI server for the Lighthouser SEMAP compliance demo.

Provides endpoints:
  - POST /awp          -> SSE (AG-UI protocol event stream)
  - POST /chat/action  -> JSON (A2UI button clicks, form submits)
  - POST /chat/upload  -> JSON (file upload, returns attachment metadata)

Features:
  - Task Planning: agent decomposes complex reviews into steps
  - Parallel Tool Execution: multiple SEMAP checks run concurrently
  - Persistent Memory: conversations persist across server restarts (SQLite)

Requires GOOGLE_API_KEY for the Gemini agent.

Run:
    export GOOGLE_API_KEY=your-key-here
    uvicorn server:app --port 8001 --reload
"""

import asyncio
import copy
import os
import sys
import threading

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from mock_data import MARKET_COMPARABLES, PAYMENT_STANDARDS
from semap_engine import (
    calculate_hap as _calc_hap,
)
from semap_engine import (
    calculate_hud_deductions,
    validate_rent_reasonableness,
)
from semap_engine import (
    calculate_ttp as _calc_ttp,
)
from semap_engine import (
    check_rent_burden as _check_burden,
)

from openbench.chat import ChatEngine
from openbench.chat.a2ui.schema import A2UIComponent
from openbench.chat.files import FileContentExtractor, LocalFileStore
from openbench.chat.transport import ActionData, AGUIActionHandler, AGUIHandler
from openbench.intelligence.base import AgentMemory, BaseAgent, MessageRole
from openbench.intelligence.memory import PersistentMemory, SQLiteMemoryStore

# ── Agent: Gemini (required) ──

if not os.getenv("GOOGLE_API_KEY"):
    print("\n  ERROR: GOOGLE_API_KEY is required.")
    print("  Set it with: export GOOGLE_API_KEY=your-key-here\n")
    sys.exit(1)

from semap_agent import (
    clear_render_items,
    create_semap_agent,
    get_render_items,
    set_attachments,
)

# ── Persistent Memory Setup ──

DB_PATH = os.getenv("CHAT_MEMORY_DB", "lighthouser_memory.db")


# ── Custom AG-UI Handler with Persistent Memory ──


class AgenticAGUIHandler(AGUIHandler):
    """AG-UI handler with per-session persistent memory for SEMAP reviews."""

    def __init__(self, engine, db_path: str = "lighthouser_memory.db"):
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


agent = create_semap_agent(
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


@action_handler.on("submit_rfta_review")
def handle_rfta_review(action: ActionData):
    """Run full SEMAP calculations from the RFTA review form and return A2UI results."""
    data = action.context

    # Parse form fields with safe defaults
    proposed_rent = float(data.get("proposed_rent", 0) or 0)
    utility_allowance = float(data.get("utility_allowance", 0) or 0)
    bedrooms = int(data.get("bedrooms", 2) or 2)
    area = str(data.get("area", "downtown") or "downtown")
    annual_gross_income = float(data.get("annual_gross_income", 0) or 0)
    dependents = int(data.get("dependents", 0) or 0)
    elderly_disabled = bool(data.get("elderly_disabled", False))
    medical_expenses = float(data.get("medical_expenses", 0) or 0)
    childcare_expenses = float(data.get("childcare_expenses", 0) or 0)
    disability_assistance = float(data.get("disability_assistance", 0) or 0)
    voucher_id = str(data.get("voucher_id", "") or "")
    tenant_name = str(data.get("tenant_name", "") or "")

    # 1. Calculate deductions & adjusted income
    deductions = calculate_hud_deductions(
        gross_income=annual_gross_income,
        dependents=dependents,
        elderly_disabled=elderly_disabled,
        medical_expenses=medical_expenses,
        childcare_expenses=childcare_expenses,
        disability_assistance=disability_assistance,
    )
    adjusted_income = deductions["adjusted_income"]

    # 2. Calculate TTP
    ttp_result = _calc_ttp(
        adjusted_income=adjusted_income,
        gross_income=annual_gross_income,
    )

    # 3. Calculate HAP
    ps = PAYMENT_STANDARDS.get(area, {}).get(bedrooms, 1500)
    hap_result = _calc_hap(
        payment_standard=ps,
        ttp=ttp_result["selected_ttp"],
        rent=proposed_rent,
        utility_allowance=utility_allowance,
    )

    # 4. Check rent burden
    burden = _check_burden(
        rent=proposed_rent,
        utility_allowance=utility_allowance,
        hap=hap_result["hap"],
        adjusted_income=adjusted_income,
    )

    # 5. Rent reasonableness
    comps = MARKET_COMPARABLES.get(area, {}).get(bedrooms, [])
    rr = validate_rent_reasonableness(proposed_rent, comps)

    # ── Build A2UI components ──
    components: list[A2UIComponent] = []
    col_children: list[str] = []

    # Header
    header_id = "rfta-header"
    header_text = "SEMAP Review Results"
    if voucher_id:
        header_text += f" -- {voucher_id}"
    if tenant_name:
        header_text += f" ({tenant_name})"
    components.append(
        A2UIComponent(
            id=header_id,
            component="Text",
            properties={"text": header_text, "variant": "h4"},
        )
    )
    col_children.append(header_id)

    # Table 1: Income & Deductions
    inc_table_id = "rfta-income-table"
    components.append(
        A2UIComponent(
            id=inc_table_id,
            component="ObTable",
            properties={
                "title": "Income & Deductions (24 CFR 5.611)",
                "headers": ["Item", "Amount"],
                "rows": [
                    ["Gross Annual Income", f"${annual_gross_income:,.0f}"],
                    [
                        f"Dependent Deduction ({dependents} x $480)",
                        f"-${deductions['dependent_deduction']:,.0f}",
                    ],
                    [
                        "Elderly/Disabled Deduction",
                        f"-${deductions['elderly_disabled_deduction']:,.0f}",
                    ],
                    [
                        "Medical Expenses (excess over 3%)",
                        f"-${deductions['medical_deduction']:,.2f}",
                    ],
                    ["Childcare Deduction", f"-${deductions['childcare_deduction']:,.0f}"],
                    [
                        "Disability Assistance",
                        f"-${deductions['disability_assistance_deduction']:,.0f}",
                    ],
                    ["Total Deductions", f"-${deductions['total_deductions']:,.2f}"],
                    ["Adjusted Annual Income", f"${adjusted_income:,.2f}"],
                ],
                "compact": True,
            },
        )
    )
    col_children.append(inc_table_id)

    # Table 2: TTP 4-method breakdown
    check = "\u2713"
    ttp_table_id = "rfta-ttp-table"
    components.append(
        A2UIComponent(
            id=ttp_table_id,
            component="ObTable",
            properties={
                "title": "Total Tenant Payment (24 CFR 5.628)",
                "headers": ["Method", "Monthly Amount", ""],
                "rows": [
                    [
                        "30% Adjusted",
                        f"${ttp_result['30pct_adjusted']:,.2f}",
                        check if ttp_result["selected_method"] == "30% adjusted" else "",
                    ],
                    [
                        "10% Gross",
                        f"${ttp_result['10pct_gross']:,.2f}",
                        check if ttp_result["selected_method"] == "10% gross" else "",
                    ],
                    [
                        "Welfare Rent",
                        f"${ttp_result['welfare_rent']:,.2f}",
                        check if ttp_result["selected_method"] == "welfare rent" else "",
                    ],
                    [
                        "Minimum Rent",
                        f"${ttp_result['minimum_rent']:,.2f}",
                        check if ttp_result["selected_method"] == "minimum rent" else "",
                    ],
                    [
                        f"TTP ({ttp_result['selected_method']})",
                        f"${ttp_result['selected_ttp']:,.2f}",
                        check,
                    ],
                ],
                "caption": "TTP = Greatest of all 4 methods",
                "compact": True,
            },
        )
    )
    col_children.append(ttp_table_id)

    # Table 3: HAP calculation
    hap_table_id = "rfta-hap-table"
    components.append(
        A2UIComponent(
            id=hap_table_id,
            component="ObTable",
            properties={
                "title": "Housing Assistance Payment (24 CFR 982.505)",
                "headers": ["Component", "Amount"],
                "rows": [
                    ["Payment Standard", f"${hap_result['payment_standard']:,.2f}"],
                    ["TTP", f"${hap_result['ttp']:,.2f}"],
                    ["Contract Rent", f"${hap_result['contract_rent']:,.2f}"],
                    ["Utility Allowance", f"${hap_result['utility_allowance']:,.2f}"],
                    ["Gross Rent (Rent + UA)", f"${hap_result['gross_rent']:,.2f}"],
                    ["HAP from Standard (PS - TTP)", f"${hap_result['hap_from_standard']:,.2f}"],
                    ["HAP from Rent (GR - TTP)", f"${hap_result['hap_from_rent']:,.2f}"],
                    ["HAP (Lesser)", f"${hap_result['hap']:,.2f}"],
                    ["Tenant Share (GR - HAP)", f"${hap_result['tenant_share']:,.2f}"],
                ],
                "compact": True,
            },
        )
    )
    col_children.append(hap_table_id)

    # Callout: Rent burden
    burden_id = "rfta-burden-callout"
    if burden["passes"]:
        components.append(
            A2UIComponent(
                id=burden_id,
                component="ObCallout",
                properties={
                    "variant": "success",
                    "title": "Rent Burden Check (24 CFR 982.508)",
                    "message": (
                        f"PASSED -- Rent burden: {burden['burden_pct']}% "
                        f"(threshold: {burden['threshold_pct']}%). "
                        f"Family share: ${burden['family_share']:,.2f}/month."
                    ),
                },
            )
        )
    else:
        components.append(
            A2UIComponent(
                id=burden_id,
                component="ObCallout",
                properties={
                    "variant": "warning",
                    "title": "Rent Burden Check (24 CFR 982.508)",
                    "message": (
                        f"FAILED -- Rent burden: {burden['burden_pct']}% "
                        f"exceeds {burden['threshold_pct']}% threshold. "
                        f"Family share: ${burden['family_share']:,.2f}/month. "
                        f"Unit cannot be approved at initial occupancy."
                    ),
                },
            )
        )
    col_children.append(burden_id)

    # Callout: Rent reasonableness
    rr_id = "rfta-rr-callout"
    if rr["passes"]:
        components.append(
            A2UIComponent(
                id=rr_id,
                component="ObCallout",
                properties={
                    "variant": "success",
                    "title": "Rent Reasonableness (24 CFR 982.507)",
                    "message": (
                        f"PASSED -- Proposed ${proposed_rent:,.0f} vs "
                        f"market average ${rr['average_comparable']:,.0f} "
                        f"(ratio: {rr['ratio']:.3f})."
                    ),
                },
            )
        )
    else:
        components.append(
            A2UIComponent(
                id=rr_id,
                component="ObCallout",
                properties={
                    "variant": "warning",
                    "title": "Rent Reasonableness (24 CFR 982.507)",
                    "message": (
                        f"FAILED -- Proposed ${proposed_rent:,.0f} exceeds "
                        f"market average ${rr['average_comparable']:,.0f} "
                        f"(ratio: {rr['ratio']:.3f}). "
                        f"Rent reduction or additional justification required."
                    ),
                },
            )
        )
    col_children.append(rr_id)

    # Root Column
    components.append(
        A2UIComponent(
            id="root",
            component="Column",
            properties={"children": col_children, "gap": "16px"},
        )
    )

    return [engine.builder.build_update_components(action.surface_id, components)]


# File upload
file_store = LocalFileStore(upload_dir="./uploads")
extractor = FileContentExtractor()

app = FastAPI(title="Lighthouser AI - SEMAP Compliance Copilot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    print("\n  Lighthouser AI - SEMAP Compliance Copilot")
    print(f"  Agent: Gemini ({agent.model})")
    print(f"  Memory DB: {DB_PATH}")
    print("  Features: planning, parallel-tools, persistent-memory")
    print("  AG-UI: POST http://localhost:8001/awp")
    print("  Action: POST http://localhost:8001/chat/action")
    print("  Upload: POST http://localhost:8001/chat/upload\n")


@app.post("/chat/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file for chat attachments (RFTA, paystubs, leases)."""
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
