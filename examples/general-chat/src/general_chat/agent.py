"""General Chat agent factory."""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from openbench.chat import render_queue as shared_render_queue
from openbench.core.abstractions import Tool
from openbench.core.providers import ProviderConfig, ProviderType, get_provider_service
from openbench.intelligence import BaseAgent, Persona

_DEFAULT_MCP_APPROVED_TOOLS = (
    "openbench.filter_records",
    "openbench.distinct_values",
    "openbench.group_and_aggregate",
    "openbench.top_n_records",
)
_IMAGE_SEARCH_SIMILAR_TOOL = "image_search.search_similar_images"
_SAM_COUNT_TOOL = "sam_segmentation.count_objects_with_sam3"
_SAM_SERVICE_INFO_TOOL = "sam_segmentation.service_info"
_PROVIDER_NAME = "gemini-general-chat"
logger = logging.getLogger(__name__)


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
    if not _env_flag("GENERAL_CHAT_MCP_REGISTRY_ENABLED", default=True):
        return None
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

    @property
    def timeout_seconds(self) -> Any:
        return getattr(self.inner, "timeout_seconds", None)

    def execute(self, **params: Any) -> Any:
        payload = self.inner.execute(**params)
        shared_render_queue.push_many(_image_search_render_items(payload))
        return payload

    def get_schema(self) -> dict[str, Any]:
        return self.inner.get_schema()


class _SamSegmentationCountTool(Tool):
    """Tool wrapper that avoids repeated identical SAM count calls in one chat turn."""

    def __init__(self, inner: Tool):
        self.inner = inner
        self._cache: dict[str, Any] = {}
        self._inflight: dict[str, tuple[threading.Event, dict[str, Any]]] = {}
        self._lock = threading.Lock()

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

    @property
    def timeout_seconds(self) -> Any:
        return getattr(self.inner, "timeout_seconds", None)

    def execute(self, **params: Any) -> Any:
        normalized = dict(params)
        normalized.setdefault("return_segments", False)
        normalized.setdefault("return_overlay", False)
        cache_key = json.dumps(normalized, sort_keys=True, default=str)
        with self._lock:
            if cache_key in self._cache:
                return self._cached_payload(cache_key)
            inflight = self._inflight.get(cache_key)
            if inflight is None:
                event = threading.Event()
                state: dict[str, Any] = {}
                self._inflight[cache_key] = (event, state)
                is_owner = True
            else:
                event, state = inflight
                is_owner = False

        if not is_owner:
            event.wait()
            if "exception" in state:
                raise state["exception"]
            payload = copy.deepcopy(state.get("payload"))
            if isinstance(payload, dict):
                payload["cached"] = True
                payload.setdefault(
                    "final_answer_hint",
                    "This is a shared in-flight SAM count result. Answer from count; "
                    "do not rerun SAM or inspect the filesystem unless the result has an error.",
                )
            return payload

        try:
            payload = self.inner.execute(**normalized)
            if isinstance(payload, dict) and not payload.get("error") and "count" in payload:
                payload.setdefault(
                    "final_answer_hint",
                    "Use the returned count as the answer for this image/concept. Do not call "
                    "SAM again, service_info, or filesystem unless the result contains an error "
                    "or the user asks for diagnostics.",
                )
                with self._lock:
                    self._cache[cache_key] = copy.deepcopy(payload)
            state["payload"] = copy.deepcopy(payload)
            return payload
        except BaseException as exc:
            state["exception"] = exc
            raise
        finally:
            with self._lock:
                self._inflight.pop(cache_key, None)
                event.set()

    def _cached_payload(self, cache_key: str) -> Any:
        payload = copy.deepcopy(self._cache[cache_key])
        if isinstance(payload, dict):
            payload["cached"] = True
            payload.setdefault(
                "final_answer_hint",
                "This is a cached duplicate SAM count result. Answer from count; "
                "do not rerun SAM or inspect the filesystem unless the result has an error.",
            )
        return payload

    def get_schema(self) -> dict[str, Any]:
        schema = copy.deepcopy(self.inner.get_schema())
        function = schema.get("function")
        if isinstance(function, dict):
            description = str(function.get("description") or "")
            guidance = (
                " For image counting, call this once per image/concept and answer from "
                "the returned count. Do not call service_info or filesystem after a "
                "successful result."
            )
            if guidance.strip() not in description:
                function["description"] = f"{description}\n\n{guidance.strip()}".strip()
            parameters = function.get("parameters")
            if isinstance(parameters, dict):
                properties = parameters.get("properties")
                if isinstance(properties, dict):
                    for name in ("return_segments", "return_overlay"):
                        if isinstance(properties.get(name), dict):
                            properties[name]["default"] = False
        return schema


class _DiagnosticMCPToolDescription(Tool):
    """Tool wrapper that marks MCP service-info tools as diagnostics."""

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

    @property
    def timeout_seconds(self) -> Any:
        return getattr(self.inner, "timeout_seconds", None)

    def execute(self, **params: Any) -> Any:
        return self.inner.execute(**params)

    def get_schema(self) -> dict[str, Any]:
        schema = copy.deepcopy(self.inner.get_schema())
        function = schema.get("function")
        if isinstance(function, dict):
            description = str(function.get("description") or "")
            guidance = (
                "Diagnostic-only tool. Use it only after an operational SAM tool returns "
                "an error, not after a successful count."
            )
            if guidance not in description:
                function["description"] = f"{description}\n\n{guidance}".strip()
        return schema


def _wrap_chat_mcp_tool(tool: Any) -> Any:
    if (
        getattr(tool, "namespaced_name", None) == _IMAGE_SEARCH_SIMILAR_TOOL
        and isinstance(tool, Tool)
    ):
        return _ImageSearchRenderTool(tool)
    if getattr(tool, "namespaced_name", None) == _SAM_COUNT_TOOL and isinstance(tool, Tool):
        return _SamSegmentationCountTool(tool)
    if (
        getattr(tool, "namespaced_name", None) == _SAM_SERVICE_INFO_TOOL
        and isinstance(tool, Tool)
    ):
        return _DiagnosticMCPToolDescription(tool)
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


def _unregister_tool(agent: Any, name: str) -> None:
    tools = getattr(agent, "tools", None)
    if tools is None:
        return
    tool_map = getattr(tools, "_tools", None)
    schema_map = getattr(tools, "_schemas", None)
    if isinstance(tool_map, dict):
        tool_map.pop(name, None)
    if isinstance(schema_map, dict):
        schema_map.pop(name, None)


def _tool_available_to_chat(agent: Any, name: str) -> bool:
    tools = getattr(agent, "tools", None)
    if tools is None:
        return False
    tool_map = getattr(tools, "_tools", None)
    schema_map = getattr(tools, "_schemas", None)
    if not isinstance(tool_map, dict) or name not in tool_map:
        return False
    if isinstance(schema_map, dict) and name not in schema_map:
        return False
    try:
        schemas = tools.get_schemas()
    except Exception:
        return False
    return any(
        isinstance(schema, dict)
        and isinstance(schema.get("function"), dict)
        and schema["function"].get("name") == name
        for schema in schemas
    )


def _with_runtime_verification(
    summary: dict[str, Any],
    *,
    registered: set[str],
    registration_errors: list[str] | None = None,
) -> dict[str, Any]:
    verified_summary = dict(summary)
    tools = list(verified_summary.get("tools") or [])
    expected = [
        str(item.get("adapter_name") or "")
        for item in tools
        if isinstance(item, dict) and item.get("enabled", True)
    ]
    missing = sorted(name for name in expected if name and name not in registered)
    errors = [item for item in registration_errors or [] if item]
    if missing:
        errors.append(
            "Runtime registration did not expose these tools to chat: "
            + ", ".join(missing)
        )
    existing_error = verified_summary.get("error")
    if existing_error:
        errors.insert(0, str(existing_error))
    verified_summary["registered_tools"] = sorted(registered)
    verified_summary["provider_tool_names"] = sorted(registered)
    verified_summary["available_to_chat"] = bool(expected) and not errors
    verified_summary["runtime_tool_count"] = len(registered)
    verified_summary["registered_tool_count"] = len(registered)
    verified_summary["error"] = "; ".join(errors) or None
    return verified_summary


def reload_external_mcp_tools(agent: Any) -> dict[str, Any]:
    """Refresh an existing General Chat agent with enabled external MCP tools."""
    previous_names = set(getattr(agent, "_external_mcp_tool_names", set()))

    try:
        tools, summary = _load_external_mcp_tools_for_chat()
    except Exception as exc:
        logger.warning("mcp.chat.load_failed error=%s", exc)
        for name in previous_names:
            _unregister_tool(agent, name)
        summary = {
            "enabled": True,
            "mode": "registry",
            "tools": [],
            "error": str(exc),
            "registry_root": str(_mcp_registry_root() or ""),
            "available_to_chat": False,
            "registered_tools": [],
        }
        agent._external_mcp_tools = []
        agent._external_mcp_tool_names = set()
        agent._external_mcp_summary = summary
        return summary

    duplicate_names: dict[str, int] = {}
    for tool in tools:
        duplicate_names[tool.name] = duplicate_names.get(tool.name, 0) + 1
    registration_errors = [
        f"Multiple MCP tools map to provider tool name {name!r}; rename or disable one."
        for name, count in duplicate_names.items()
        if count > 1
    ]
    if registration_errors:
        logger.warning("mcp.chat.registration_duplicate errors=%s", registration_errors)
        for name in previous_names:
            _unregister_tool(agent, name)
        summary = _with_runtime_verification(
            summary,
            registered=set(),
            registration_errors=registration_errors,
        )
        agent._external_mcp_tools = []
        agent._external_mcp_tool_names = set()
        agent._external_mcp_summary = summary
        return summary

    for name in previous_names:
        _unregister_tool(agent, name)

    registered: set[str] = set()
    for tool in tools:
        try:
            agent.tools.register(tool.name, tool)
        except Exception as exc:
            registration_errors.append(f"{tool.name}: {exc}")
            logger.warning("mcp.chat.register_tool_failed tool=%s error=%s", tool.name, exc)
            continue
        if _tool_available_to_chat(agent, tool.name):
            registered.add(tool.name)
            logger.info(
                "mcp.chat.register_tool tool=%s namespaced=%s",
                tool.name,
                getattr(tool, "namespaced_name", tool.name),
            )
        else:
            registration_errors.append(f"{tool.name}: registered but not visible to chat")
            logger.warning("mcp.chat.register_tool_invisible tool=%s", tool.name)
            _unregister_tool(agent, tool.name)

    if registration_errors:
        for name in registered:
            _unregister_tool(agent, name)
        registered = set()

    summary = _with_runtime_verification(
        summary,
        registered=registered,
        registration_errors=registration_errors,
    )
    registry_root = _mcp_registry_root()
    if registry_root is not None:
        try:
            from general_chat.mcp_registry import MCPServerRegistryStore

            MCPServerRegistryStore(registry_root).mark_runtime_registration(
                registered,
                summary.get("diagnostics") if isinstance(summary.get("diagnostics"), list) else [],
            )
        except Exception as exc:
            logger.warning("mcp.chat.mark_runtime_failed error=%s", exc)
    agent._external_mcp_tools = [tool for tool in tools if tool.name in registered]
    agent._external_mcp_tool_names = registered
    agent._external_mcp_summary = summary
    logger.info(
        "mcp.chat.reload complete loaded=%d registered=%d available=%s error=%s",
        len(tools),
        len(registered),
        summary.get("available_to_chat"),
        summary.get("error"),
    )
    return summary


def _configure_general_chat_provider(api_key: str, model: str) -> None:
    """Configure the demo LLM provider without writing user-level provider state."""
    get_provider_service().configure(
        ProviderConfig(
            name=_PROVIDER_NAME,
            provider_type=ProviderType.LLM,
            provider="gemini",
            plugin_type="chat",
            credentials={"api_key": api_key},
            settings={"model": model},
            is_default=True,
        ),
        save=False,
    )


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

    _configure_general_chat_provider(key, resolved_model)

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

    agent = BaseAgent(
        goal=(
            "Help users by answering questions, reasoning over optional context, "
            "using enabled tools when useful, and thinking through problems. For "
            "uploaded image counting, call the SAM count tool once per image/concept "
            "and answer from the returned count; /general-chat/uploads paths are for "
            "image MCP tools, not filesystem MCP inspection."
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
    if _mcp_registry_root() is not None:
        reload_external_mcp_tools(agent)
    return agent
