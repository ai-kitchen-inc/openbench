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

Supports multi-turn conversation with memory.

Requires:
    - GOOGLE_API_KEY environment variable
    - pip install google-genai
"""

import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from openbench.core.chainable import Chain
from openbench.core.providers import ProviderType, configure_provider
from openbench.data.sources import GroundedSearchSource, LangExtractSource, PDFSource
from openbench.intelligence.base import BaseAgent
from openbench.workflows import Workflow

# ── Global attachment context (set per-request from server.py) ──

_current_attachments: list[dict] | None = None


def set_attachments(attachments: list[dict] | None) -> None:
    """Set file attachments for the current request.

    Called from server.py before each agent execution so that the
    analyze_file and extract_entities tools can access uploaded files.

    Each dict should have: name (str), path (str), mime_type (str).
    """
    global _current_attachments
    _current_attachments = attachments


# ── Render queue (side-channel for visualization tools) ──
# Same pattern as _current_attachments: module-level list populated by tools,
# read by ChatEngine after agent execution, cleared before each request.

_render_items: list[dict] = []


def get_render_items() -> list[dict]:
    """Return accumulated render items from visualization tools."""
    return list(_render_items)


def clear_render_items() -> None:
    """Clear render items queue. Called before each request."""
    _render_items.clear()


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


# ── Tool schemas ──

SEARCH_WEB_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "Search the web for current, up-to-date information on any topic. "
            "Uses Google Search grounding for real-time results with citations. "
            "Use this for news, recent events, or anything not in the knowledge base."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, e.g. 'latest AI agent trends 2026'",
                },
            },
            "required": ["query"],
        },
    },
}

ANALYZE_FILE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "analyze_file",
        "description": (
            "Read and analyze the full content of uploaded files. "
            "Supports PDF (full text extraction) and text files. "
            "Call without arguments to see all uploaded files, "
            "or specify a filename to read a specific file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of a specific file to read (optional, reads all if omitted)",
                },
            },
            "required": [],
        },
    },
}

CALCULATE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": (
            "Evaluate a mathematical expression. "
            "Supports: +, -, *, /, **, sqrt, log, sin, cos, pi, e."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Math expression, e.g. '2 * 3 + 1' or 'sqrt(144)'",
                },
            },
            "required": ["expression"],
        },
    },
}

KNOWLEDGE_LOOKUP_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "knowledge_lookup",
        "description": (
            "Look up information from the built-in knowledge base. "
            "Topics: renewable_energy (solar, wind, storage), "
            "ai_trends (models, agents, regulation), "
            "market_data (tech_stocks, venture_capital)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "One of: renewable_energy, ai_trends, market_data",
                },
                "subtopic": {
                    "type": "string",
                    "description": "Subtopic within the topic (optional)",
                },
            },
            "required": ["topic"],
        },
    },
}

EXTRACT_ENTITIES_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "extract_entities",
        "description": (
            "Extract structured entities from text using AI-powered extraction (LangExtract). "
            "Provide text directly OR specify a filename to extract from an uploaded file. "
            "Returns structured results grouped by entity class. "
            "Example prompt: 'Extract people, organizations, and dates'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "Description of what to extract, "
                        "e.g. 'Extract people, organizations, and locations'"
                    ),
                },
                "text": {
                    "type": "string",
                    "description": "The text to extract entities from (optional if filename given)",
                },
                "filename": {
                    "type": "string",
                    "description": "Name of an uploaded file to extract entities from (optional if text given)",
                },
            },
            "required": ["prompt"],
        },
    },
}

GET_DATETIME_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_datetime",
        "description": "Get the current date and time.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

CREATE_CHART_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_chart",
        "description": (
            "Create a visual chart for the user. Use this when comparing data with "
            "numbers, showing trends, or visualizing distributions. "
            "Data must be an array of objects in Recharts format: "
            '[{"name": "Solar", "cost": 0.03}, {"name": "Wind", "cost": 0.034}]. '
            "The first key is used as X-axis, remaining keys as data series."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "pie", "scatter", "area"],
                    "description": "Type of chart to create",
                },
                "title": {
                    "type": "string",
                    "description": "Chart title displayed above the chart",
                },
                "data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "Array of data objects in Recharts format. "
                        'Example: [{"name": "Q1", "revenue": 100, "profit": 30}]'
                    ),
                },
                "options": {
                    "type": "object",
                    "description": (
                        "Optional chart configuration: "
                        "xKey (string, X-axis field name), "
                        "series (array of strings, Y-axis field names), "
                        "width (string, default '100%'), "
                        "height (string, default '300px')"
                    ),
                },
            },
            "required": ["chart_type", "title", "data"],
        },
    },
}

CREATE_FORM_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_form",
        "description": (
            "Create an interactive form for the user. Use this when you need to "
            "collect structured input from the user (e.g. feedback, registration, "
            "settings). Each field becomes an input component."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Form title displayed above the form fields",
                },
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Field identifier",
                            },
                            "type": {
                                "type": "string",
                                "enum": [
                                    "text",
                                    "email",
                                    "password",
                                    "number",
                                    "textarea",
                                    "date",
                                    "datetime",
                                    "time",
                                    "checkbox",
                                    "select",
                                    "slider",
                                ],
                                "description": "Input field type",
                            },
                            "label": {"type": "string", "description": "Display label"},
                            "required": {
                                "type": "boolean",
                                "description": "Whether field is required",
                            },
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Options for select/choice fields",
                            },
                        },
                        "required": ["name", "type", "label"],
                    },
                    "description": "List of form fields",
                },
                "submit_label": {
                    "type": "string",
                    "description": "Submit button label (default: 'Submit')",
                },
            },
            "required": ["title", "fields"],
        },
    },
}

SHOW_FILE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "show_file",
        "description": (
            "Display a file card for the user. Use this when referencing "
            "downloadable files, reports, or documents."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "File name (e.g. 'report.pdf')",
                },
                "url": {
                    "type": "string",
                    "description": "URL to download/view the file",
                },
                "mime_type": {
                    "type": "string",
                    "description": "MIME type (e.g. 'application/pdf')",
                },
                "size": {
                    "type": "integer",
                    "description": "File size in bytes (optional)",
                },
            },
            "required": ["name", "url"],
        },
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
    if not _current_attachments:
        return None
    return next((a for a in _current_attachments if a["name"] == filename), None)


def _format_not_found(filename: str) -> str:
    """Format a 'file not found' error with available filenames."""
    available = ", ".join(a["name"] for a in (_current_attachments or []))
    return f"File '{filename}' not found. Available files: {available}"


def extract_entities(prompt: str, text: str = "", filename: str = "") -> str:
    """Extract structured entities using Workflow(Chain([PDFSource, LangExtractSource]))."""
    try:
        # Workflow: PDFSource -> LangExtractSource for uploaded PDF files
        if filename and _current_attachments:
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
    if not _current_attachments:
        return "No files have been uploaded in this message."

    targets = _current_attachments
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
    _render_items[:] = [i for i in _render_items if not (i.get("title") == title and "data" in i)]
    _render_items.append(item)
    return f"Chart created: {chart_type} chart titled '{title}' with {len(data)} data points."


def create_form(title: str, fields: list[dict], submit_label: str = "Submit") -> str:
    """Create an interactive form by pushing field definitions to the render queue.

    Only one form per response — if the agent refines the form across reasoning
    iterations, the previous form is replaced (not accumulated).
    """
    # Replace any existing form item (agent may call this multiple times in reasoning loop)
    _render_items[:] = [item for item in _render_items if "fields" not in item]
    _render_items.append(
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
    _render_items[:] = [
        i for i in _render_items if not (i.get("name") == name and "url" in i and "fields" not in i)
    ]
    _render_items.append(item)
    return f"File card displayed: {name}."


# ── Agent factory ──

_SYSTEM_PROMPT = """\
You are a helpful AI assistant powered by OpenBench with multi-turn memory.

You have access to these tools:
- **search_web**: Search the internet for current information, news, and real-time data.
- **extract_entities**: Extract structured entities (people, orgs, dates, etc.) from text.
- **knowledge_lookup**: Look up curated data on renewable energy, AI trends, and market data.
- **calculate**: Evaluate mathematical expressions.
- **get_datetime**: Get the current date and time.
- **analyze_file**: Read and analyze uploaded file content.
- **create_chart**: Create visual charts (bar, line, pie, scatter, area).
- **create_form**: Create interactive forms to collect user input.
- **show_file**: Display file download cards.

Guidelines:
- When a user uploads files, ALWAYS use the analyze_file tool to read their content \
before answering questions about them.
- Use extract_entities when users want structured extraction from text \
(e.g. "extract people and companies from this article").
- For current events or recent information, use search_web.
- For renewable energy, AI trends, or market data, try knowledge_lookup first.
- When comparing data with numbers, use create_chart for visual charts.
- When asking user for structured input, use create_form.
- When referencing downloadable files, use show_file.
- Always provide text explanation alongside visualizations.
- Respond in clear, well-formatted markdown.
- Be concise but thorough.\
"""


def create_gemini_agent(
    # model: str = "gemini-3-flash-preview",
    model: str = "gemini-2.5-flash",
    temperature: float = 0.7,
) -> BaseAgent:
    """Create a BaseAgent powered by Gemini with tools.

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
        system_prompt=_SYSTEM_PROMPT,
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

    return agent
