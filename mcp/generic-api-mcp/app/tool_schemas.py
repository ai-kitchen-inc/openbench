"""OpenAI/OpenBench-style function schema for generic API tools."""

FETCH_GENERIC_API_DATA_SCHEMA = {
    "name": "fetch_generic_api_data",
    "description": (
        "Fetch data from a user-provided external API endpoint. Optional Basic "
        "Auth defaults are read from environment variables when present."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "endpoint_url": {
                "type": "string",
                "description": "Required http:// or https:// API endpoint URL to fetch.",
            },
            "query_params": {
                "type": "object",
                "description": "Optional query string parameters to send with the GET request.",
                "additionalProperties": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "integer"},
                        {"type": "number"},
                        {"type": "boolean"},
                        {"type": "null"},
                    ]
                },
            }
        },
        "required": ["endpoint_url"],
    },
}
