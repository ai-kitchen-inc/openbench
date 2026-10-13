"""Startup helpers for bundled General Chat MCP server configs."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from general_chat.mcp_registry import MCPServerRegistryStore
from openbench.mcp.config import MCPConfig

logger = logging.getLogger(__name__)

# The db_server entry is resolved at seed time from
# GENERAL_CHAT_MCP_DB_SERVER_CONFIG so local dev can swap the docker image for
# the fork run directly with python (``db-server-local.yaml``). Both files
# register the same server name, hence the same registry id -- never seed both.
DB_SERVER_CONFIG_PLACEHOLDER = "<db-server>"
DEFAULT_DB_SERVER_CONFIG = "db-server-docker.yaml"
DB_SERVER_CONFIG_ENV = "GENERAL_CHAT_MCP_DB_SERVER_CONFIG"

BUNDLED_MCP_CONFIGS = (
    "filesystem-mcp.yaml",
    "generic-api-docker.yaml",
    "image-search-docker.yaml",
    "sam-segmentation-docker.yaml",
    "docker-mcp-gateway.yaml",
    "aggregate-data-stdio.yaml",
    "dashboard-generator-stdio.yaml",
    DB_SERVER_CONFIG_PLACEHOLDER,
    "custom-function-docker.yaml",
    "google-drive-mcp.yaml",
)

# Configs whose servers need operator-supplied credentials before they can
# run. import_client_config enables new servers unconditionally, so these
# are flipped off right after their FIRST seed; a later admin enable
# survives re-seeding (re-import preserves the existing flag).
DISABLED_BY_DEFAULT_CONFIGS = frozenset({"google-drive-mcp.yaml"})


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

    for filename in bundled_mcp_config_names():
        path = resolved_config_dir / filename
        if not path.exists():
            missing.append(filename)
            continue
        try:
            config = MCPConfig.from_file(path)
            preexisting_ids: set[str] = set()
            if filename in DISABLED_BY_DEFAULT_CONFIGS:
                preexisting_ids = {
                    item["id"] for item in store.list_payload()["servers"]
                }
            store.import_client_config(config.client_config(), source="manual")
            if filename in DISABLED_BY_DEFAULT_CONFIGS:
                for item in store.list_payload()["servers"]:
                    if (
                        item["id"] not in preexisting_ids
                        and item["name"] in config.client_config().servers
                    ):
                        store.set_server_enabled(item["id"], False)
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


def bundled_mcp_config_names() -> tuple[str, ...]:
    """Bundled config filenames with the db_server entry resolved from the env."""
    db_server = os.getenv(DB_SERVER_CONFIG_ENV, "").strip() or DEFAULT_DB_SERVER_CONFIG
    return tuple(
        db_server if name == DB_SERVER_CONFIG_PLACEHOLDER else name for name in BUNDLED_MCP_CONFIGS
    )


def _default_config_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "mcp"
