"""Tool schemas for the Gemini chat agent.

Each schema follows the OpenAI function-calling format used by BaseAgent's
ToolExecutor to describe tool parameters to the LLM.
"""

from typing import Any

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
                            "placeholder": {
                                "type": "string",
                                "description": "Placeholder text for input fields",
                            },
                            "description": {
                                "type": "string",
                                "description": "Help text displayed below the field",
                            },
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Options for select/choice fields",
                            },
                            "min": {
                                "type": "number",
                                "description": "Minimum value for number/slider fields",
                            },
                            "max": {
                                "type": "number",
                                "description": "Maximum value for number/slider fields",
                            },
                            "step": {
                                "type": "number",
                                "description": "Step increment for slider fields",
                            },
                            "pattern": {
                                "type": "string",
                                "description": "Regex pattern for text validation",
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

GENERATE_FILE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "generate_file",
        "description": (
            "Generate a downloadable file from text content. Use this when the user "
            "asks to create, generate, save, or export content as a file. "
            "Supports text, markdown, CSV, JSON, HTML, and other text-based formats."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Output filename with extension (e.g. 'report.md', 'data.csv')",
                },
                "content": {
                    "type": "string",
                    "description": "The full file content to write",
                },
                "mime_type": {
                    "type": "string",
                    "description": "MIME type. Auto-detected from extension if omitted.",
                },
            },
            "required": ["filename", "content"],
        },
    },
}

SHOW_MEDIA_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "show_media",
        "description": (
            "Display inline media for the user: images, videos, or audio players. "
            "Use this when showing visual or audio content from URLs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL of the media (image, video, or audio file)",
                },
                "media_type": {
                    "type": "string",
                    "enum": ["image", "video", "audio"],
                    "description": "Type of media to display",
                },
                "title": {
                    "type": "string",
                    "description": "Title displayed above the media (optional)",
                },
                "caption": {
                    "type": "string",
                    "description": "Alt text for images, description for video/audio (optional)",
                },
            },
            "required": ["url", "media_type"],
        },
    },
}

CREATE_LIST_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_list",
        "description": (
            "MANDATORY: Display a structured list of items as a rich UI component. "
            "You MUST call this tool whenever your answer contains 3 or more items "
            "(rankings, top-N lists, steps, search results, recommendations, comparisons). "
            "NEVER write numbered or bulleted lists in your text — always use this tool. "
            "Each item has text (required) and optional subtitle for details."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "List title displayed above the list",
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "Main item text",
                            },
                            "subtitle": {
                                "type": "string",
                                "description": "Secondary text below the item (optional)",
                            },
                        },
                        "required": ["text"],
                    },
                    "description": (
                        "List items as objects with 'text' (required) and optional 'subtitle'"
                    ),
                },
                "ordered": {
                    "type": "boolean",
                    "description": "If true, display as numbered list (default: false)",
                },
            },
            "required": ["title", "items"],
        },
    },
}

CREATE_TABS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_tabs",
        "description": (
            "Create a tabbed interface to organize content by category. "
            "Use this when presenting categorized or multi-topic information, "
            "comparisons, or different perspectives on a subject. "
            "Each tab has a label and markdown content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title displayed above the tabs",
                },
                "tabs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "Tab header label",
                            },
                            "content": {
                                "type": "string",
                                "description": "Tab body content (markdown)",
                            },
                        },
                        "required": ["label", "content"],
                    },
                    "description": "Tab definitions with label and content",
                },
            },
            "required": ["title", "tabs"],
        },
    },
}

SHOW_MODAL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "show_modal",
        "description": (
            "Display important information in a modal overlay. "
            "Use this when highlighting important details, disclaimers, "
            "summaries, or content that deserves focused attention."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Modal title in header",
                },
                "content": {
                    "type": "string",
                    "description": "Modal body content (markdown)",
                },
            },
            "required": ["title", "content"],
        },
    },
}

CREATE_TABLE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_table",
        "description": (
            "Display structured tabular data with headers and rows. "
            "Use this when presenting comparisons, specifications, "
            "pricing tables, or any data that fits a row/column layout."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Table title displayed above the table",
                },
                "headers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Column header names",
                },
                "rows": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "description": "Table rows as arrays of cell values",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional description displayed below the title",
                },
            },
            "required": ["title", "headers", "rows"],
        },
    },
}

CREATE_CALLOUT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_callout",
        "description": (
            "Display a styled callout box for important notes, warnings, tips, "
            "or success messages. Supports markdown content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Callout body content (supports markdown)",
                },
                "variant": {
                    "type": "string",
                    "enum": ["default", "info", "success", "warning"],
                    "description": "Visual style variant (default: 'default')",
                },
                "title": {
                    "type": "string",
                    "description": "Optional bold title above the content",
                },
            },
            "required": ["content"],
        },
    },
}

CREATE_CODE_BLOCK_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_code_block",
        "description": (
            "Display a syntax-highlighted code block for the user. Use this when "
            "showing code examples, implementations, snippets, or programming solutions. "
            "The code is rendered with syntax highlighting in an ObCodeBlock component."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The source code to display",
                },
                "language": {
                    "type": "string",
                    "description": (
                        "Programming language for syntax highlighting "
                        "(e.g. 'python', 'javascript', 'typescript', 'sql', 'bash')"
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "Optional title displayed above the code block",
                },
            },
            "required": ["code", "language"],
        },
    },
}
