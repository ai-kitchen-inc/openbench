"""
OpenBench custom A2UI catalog definition.

Extends the 18 standard A2UI v0.10 components with 6 OpenBench-specific components:
- ObChart: Recharts-based chart rendering (bar, line, pie, scatter, area)
- ObFileCard: File preview card with download
- ObCodeBlock: Syntax-highlighted code (Shiki)
- ObMarkdown: Rich markdown rendering (react-markdown)
- ObTable: Structured tabular data display
- ObCallout: Styled callout box with variant colors

Note: AudioPlayer and Video are standard A2UI components -- no custom wrappers needed.
"""

OPENBENCH_CATALOG_ID = "https://openbench.dev/catalog/v1"

# 18 standard A2UI v0.10 components (for reference, defined in the A2UI spec)
STANDARD_COMPONENTS = (
    "Text",
    "Image",
    "Icon",
    "Video",
    "AudioPlayer",
    "Row",
    "Column",
    "List",
    "Card",
    "Tabs",
    "Modal",
    "Divider",
    "Button",
    "TextField",
    "CheckBox",
    "ChoicePicker",
    "Slider",
    "DateTimeInput",
)

# 14 standard A2UI functions (for reference, defined in the A2UI spec)
STANDARD_FUNCTIONS = (
    # Validation
    "required",
    "regex",
    "length",
    "numeric",
    "email",
    # Formatting
    "formatString",
    "formatNumber",
    "formatCurrency",
    "formatDate",
    "pluralize",
    # Navigation
    "openUrl",
    # Logic
    "and",
    "or",
    "not",
)

# OpenBench custom catalog: 6 additional components
OPENBENCH_CATALOG: dict = {
    "catalogId": OPENBENCH_CATALOG_ID,
    "components": {
        "ObChart": {
            "description": "Recharts-based chart rendering",
            "properties": {
                "chartType": {
                    "type": "string",
                    "enum": ["bar", "line", "pie", "scatter", "area"],
                },
                "data": {"type": "object"},
                "options": {"type": "object"},
                "width": {"type": "string"},
                "height": {"type": "string"},
            },
        },
        "ObFileCard": {
            "description": "File preview card with download link",
            "properties": {
                "fileName": {"type": "string"},
                "fileUrl": {"type": "string"},
                "fileSize": {"type": "number"},
                "mimeType": {"type": "string"},
                "previewUrl": {"type": "string"},
            },
        },
        "ObCodeBlock": {
            "description": "Syntax-highlighted code block (Shiki)",
            "properties": {
                "code": {"type": "string"},
                "language": {"type": "string"},
                "showLineNumbers": {"type": "boolean"},
                "maxHeight": {"type": "string"},
            },
        },
        "ObMarkdown": {
            "description": "Rich markdown rendering (react-markdown)",
            "properties": {
                "content": {"type": "string"},
                "allowHtml": {"type": "boolean"},
            },
        },
        "ObTable": {
            "description": "Structured tabular data display",
            "properties": {
                "headers": {"type": "array"},
                "rows": {"type": "array"},
                "striped": {"type": "boolean"},
                "compact": {"type": "boolean"},
            },
        },
        "ObCallout": {
            "description": "Styled callout box with variant colors",
            "properties": {
                "content": {"type": "string"},
                "variant": {
                    "type": "string",
                    "enum": ["default", "info", "success", "warning"],
                },
                "title": {"type": "string"},
            },
        },
    },
    "functions": "inherit_from_standard",
}

# All known component types (standard + custom)
ALL_COMPONENT_TYPES = tuple(STANDARD_COMPONENTS) + tuple(OPENBENCH_CATALOG["components"].keys())


def is_standard_component(component_type: str) -> bool:
    """Check if a component type is from the standard A2UI catalog."""
    return component_type in STANDARD_COMPONENTS


def is_custom_component(component_type: str) -> bool:
    """Check if a component type is from the OpenBench custom catalog."""
    return component_type in OPENBENCH_CATALOG["components"]


def is_known_component(component_type: str) -> bool:
    """Check if a component type is known (standard or custom)."""
    return component_type in ALL_COMPONENT_TYPES
