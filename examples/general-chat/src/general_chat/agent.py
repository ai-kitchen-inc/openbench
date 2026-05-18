"""General Chat agent factory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from openbench.core.providers import ProviderType, configure_provider
from openbench.intelligence import BaseAgent, Persona

_DEFAULT_MCP_APPROVED_TOOLS = (
    "openbench.filter_records",
    "openbench.distinct_values",
    "openbench.group_and_aggregate",
    "openbench.top_n_records",
)


def _example_root() -> Path:
    return Path(__file__).resolve().parents[2]


def get_persona_dir() -> Path:
    return (_example_root() / "soul").resolve()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: tuple[str, ...] = ()) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _mcp_config_path() -> Path:
    raw = os.getenv("GENERAL_CHAT_MCP_CONFIG", "mcp/openbench-mcp.yaml")
    path = Path(raw)
    if not path.is_absolute():
        path = _example_root() / path
    return path.resolve()


def _load_mcp_tools_for_chat() -> tuple[list[Any], dict[str, Any]]:
    """Load MCP-backed OpenBench tools for opt-in General Chat testing."""
    from openbench.mcp.adapters import MCPToolAdapter, load_mcp_tools
    from openbench.mcp.client import MCPClient
    from openbench.mcp.config import MCPConfig, MCPServerConfig
    from openbench.mcp.server import OpenBenchMCPServer
    from openbench.mcp.transports import InMemoryMCPTransport

    mode = os.getenv("GENERAL_CHAT_MCP_MODE", "local").strip().lower()
    approved_names = set(
        _csv_env("GENERAL_CHAT_MCP_APPROVED_TOOLS", _DEFAULT_MCP_APPROVED_TOOLS)
    )
    config_path = _mcp_config_path()
    config = MCPConfig.from_file(config_path) if config_path.exists() else MCPConfig()
    loaded: list[MCPToolAdapter] = []

    if mode == "local":
        server_config = config.server if config_path.exists() else MCPServerConfig()
        server = OpenBenchMCPServer(server_config)
        client = MCPClient(transports={server_config.name: InMemoryMCPTransport(server)})
        discovered = client.discover_sync()
        for server_name, discovered_server in discovered.servers.items():
            for tool_name, tool_schema in discovered_server.tools.items():
                namespaced = f"{server_name}.{tool_name}"
                if namespaced not in approved_names:
                    continue
                loaded.append(
                    MCPToolAdapter(
                        client=client,
                        namespaced_name=namespaced,
                        tool_schema=tool_schema,
                        approved=True,
                    )
                )
    else:
        for adapter in load_mcp_tools(config):
            if adapter.namespaced_name in approved_names:
                adapter.approved = True
                loaded.append(adapter)

    return loaded, {
        "enabled": True,
        "mode": mode,
        "config_path": str(config_path),
        "approved_tools": sorted(approved_names),
        "tools": [
            {
                "name": tool.namespaced_name,
                "adapter_name": tool.name,
                "description": tool.tool_schema.get("description", ""),
            }
            for tool in loaded
        ],
    }


def create_agent(
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.3,
) -> BaseAgent:
    """Create the general-purpose chat agent.

    By default this keeps General Chat document-first and tool-free. Set
    ``GENERAL_CHAT_MCP_ENABLED=1`` to load a small allowlisted set of MCP-backed
    query tools for local MCP testing.
    """
    key = api_key or os.getenv("GOOGLE_API_KEY")
    resolved_model = model or os.getenv("GENERAL_CHAT_MODEL", "gemini-3-flash-preview")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY is required. Set it in .env or the environment.")

    configure_provider(
        name="gemini-general-chat",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": key},
        settings={"model": resolved_model},
        is_default=True,
    )

    persona_dir = get_persona_dir()
    persona = Persona.from_dir(persona_dir) if persona_dir.is_dir() else None

    mcp_tools: list[Any] = []
    mcp_summary: dict[str, Any] = {
        "enabled": False,
        "mode": os.getenv("GENERAL_CHAT_MCP_MODE", "local"),
        "tools": [],
        "approved_tools": list(_DEFAULT_MCP_APPROVED_TOOLS),
    }
    mcp_error: str | None = None
    if _env_flag("GENERAL_CHAT_MCP_ENABLED", default=False):
        try:
            mcp_tools, mcp_summary = _load_mcp_tools_for_chat()
        except Exception as exc:
            mcp_error = str(exc)
            mcp_summary = {
                "enabled": True,
                "mode": os.getenv("GENERAL_CHAT_MCP_MODE", "local"),
                "tools": [],
                "error": mcp_error,
                "config_path": str(_mcp_config_path()),
            }

    agent = BaseAgent(
        goal=(
            "Help users by answering questions, analysing uploaded documents "
            "(PDF, Word, PowerPoint), and reasoning over data."
        ),
        model=resolved_model,
        temperature=temperature,
        persona=persona,
        tools=mcp_tools or None,
    )
    agent._mcp_enabled = bool(mcp_summary.get("enabled"))  # type: ignore[attr-defined]
    agent._mcp_summary = mcp_summary  # type: ignore[attr-defined]
    agent._mcp_error = mcp_error  # type: ignore[attr-defined]
    agent._mcp_tools = mcp_tools  # type: ignore[attr-defined]
    return agent
