"""
Gemini-powered agent for the chat demo.

Uses BaseAgent with GeminiLLMProvider + tools:
  - search_web: Web search via Gemini grounding (GroundedSearchSource)
  - extract_entities: Structured entity extraction (LangExtractSource)
  - analyze_file: Read and analyze uploaded file content
  - knowledge_lookup: In-memory knowledge base (renewable energy, AI, market data)
  - calculate: Math expression evaluator
  - get_datetime: Current date/time
  - create_chart: Generate bar/line/pie/scatter/area charts (A2UI ObChart)
  - create_form: Generate interactive forms (A2UI TextField/CheckBox/etc.)
  - show_file: Display file cards (A2UI ObFileCard)
  - generate_file: Generate downloadable files (text, markdown, CSV, JSON, HTML)
  - show_media: Display inline images, videos, or audio players (A2UI Image/Video/AudioPlayer)
  - create_list: Display structured lists of items (A2UI List)
  - create_tabs: Create tabbed interfaces for categorized content (A2UI Tabs)
  - show_modal: Display important info in modal overlays (A2UI Modal)
  - create_table: Display structured tabular data (A2UI ObTable)
  - create_callout: Display styled callout boxes (A2UI ObCallout)

Phase 2 Agentic AI features (optional, enabled via factory params):
  - Task Planning: LLM decomposes complex queries into steps
  - Parallel Tool Execution: Concurrent tool calls
  - Persistent Memory: Cross-session recall via memory_store

Supports multi-turn conversation with memory.

Requires:
    - GOOGLE_API_KEY environment variable
    - pip install google-genai
"""

import contextvars
import math
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from prompt import SYSTEM_PROMPT
from schemas import (
    ANALYZE_FILE_SCHEMA,
    CALCULATE_SCHEMA,
    CREATE_CALLOUT_SCHEMA,
    CREATE_CHART_SCHEMA,
    CREATE_CODE_BLOCK_SCHEMA,
    CREATE_FORM_SCHEMA,
    CREATE_LIST_SCHEMA,
    CREATE_TABLE_SCHEMA,
    CREATE_TABS_SCHEMA,
    EXTRACT_ENTITIES_SCHEMA,
    GENERATE_FILE_SCHEMA,
    GET_DATETIME_SCHEMA,
    KNOWLEDGE_LOOKUP_SCHEMA,
    SEARCH_WEB_SCHEMA,
    SHOW_FILE_SCHEMA,
    SHOW_MEDIA_SCHEMA,
    SHOW_MODAL_SCHEMA,
)

from openbench.core.chainable import Chain
from openbench.core.providers import ProviderType, configure_provider
from openbench.data.sources import GroundedSearchSource, LangExtractSource, PDFSource
from openbench.intelligence.base import BaseAgent
from openbench.workflows import Workflow

# ── Per-request context (ContextVar for async isolation) ──
# asyncio.to_thread() automatically copies context to spawned threads,
# so tool functions running in the agent thread see the correct per-request values.

_current_attachments_var: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "current_attachments", default=None
)
_render_items_var: contextvars.ContextVar[list[dict]] = contextvars.ContextVar("render_items")


def _get_render_list() -> list[dict]:
    """Get per-request render items list, creating if needed."""
    try:
        return _render_items_var.get()
    except LookupError:
        items: list[dict] = []
        _render_items_var.set(items)
        return items


def set_attachments(attachments: list[dict] | None) -> None:
    """Set file attachments for the current request.

    Called from server.py before each agent execution so that the
    analyze_file and extract_entities tools can access uploaded files.

    Each dict should have: name (str), path (str), mime_type (str).
    """
    _current_attachments_var.set(attachments)


def get_render_items() -> list[dict]:
    """Return accumulated render items from visualization tools."""
    return list(_get_render_list())


def clear_render_items() -> None:
    """Clear render items queue. Called before each request."""
    _render_items_var.set([])


# ── Knowledge base ──

KNOWLEDGE_BASE: dict[str, dict[str, str]] = {
    "renewable_energy": {
        "solar": (
            "Global solar capacity reached 1.6 TW in 2025. Average cost dropped to "
            "$0.03/kWh. China leads with 600 GW installed. Perovskite solar cells "
            "achieved 33% efficiency in lab settings."
        ),
        "wind": (
            "Offshore wind capacity grew 35% YoY in 2025. Largest turbine is 18 MW. "
            "Europe leads offshore with 45 GW total. Floating wind farms emerging "
            "in deep water locations."
        ),
        "storage": (
            "Battery storage costs fell to $100/kWh in 2025. Sodium-ion batteries "
            "entering market at 30% lower cost than lithium. Grid-scale storage "
            "deployments doubled to 120 GWh globally."
        ),
    },
    "ai_trends": {
        "models": (
            "Frontier models surpassed 10T parameters in 2025. Mixture-of-experts "
            "architectures dominate. Open-source models closing gap with proprietary. "
            "Multi-modal capabilities now standard."
        ),
        "agents": (
            "AI agent frameworks grew 400% in adoption during 2025. Key players: "
            "LangChain, CrewAI, Google ADK, AutoGen. Tool use and reasoning loops "
            "became production-ready. Orchestration platforms emerging."
        ),
        "regulation": (
            "EU AI Act enforcement began in 2025. US executive order on AI safety "
            "expanded. China released AI governance framework. Industry self-regulation "
            "through voluntary commitments."
        ),
    },
    "market_data": {
        "tech_stocks": (
            "NASDAQ up 18% YTD in 2025. AI-related stocks outperformed by 2x. "
            "Semiconductor companies saw record revenue. Cloud providers grew 25% "
            "on AI infrastructure demand."
        ),
        "venture_capital": (
            "Global VC funding reached $350B in 2025. AI startups captured 40% "
            "of total funding. Average Series A rose to $15M. Key sectors: "
            "AI agents, climate tech, biotech."
        ),
    },
}


# ── Tool functions ──


def search_web(query: str) -> str:
    """Search the web using Gemini grounding via GroundedSearchSource."""
    try:
        source = GroundedSearchSource(query=query, provider="gemini")
        result = source.extract()

        # Return the answer content with source citations
        parts = [result.content]
        sources = result.metadata.get("sources", [])
        if sources:
            parts.append("\n**Sources:**")
            for i, src in enumerate(sources, 1):
                title = src.get("title", f"Source {i}")
                url = src.get("url", "")
                if url:
                    parts.append(f"[{i}] {title}: {url}")
        return "\n".join(parts)
    except Exception as e:
        return f"Web search failed: {e}"


def _resolve_attachment(filename: str) -> dict | None:
    """Find an attachment by filename. Returns None if not found."""
    attachments = _current_attachments_var.get()
    if not attachments:
        return None
    return next((a for a in attachments if a["name"] == filename), None)


def _format_not_found(filename: str) -> str:
    """Format a 'file not found' error with available filenames."""
    available = ", ".join(a["name"] for a in (_current_attachments_var.get() or []))
    return f"File '{filename}' not found. Available files: {available}"


def extract_entities(prompt: str, text: str = "", filename: str = "") -> str:
    """Extract structured entities using Workflow(Chain([PDFSource, LangExtractSource]))."""
    try:
        # Workflow: PDFSource -> LangExtractSource for uploaded PDF files
        if filename and _current_attachments_var.get():
            att = _resolve_attachment(filename)
            if not att:
                return _format_not_found(filename)

            extractor = LangExtractSource(prompt=prompt, provider="gemini")

            if att["mime_type"] == "application/pdf":
                wf = Workflow(
                    name="extract-entities",
                    chain=Chain(steps=[PDFSource(path=att["path"]), extractor]),
                    checkpoints=False,
                )
                result = wf.run()
            else:
                # Text files: read content, then run extractor directly
                extractor.text = Path(att["path"]).read_text(encoding="utf-8")
                result = extractor.extract()

            return _format_entities(result)

        if not text:
            return "No text provided. Provide text or a filename of an uploaded file."

        result = LangExtractSource(text=text, prompt=prompt, provider="gemini").extract()
        return _format_entities(result)
    except Exception as e:
        return f"Entity extraction failed: {e}"


def _format_entities(result: Any) -> str:
    """Format LangExtractSource result as readable markdown."""
    summary = result.content["summary"]
    parts = [f"**Extracted {summary['total']} entities:**\n"]
    for cls, items in result.content["by_class"].items():
        parts.append(f"### {cls} ({len(items)})")
        for item in items:
            attrs = item.get("attributes", {})
            attr_str = f" -- {attrs}" if attrs else ""
            parts.append(f"- {item['text']}{attr_str}")
        parts.append("")
    return "\n".join(parts)


def analyze_file(filename: str = "") -> str:
    """Read full content of uploaded files from disk using PDFSource."""
    attachments = _current_attachments_var.get()
    if not attachments:
        return "No files have been uploaded in this message."

    targets = attachments
    if filename:
        att = _resolve_attachment(filename)
        if not att:
            return _format_not_found(filename)
        targets = [att]

    parts = []
    for a in targets:
        file_path = a["path"]
        mime = a.get("mime_type", "")
        name = a["name"]

        if mime == "application/pdf":
            raw = PDFSource(path=file_path).extract()
            pages = raw.metadata.get("total_pages", "?")
            parts.append(f"**{name}** ({pages} pages)\n\n{raw.content}")
        elif mime.startswith("text/"):
            content = Path(file_path).read_text(encoding="utf-8")
            parts.append(f"**{name}**\n\n{content}")
        else:
            parts.append(f"[{name}] ({mime}) -- binary file, text extraction not supported")

    return "\n\n---\n\n".join(parts)


# NOTE: calculate() uses a sandboxed eval with __builtins__ disabled and only
# math functions allowed. Same pattern as gemini_agent_demo.py. Safe for demo use.
_MATH_NAMESPACE: dict[str, Any] = {
    "__builtins__": {},
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "pi": math.pi,
    "e": math.e,
    "abs": abs,
    "round": round,
    "pow": pow,
}


def calculate(expression: str) -> str:
    """Evaluate a math expression using sandboxed math functions."""
    try:
        result = eval(expression, _MATH_NAMESPACE)
        return str(result)
    except Exception as e:
        return f"Error: {e}"


def knowledge_lookup(topic: str, subtopic: str = "") -> str:
    """Look up information from the knowledge base."""
    topic_data = KNOWLEDGE_BASE.get(topic)
    if not topic_data:
        available = ", ".join(KNOWLEDGE_BASE.keys())
        return f"Topic '{topic}' not found. Available: {available}"
    if subtopic:
        info = topic_data.get(subtopic)
        if not info:
            available = ", ".join(topic_data.keys())
            return f"Subtopic '{subtopic}' not found. Available: {available}"
        return info
    return "\n\n".join(f"[{sub}] {info}" for sub, info in topic_data.items())


def get_datetime() -> str:
    """Get current date and time."""
    now = datetime.now()
    return now.strftime("%A, %B %d, %Y at %H:%M:%S")


# ── Visualization tool functions ──


def create_chart(chart_type: str, title: str, data: list[dict], options: dict | None = None) -> str:
    """Create a visual chart by pushing structured data to the render queue.

    If a chart with the same title already exists (agent refinement), it is replaced.
    Multiple charts with different titles are kept (valid multi-chart scenario).
    """
    item: dict[str, Any] = {
        "type": chart_type,
        "title": title,
        "data": data,
    }
    if options:
        if "xKey" in options:
            item["options"] = item.get("options", {})
            item["options"]["xKey"] = options["xKey"]
        if "series" in options:
            item["options"] = item.get("options", {})
            item["options"]["series"] = options["series"]
        if "width" in options:
            item["width"] = options["width"]
        if "height" in options:
            item["height"] = options["height"]
    # Replace chart with same title (refinement), keep different titles
    items = _get_render_list()
    items[:] = [i for i in items if not (i.get("title") == title and "data" in i)]
    items.append(item)
    return f"Chart created: {chart_type} chart titled '{title}' with {len(data)} data points."


def create_form(title: str, fields: list[dict], submit_label: str = "Submit") -> str:
    """Create an interactive form by pushing field definitions to the render queue.

    Only one form per response — if the agent refines the form across reasoning
    iterations, the previous form is replaced (not accumulated).
    """
    # Replace any existing form item (agent may call this multiple times in reasoning loop)
    items = _get_render_list()
    items[:] = [item for item in items if "fields" not in item]
    items.append(
        {
            "fields": fields,
            "submitLabel": submit_label,
            "title": title,
        }
    )
    field_names = ", ".join(f["name"] for f in fields)
    return f"Form created: '{title}' with fields: {field_names}."


def show_file(name: str, url: str, mime_type: str = "", size: int = 0) -> str:
    """Display a file card by pushing file metadata to the render queue.

    If a file card with the same name already exists, it is replaced.
    """
    item: dict[str, Any] = {"name": name, "url": url}
    if mime_type:
        item["mimeType"] = mime_type
    if size:
        item["size"] = size
    # Replace file card with same name (don't show same file twice)
    items = _get_render_list()
    items[:] = [
        i for i in items if not (i.get("name") == name and "url" in i and "fields" not in i)
    ]
    items.append(item)
    return f"File card displayed: {name}."


# Extension-to-MIME mapping for generate_file
_MIME_TYPES: dict[str, str] = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".html": "text/html",
    ".xml": "application/xml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".css": "text/css",
    ".sql": "text/x-sql",
    ".sh": "text/x-shellscript",
    ".log": "text/plain",
}


def generate_file(filename: str, content: str, mime_type: str = "") -> str:
    """Generate a downloadable file by writing content to disk.

    Saves to ./uploads/<file-id>/<filename> (same directory served by StaticFiles),
    then pushes a file card to the render queue for display.
    """
    # Auto-detect MIME type from extension
    if not mime_type:
        ext = Path(filename).suffix.lower()
        mime_type = _MIME_TYPES.get(ext, "application/octet-stream")

    # Create unique directory under ./uploads/
    file_id = f"file-{uuid.uuid4().hex[:8]}"
    upload_dir = Path("./uploads") / file_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Write content to file
    file_path = upload_dir / filename
    file_path.write_text(content, encoding="utf-8")
    size = file_path.stat().st_size

    # Build download URL (matches StaticFiles mount in server.py)
    url = f"/uploads/{file_id}/{filename}"

    # Push file card to render queue (same pattern as show_file)
    item: dict[str, Any] = {
        "name": filename,
        "url": url,
        "mimeType": mime_type,
        "size": size,
    }
    items = _get_render_list()
    items[:] = [
        i for i in items if not (i.get("name") == filename and "url" in i and "fields" not in i)
    ]
    items.append(item)

    return f"File generated: {filename} ({size} bytes)"


def show_media(url: str, media_type: str, title: str = "", caption: str = "") -> str:
    """Display inline media (image, video, or audio) by pushing to the render queue.

    If media with the same URL already exists, it is replaced.
    """
    item: dict[str, Any] = {"src": url, "mediaType": media_type}
    if title:
        item["title"] = title
    if caption:
        item["caption"] = caption
    # Replace same URL
    items = _get_render_list()
    items[:] = [i for i in items if not (i.get("src") == url and "mediaType" in i)]
    items.append(item)
    return f"Media displayed: {media_type} from {url}"


def create_list(title: str, items: list, ordered: bool = False) -> str:
    """Display a structured list by pushing to the render queue.

    Only one list per response — if the agent refines the list, previous is replaced.
    """
    item: dict[str, Any] = {
        "listType": "ordered" if ordered else "unordered",
        "title": title,
        "items": items,
    }
    # Replace any existing list item
    items_list = _get_render_list()
    items_list[:] = [i for i in items_list if not ("items" in i and "listType" in i)]
    items_list.append(item)
    return f"List created: '{title}' with {len(items)} items."


def create_tabs(title: str, tabs: list[dict]) -> str:
    """Create a tabbed interface by pushing tab data to the render queue.

    Only one tabs component per response -- last one wins.
    """
    item: dict[str, Any] = {"tabs": tabs}
    if title:
        item["title"] = title
    # Replace any existing tabs item
    items = _get_render_list()
    items[:] = [i for i in items if not ("tabs" in i and isinstance(i.get("tabs"), list))]
    items.append(item)
    labels = ", ".join(t.get("label", "?") for t in tabs)
    return f"Tabs created: '{title}' with tabs: {labels}."


def show_modal(title: str, content: str) -> str:
    """Display content in a modal overlay.

    Only one modal per response -- last one wins.
    """
    item: dict[str, Any] = {"modalContent": content, "modalTitle": title}
    # Replace any existing modal item
    items = _get_render_list()
    items[:] = [i for i in items if "modalContent" not in i]
    items.append(item)
    return f"Modal displayed: '{title}'."


def create_table(title: str, headers: list[str], rows: list[list[str]], caption: str = "") -> str:
    """Display structured tabular data by pushing to the render queue.

    If a table with the same title already exists (agent refinement), it is replaced.
    Multiple tables with different titles are kept.
    """
    item: dict[str, Any] = {"headers": headers, "rows": rows, "title": title}
    if caption:
        item["caption"] = caption
    # Replace table with same title (like charts)
    items = _get_render_list()
    items[:] = [
        i for i in items if not (i.get("title") == title and "headers" in i and "rows" in i)
    ]
    items.append(item)
    return f"Table created: '{title}' with {len(headers)} columns and {len(rows)} rows."


def create_callout(content: str, variant: str = "default", title: str = "") -> str:
    """Display a styled callout box by pushing to the render queue.

    Only one callout per response — last one wins.
    """
    item: dict[str, Any] = {"calloutContent": content, "variant": variant}
    if title:
        item["title"] = title
    # Replace any existing callout item
    items = _get_render_list()
    items[:] = [i for i in items if "calloutContent" not in i]
    items.append(item)
    return f"Callout displayed: '{title or variant}' variant."


def create_code_block(code: str, language: str = "python", title: str = "") -> str:
    """Display a syntax-highlighted code block by pushing to the render queue.

    If a code block with the same title already exists (agent refinement), it is replaced.
    Multiple untitled code blocks are kept (valid multi-block scenario).
    """
    item: dict[str, Any] = {"code": code, "language": language}
    if title:
        item["title"] = title
        # Replace code block with same title (don't show same block twice)
        items = _get_render_list()
        items[:] = [
            i for i in items if not (i.get("title") == title and "code" in i and "language" in i)
        ]
        items.append(item)
    else:
        items = _get_render_list()
        items.append(item)
    return f"Code block created: {language}, {len(code.splitlines())} lines."


# ── Agent factory ──


def create_gemini_agent(
    model: str = "gemini-2.5-flash",
    temperature: float = 0.7,
    enable_planning: bool = False,
    parallel_tool_execution: bool = False,
    memory_store: Any = None,
    session_id: str | None = None,
) -> BaseAgent:
    """Create a BaseAgent powered by Gemini with tools.

    Args:
        model: Gemini model name.
        temperature: Model temperature.
        enable_planning: Enable task decomposition before execution.
        parallel_tool_execution: Enable concurrent tool calls.
        memory_store: Optional MemoryStore for persistent memory.
        session_id: Session ID for persistent memory (required with memory_store).

    Requires GOOGLE_API_KEY environment variable.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is required")

    configure_provider(
        name="gemini-chat-demo",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": api_key},
        settings={"model": model},
        is_default=True,
    )

    agent = BaseAgent(
        goal=(
            "You are a helpful AI assistant. Answer questions, search the web, "
            "analyze uploaded files, perform calculations, and look up information. "
            "Be concise and informative. Use markdown formatting."
        ),
        model=model,
        temperature=temperature,
        max_iterations=8,
        system_prompt=SYSTEM_PROMPT,
        enable_planning=enable_planning,
        parallel_tool_execution=parallel_tool_execution,
        memory_store=memory_store,
        session_id=session_id,
    )

    agent.tools.register("search_web", search_web, schema=SEARCH_WEB_SCHEMA)
    agent.tools.register("extract_entities", extract_entities, schema=EXTRACT_ENTITIES_SCHEMA)
    agent.tools.register("analyze_file", analyze_file, schema=ANALYZE_FILE_SCHEMA)
    agent.tools.register("knowledge_lookup", knowledge_lookup, schema=KNOWLEDGE_LOOKUP_SCHEMA)
    agent.tools.register("calculate", calculate, schema=CALCULATE_SCHEMA)
    agent.tools.register("get_datetime", get_datetime, schema=GET_DATETIME_SCHEMA)
    agent.tools.register("create_chart", create_chart, schema=CREATE_CHART_SCHEMA)
    agent.tools.register("create_form", create_form, schema=CREATE_FORM_SCHEMA)
    agent.tools.register("show_file", show_file, schema=SHOW_FILE_SCHEMA)
    agent.tools.register("generate_file", generate_file, schema=GENERATE_FILE_SCHEMA)
    agent.tools.register("create_code_block", create_code_block, schema=CREATE_CODE_BLOCK_SCHEMA)
    agent.tools.register("show_media", show_media, schema=SHOW_MEDIA_SCHEMA)
    agent.tools.register("create_list", create_list, schema=CREATE_LIST_SCHEMA)
    agent.tools.register("create_tabs", create_tabs, schema=CREATE_TABS_SCHEMA)
    agent.tools.register("show_modal", show_modal, schema=SHOW_MODAL_SCHEMA)
    agent.tools.register("create_table", create_table, schema=CREATE_TABLE_SCHEMA)
    agent.tools.register("create_callout", create_callout, schema=CREATE_CALLOUT_SCHEMA)

    return agent
