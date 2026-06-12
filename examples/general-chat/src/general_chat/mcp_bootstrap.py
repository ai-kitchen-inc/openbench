"""Startup helpers for bundled General Chat MCP server configs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from general_chat.mcp_registry import MCPServerRegistryStore
from openbench.mcp.config import MCPConfig

logger = logging.getLogger(__name__)

BUNDLED_MCP_CONFIGS = (
    "filesystem-mcp.yaml",
    "generic-api-docker.yaml",
    "image-search-docker.yaml",
    "sam-segmentation-docker.yaml",
    "docker-mcp-gateway.yaml",
)


def seed_all_mcp_registry(
    storage_root: str | Path,
    *,
    config_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Import bundled MCP configs into the persistent General Chat registry."""
    root = Path(storage_root).expanduser().resolve()
    resolved_config_dir = Path(config_dir).expanduser().resolve() if config_dir else _default_config_dir()
    store = MCPServerRegistryStore(root)
    seeded: list[str] = []
    missing: list[str] = []
    errors: list[dict[str, str]] = []

    for filename in BUNDLED_MCP_CONFIGS:
        path = resolved_config_dir / filename
        if not path.exists():
            missing.append(filename)
            continue
        try:
            config = MCPConfig.from_file(path)
            store.import_client_config(config.client_config(), source="manual")
        except Exception as exc:
            logger.warning("mcp.bootstrap.seed_failed config=%s error=%s", path, exc)
            errors.append({"config": filename, "error": str(exc)})
            continue
        seeded.extend(sorted(config.client_config().servers))

    return {
        "storageRoot": str(root),
        "configDir": str(resolved_config_dir),
        "seeded": seeded,
        "missing": missing,
        "errors": errors,
    }


def _default_config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "mcp"
