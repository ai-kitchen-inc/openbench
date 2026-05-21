"""OpenAI/OpenBench-style function schemas for image search tools."""

SEARCH_SIMILAR_IMAGES_SCHEMA = {
    "name": "search_similar_images",
    "description": (
        "Search the persisted CIFAR-10 image index for images visually similar to one query "
        "image. Provide exactly one of image_path, image_base64, image_url, or "
        "cifar10_test_index. The tool embeds only the query image and uses ANN search."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "Local jpg/png/webp image path."},
            "image_base64": {"type": "string", "description": "Base64 image bytes or data URL."},
            "image_url": {"type": "string", "description": "HTTP(S) image URL to fetch locally."},
            "cifar10_test_index": {
                "type": "integer",
                "description": "CIFAR-10 test split index to use as the query image.",
                "minimum": 0,
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum number of neighbors to return. Values above the service cap are capped.",
                "minimum": 1,
                "maximum": 50,
                "default": 10,
            },
            "threshold": {
                "type": "number",
                "description": "Optional minimum cosine similarity score.",
                "minimum": -1,
                "maximum": 1,
            },
        },
        "required": [],
    },
}

INDEX_IMAGES_SCHEMA = {
    "name": "index_images",
    "description": "Index missing CIFAR-10 images into the persistent vector index.",
    "parameters": {
        "type": "object",
        "properties": {
            "batch_size": {
                "type": "integer",
                "description": "Embedding batch size.",
                "minimum": 1,
            },
            "max_items": {
                "type": "integer",
                "description": "Optional cap for demos/tests; omit to index the full CIFAR-10 corpus.",
                "minimum": 1,
            },
            "write_previews": {
                "type": "boolean",
                "description": "Whether to write PNG preview files.",
                "default": True,
            },
        },
        "required": [],
    },
}

REBUILD_INDEX_SCHEMA = {
    "name": "rebuild_index",
    "description": "Clear and rebuild the CIFAR-10 vector index.",
    "parameters": INDEX_IMAGES_SCHEMA["parameters"],
}

LIST_INDEX_STATS_SCHEMA = {
    "name": "list_index_stats",
    "description": "Report image search index health, backend, paths, model, and vector counts.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

REMOVE_IMAGE_SCHEMA = {
    "name": "remove_image",
    "description": "Remove one indexed image by image_id and persist a rebuilt index.",
    "parameters": {
        "type": "object",
        "properties": {
            "image_id": {
                "type": "string",
                "description": "Indexed image id such as cifar10-train-00042.",
            }
        },
        "required": ["image_id"],
    },
}
