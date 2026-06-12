"""OpenAI/OpenBench-style function schema for SAM 3 counting tools."""

COUNT_OBJECTS_WITH_SAM3_SCHEMA = {
    "name": "count_objects_with_sam3",
    "description": (
        "Use SAM 3 concept segmentation to count all image instances matching "
        "a user-provided text concept. The concept should be a short noun phrase "
        "such as dog, person, red apple, yellow school bus, or person wearing a hat. "
        "This server is SAM 3 only and does not expose model selection."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "concept": {
                "type": "string",
                "description": "Required text concept or short noun phrase to count.",
            },
            "image_path": {
                "type": "string",
                "description": "Local png/jpg/jpeg/webp image path inside an allowed mounted input root.",
            },
            "image_base64": {
                "type": "string",
                "description": "Base64 image bytes or a data URL. Raw image data is not logged.",
            },
            "mime_type": {
                "type": "string",
                "description": "Optional MIME type for base64 inputs.",
                "enum": ["image/png", "image/jpeg", "image/webp"],
            },
            "conf": {
                "type": "number",
                "description": "Optional SAM 3 confidence threshold. Defaults to SAM3_CONF.",
                "minimum": 0,
                "maximum": 1,
                "default": 0.25,
            },
            "min_area_pixels": {
                "type": "integer",
                "description": "Ignore SAM 3 masks smaller than this pixel area.",
                "minimum": 0,
                "default": 0,
            },
            "return_segments": {
                "type": "boolean",
                "description": "Return per-mask metadata for each kept SAM 3 segment.",
                "default": True,
            },
            "return_overlay": {
                "type": "boolean",
                "description": "Return a base64 PNG overlay visualization.",
                "default": False,
            },
        },
        "required": ["concept"],
    },
}

SERVICE_INFO_SCHEMA = {
    "name": "service_info",
    "description": "Report SAM 3 concept counting MCP service configuration and weight status.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}
