"""OpenBench/OpenAI-style schemas for the example MCP tools."""

EXAMPLE_ECHO_SCHEMA = {
    "name": "example_echo",
    "description": "Echo text with optional uppercase formatting.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Non-empty text to echo.",
            },
            "uppercase": {
                "type": "boolean",
                "description": "Whether to uppercase the returned text.",
            },
        },
        "required": ["text"],
    },
}
