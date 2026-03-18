"""FastAPI application for LCI Ignite X.

Provides AG-UI SSE streaming, A2UI action handling, and file upload
for the LCA analysis chat interface.
"""

from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openbench.chat import ChatEngine
from openbench.chat.files import FileContentExtractor, FileStore
from openbench.chat.transport import AGUIActionHandler
from openbench.core.providers import ProviderType, configure_provider
from openbench.intelligence.base import BaseAgent

from lci_ignite.config import LCIConfig
from lci_ignite.data.attachment_handler import ChatAttachmentHandler
from lci_ignite.intelligence.prompts import COORDINATOR_PROMPT
from lci_ignite.intelligence.tools import (
    clear_pipeline_data,
    clear_render_items,
    get_render_items,
    set_attachments,
    set_pipeline_session,
    set_upload_dir,
)
from lci_ignite.server.handler import LCIAGUIHandler


def create_lci_coordinator_agent(config: LCIConfig) -> BaseAgent:
    """Create the LCI coordinator agent with all 20 tools.

    The coordinator handles user interaction and dispatches to
    domain tools for data processing, IO table building, hotspot
    analysis, and report generation.
    """

    agent = BaseAgent(
        goal=(
            "You are an LCA (Life Cycle Assessment) analysis assistant. "
            "Help users analyze their LCI data by building IO tables, "
            "identifying environmental hotspots, and generating reports. "
            "Support Excel LDI (.xlsx), easyLCA CSV, and SimaPro CSV formats."
        ),
        model=config.model,
        temperature=config.temperature,
        max_iterations=25,
        system_prompt=COORDINATOR_PROMPT,
    )

    # Register all tools
    from lci_ignite.intelligence.tools import (
        # Existing tool schemas
        AGGREGATE_BY_CATEGORY_SCHEMA,
        # New tool schemas (Phase 3)
        ANALYZE_EXCEL_STRUCTURE_SCHEMA,
        APPLY_UNIT_CONVERSIONS_SCHEMA,
        BUILD_PROPER_IO_TABLE_SCHEMA,
        CALCULATE_FUNCTIONAL_UNIT_SCHEMA,
        CALCULATE_PARETO_SCHEMA,
        # Conversational tools (Phase 4)
        COMPARE_PRODUCTS_SCHEMA,
        CREATE_HOTSPOT_CALLOUT_SCHEMA,
        CREATE_HOTSPOT_TABLE_SCHEMA,
        CREATE_IO_TABLE_CHART_SCHEMA,
        CREATE_IO_TABLE_SCHEMA,
        CREATE_NARRATIVE_CALLOUT_SCHEMA,
        CREATE_NARRATIVE_MARKDOWN_SCHEMA,
        CREATE_PARETO_CHART_SCHEMA,
        EXPLAIN_ANALYSIS_SCHEMA,
        EXPORT_FILTERED_SCHEMA,
        EXPORT_TO_DOCX_SCHEMA,
        EXPORT_TO_XLSX_SCHEMA,
        # File discovery
        GET_UPLOADED_FILES_SCHEMA,
        PARSE_LDI_SHEET_SCHEMA,
        REVISE_PIPELINE_SCHEMA,
        SELECT_PARETO_ITEMS_SCHEMA,
        VALIDATE_DATA_QUALITY_SCHEMA,
        VALIDATE_UNITS_SCHEMA,
        # Existing tool functions
        aggregate_by_category,
        # New tool functions (Phase 3)
        analyze_excel_structure,
        apply_unit_conversions,
        build_proper_io_table,
        calculate_functional_unit,
        calculate_pareto,
        compare_products,
        create_hotspot_callout,
        create_hotspot_table,
        create_io_table,
        create_io_table_chart,
        create_narrative_callout,
        create_narrative_markdown,
        create_pareto_chart,
        explain_analysis,
        export_filtered,
        export_to_docx,
        export_to_xlsx,
        # File discovery
        get_uploaded_files,
        parse_ldi_sheet,
        revise_pipeline,
        select_pareto_items,
        validate_data_quality,
        validate_units,
    )

    # -- File Discovery Tool --
    agent.tools.register(
        "get_uploaded_files",
        get_uploaded_files,
        schema=GET_UPLOADED_FILES_SCHEMA,
    )

    # -- Data Processing Tools (7 NEW) --
    agent.tools.register(
        "analyze_excel_structure",
        analyze_excel_structure,
        schema=ANALYZE_EXCEL_STRUCTURE_SCHEMA,
    )
    agent.tools.register("parse_ldi_sheet", parse_ldi_sheet, schema=PARSE_LDI_SHEET_SCHEMA)
    agent.tools.register(
        "apply_unit_conversions",
        apply_unit_conversions,
        schema=APPLY_UNIT_CONVERSIONS_SCHEMA,
    )
    agent.tools.register(
        "calculate_functional_unit",
        calculate_functional_unit,
        schema=CALCULATE_FUNCTIONAL_UNIT_SCHEMA,
    )
    agent.tools.register(
        "select_pareto_items",
        select_pareto_items,
        schema=SELECT_PARETO_ITEMS_SCHEMA,
    )
    agent.tools.register(
        "validate_data_quality",
        validate_data_quality,
        schema=VALIDATE_DATA_QUALITY_SCHEMA,
    )
    agent.tools.register(
        "build_proper_io_table",
        build_proper_io_table,
        schema=BUILD_PROPER_IO_TABLE_SCHEMA,
    )

    # -- IO Table Tools (4 existing) --
    agent.tools.register("create_io_table", create_io_table, schema=CREATE_IO_TABLE_SCHEMA)
    agent.tools.register(
        "aggregate_by_category", aggregate_by_category, schema=AGGREGATE_BY_CATEGORY_SCHEMA
    )
    agent.tools.register("validate_units", validate_units, schema=VALIDATE_UNITS_SCHEMA)
    agent.tools.register(
        "create_io_table_chart", create_io_table_chart, schema=CREATE_IO_TABLE_CHART_SCHEMA
    )

    # -- Hotspot Tools (4 existing) --
    agent.tools.register("calculate_pareto", calculate_pareto, schema=CALCULATE_PARETO_SCHEMA)
    agent.tools.register(
        "create_pareto_chart", create_pareto_chart, schema=CREATE_PARETO_CHART_SCHEMA
    )
    agent.tools.register(
        "create_hotspot_table", create_hotspot_table, schema=CREATE_HOTSPOT_TABLE_SCHEMA
    )
    agent.tools.register(
        "create_hotspot_callout", create_hotspot_callout, schema=CREATE_HOTSPOT_CALLOUT_SCHEMA
    )

    # -- Output Tools (3 existing) --
    agent.tools.register(
        "create_narrative_markdown",
        create_narrative_markdown,
        schema=CREATE_NARRATIVE_MARKDOWN_SCHEMA,
    )
    agent.tools.register(
        "create_narrative_callout",
        create_narrative_callout,
        schema=CREATE_NARRATIVE_CALLOUT_SCHEMA,
    )
    agent.tools.register("export_to_docx", export_to_docx, schema=EXPORT_TO_DOCX_SCHEMA)
    agent.tools.register("export_to_xlsx", export_to_xlsx, schema=EXPORT_TO_XLSX_SCHEMA)

    # -- Conversational Tools (4 NEW) --
    agent.tools.register("explain_analysis", explain_analysis, schema=EXPLAIN_ANALYSIS_SCHEMA)
    agent.tools.register("compare_products", compare_products, schema=COMPARE_PRODUCTS_SCHEMA)
    agent.tools.register("revise_pipeline", revise_pipeline, schema=REVISE_PIPELINE_SCHEMA)
    agent.tools.register("export_filtered", export_filtered, schema=EXPORT_FILTERED_SCHEMA)

    return agent


def create_app(config: LCIConfig | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: LCI configuration. If None, loads from environment.

    Returns:
        Configured FastAPI application.
    """
    if config is None:
        config = LCIConfig.from_env()

    # Configure Gemini LLM provider
    configure_provider(
        name="gemini-lci",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": config.google_api_key},
        settings={"model": config.model},
        is_default=True,
    )

    # Create coordinator agent
    agent = create_lci_coordinator_agent(config)

    # Wire: Agent -> ChatEngine -> AG-UI Transport
    engine = ChatEngine(
        agent=agent,
        render_items_fn=get_render_items,
        clear_render_items_fn=clear_render_items,
    )

    agui_handler = LCIAGUIHandler(engine=engine, db_path=config.memory_db)
    action_handler = AGUIActionHandler(engine=engine)

    # File handling
    upload_dir = config.upload_dir
    os.makedirs(upload_dir, exist_ok=True)
    file_store = FileStore(upload_dir=upload_dir)
    extractor = FileContentExtractor()
    attachment_handler = ChatAttachmentHandler()

    # FastAPI app
    app = FastAPI(title="LCI Ignite X")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def startup():
        print("\n  LCI Ignite X")
        print(f"  Model: {config.model}")
        print(f"  Memory DB: {config.memory_db}")
        print(f"  Tools: {len(agent.tools._tools)} registered")
        print("  AG-UI: POST http://localhost:8003/awp")
        print("  Action: POST http://localhost:8003/chat/action")
        print("  Upload: POST http://localhost:8003/chat/upload\n")

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "lci-ignite-x"}

    @app.post("/chat/upload")
    async def upload_file(file: UploadFile = File(...)):
        """Upload a file for LCA analysis (CSV or Excel)."""
        content = await file.read()
        stored = file_store.store(
            file.filename or "unnamed",
            content,
            file.content_type or "application/octet-stream",
        )
        stored.extracted_text = await asyncio.to_thread(extractor.extract, stored)

        attachment = stored.to_attachment(base_url="/uploads")
        result = attachment.to_dict()

        # Detect file format
        try:
            fmt = attachment_handler.detect_format(stored.path)
            result["detectedFormat"] = fmt
        except Exception:
            result["detectedFormat"] = "unknown"

        if stored.extracted_text:
            result["extractedText"] = stored.extracted_text[:2000]
        return result

    @app.post("/awp")
    async def agent_endpoint(request: Request):
        """AG-UI protocol endpoint for LCA analysis."""
        body = await request.json()

        # Resolve uploaded file paths
        forwarded = body.get("forwardedProps") or {}
        attachments_list = forwarded.get("attachments") or body.get("attachments") or []

        # DEBUG: log what the frontend sends
        messages = body.get("messages", [])
        user_msg = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
        )
        print(f"\n  [DEBUG /awp] user_msg: {user_msg[:100]!r}")
        print(f"  [DEBUG /awp] attachments count: {len(attachments_list)}")
        for att in attachments_list:
            has_text = bool(att.get("extractedText"))
            print(
                f"  [DEBUG /awp]   id={att.get('id')}, name={att.get('name')}, "
                f"hasExtractedText={has_text}, keys={list(att.keys())}"
            )

        file_metas = []
        for att in attachments_list:
            file_id = att.get("id")
            if not file_id:
                continue
            stored = file_store.get(file_id)
            if not stored:
                print(f"  [DEBUG /awp]   file_store.get({file_id!r}) = None (NOT FOUND)")
                continue
            file_metas.append(
                {
                    "name": stored.name,
                    "path": stored.path,
                    "mime_type": stored.mime_type,
                }
            )
        set_attachments(file_metas or None)
        set_upload_dir(upload_dir)

        # Restore pipeline data for this session (or clear if new)
        thread_id = body.get("threadId") or body.get("thread_id") or ""
        if thread_id:
            set_pipeline_session(thread_id)
        else:
            clear_pipeline_data()

        return await agui_handler.handle(request)

    @app.post("/chat/action")
    async def chat_action(request: Request):
        """REST endpoint for A2UI actions."""
        return await action_handler.handle(request)

    @app.get("/chat/actions")
    async def list_actions():
        return {"actions": action_handler.get_registered_actions()}

    # Static files
    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

    return app
