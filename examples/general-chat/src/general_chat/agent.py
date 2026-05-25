"""General Chat agent factory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from openbench.chat import render_queue as shared_render_queue
from openbench.core.abstractions import Tool
from openbench.core.providers import ProviderType, configure_provider
from openbench.intelligence import BaseAgent, Persona

_DEFAULT_MCP_APPROVED_TOOLS = (
    "openbench.filter_records",
    "openbench.distinct_values",
    "openbench.group_and_aggregate",
    "openbench.top_n_records",
)
_IMAGE_SEARCH_SIMILAR_TOOL = "image_search.search_similar_images"


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


def _mcp_registry_root() -> Path | None:
    raw = os.getenv("GENERAL_CHAT_MCP_REGISTRY_ROOT")
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _format_score(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value or "")


def _image_search_render_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("error"):
        return []
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return []

    table_rows: list[list[str]] = []
    media_items: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        preview_url = item.get("preview_url") or item.get("image_url")
        if not isinstance(preview_url, str) or not preview_url:
            continue
        rank = str(item.get("rank") or "")
        image_id = str(item.get("image_id") or "")
        label = str(item.get("class_name") or item.get("label") or "")
        score = _format_score(item.get("similarity_score", item.get("score")))
        table_rows.append([rank, label, score, image_id])
        media_items.append(
            {
                "mediaType": "image",
                "src": preview_url,
                "alt": f"CIFAR-10 result {rank}: {label}".strip(),
                "title": f"#{rank} {label} - score {score}".strip(),
            }
        )

    if not media_items:
        return []
    return [
        {
            "title": "CIFAR-10 similar image results",
            "caption": "Visual similarity results returned by image_search.search_similar_images.",
            "headers": ["Rank", "Label", "Score", "Image ID"],
            "rows": table_rows,
            "compact": True,
        },
        *media_items,
    ]


class _ImageSearchRenderTool(Tool):
    """Tool wrapper that renders image-search MCP results into the chat surface."""

    def __init__(self, inner: Tool):
        self.inner = inner

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def description(self) -> str:
        return self.inner.description

    @property
    def namespaced_name(self) -> str:
        return str(getattr(self.inner, "namespaced_name", self.name))

    @property
    def tool_schema(self) -> dict[str, Any]:
        schema = getattr(self.inner, "tool_schema", {})
        return schema if isinstance(schema, dict) else {}

    @property
    def approved(self) -> bool:
        return bool(getattr(self.inner, "approved", False))

    @approved.setter
    def approved(self, value: bool) -> None:
        if hasattr(self.inner, "approved"):
            self.inner.approved = value

    def execute(self, **params: Any) -> Any:
        payload = self.inner.execute(**params)
        shared_render_queue.push_many(_image_search_render_items(payload))
        return payload

    def get_schema(self) -> dict[str, Any]:
        return self.inner.get_schema()


def _wrap_chat_mcp_tool(tool: Any) -> Any:
    if (
        getattr(tool, "namespaced_name", None) == _IMAGE_SEARCH_SIMILAR_TOOL
        and isinstance(tool, Tool)
    ):
        return _ImageSearchRenderTool(tool)
    return tool


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
    loaded: list[Any] = []

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
                    _wrap_chat_mcp_tool(
                        MCPToolAdapter(
                            client=client,
                            namespaced_name=namespaced,
                            tool_schema=tool_schema,
                            approved=True,
                        )
                    )
                )
    else:
        for adapter in load_mcp_tools(config):
            if adapter.namespaced_name in approved_names:
                adapter.approved = True
                loaded.append(_wrap_chat_mcp_tool(adapter))

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


def _load_external_mcp_tools_for_chat() -> tuple[list[Any], dict[str, Any]]:
    """Load explicitly enabled MCP registry servers."""
    from general_chat.mcp_registry import MCPServerRegistryStore

    registry_root = _mcp_registry_root()
    if registry_root is None:
        return [], {"enabled": False, "tools": []}

    store = MCPServerRegistryStore(registry_root)
    tools, summary = store.load_enabled_tool_adapters()
    return [_wrap_chat_mcp_tool(tool) for tool in tools], summary


def reload_external_mcp_tools(agent: Any) -> dict[str, Any]:
    """Refresh an existing General Chat agent with enabled external MCP tools."""
    previous_names = getattr(agent, "_external_mcp_tool_names", set())
    for name in previous_names:
        agent.tools._tools.pop(name, None)
        agent.tools._schemas.pop(name, None)

    try:
        tools, summary = _load_external_mcp_tools_for_chat()
    except Exception as exc:
        summary = {
            "enabled": True,
            "mode": "registry",
            "tools": [],
            "error": str(exc),
            "registry_root": str(_mcp_registry_root() or ""),
        }
        agent._external_mcp_tools = []
        agent._external_mcp_tool_names = set()
        agent._external_mcp_summary = summary
        return summary

    registered: set[str] = set()
    for tool in tools:
        agent.tools.register(tool.name, tool)
        registered.add(tool.name)

    agent._external_mcp_tools = tools
    agent._external_mcp_tool_names = registered
    agent._external_mcp_summary = summary
    return summary


def create_agent(
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.3,
) -> BaseAgent:
    """Create the general-purpose chat agent.

    By default this keeps General Chat tool-free. Set
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

    external_mcp_summary: dict[str, Any] = {"enabled": False, "tools": []}
    external_mcp_tools: list[Any] = []
    if _mcp_registry_root() is not None:
        try:
            external_mcp_tools, external_mcp_summary = _load_external_mcp_tools_for_chat()
            mcp_tools.extend(external_mcp_tools)
        except Exception as exc:
            external_mcp_summary = {
                "enabled": True,
                "mode": "registry",
                "tools": [],
                "error": str(exc),
                "registry_root": str(_mcp_registry_root() or ""),
            }

    agent = BaseAgent(
        goal=(
            "Help users by answering questions, reasoning over optional context, "
            "using enabled tools when useful, and thinking through problems."
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
    agent._external_mcp_summary = external_mcp_summary  # type: ignore[attr-defined]
    agent._external_mcp_tools = external_mcp_tools  # type: ignore[attr-defined]
    agent._external_mcp_tool_names = {tool.name for tool in external_mcp_tools}  # type: ignore[attr-defined]
    return agent
