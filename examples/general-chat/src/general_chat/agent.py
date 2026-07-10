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
from openbench.intelligence.base import Message, MessageRole
from openbench.intelligence.skill_registry import SkillRegistry
from openbench.mcp.permissions import MCPPermissionSession, PermissionProvider

_DEFAULT_MCP_APPROVED_TOOLS = (
    "openbench.filter_records",
    "openbench.distinct_values",
    "openbench.group_and_aggregate",
    "openbench.top_n_records",
)
_IMAGE_SEARCH_SIMILAR_TOOL = "image_search.search_similar_images"
_SAM_COUNT_TOOL = "sam_segmentation.count_objects_with_sam3"
_SAM_SERVICE_INFO_TOOL = "sam_segmentation.service_info"
_DASHBOARD_TOOL_PREFIX = "dashboard_generator."
_DASHBOARD_GENERATE_TOOL = "dashboard_generator.generate_dashboard"
_AGGREGATE_TOOL_PREFIX = "aggregate_data."
_PROVIDER_NAME = "gemini-general-chat"
_VLM_PROVIDER_NAME = "general-chat-vlm"
_DASHBOARD_SKILL_NAME = "dashboard-generator"
_VEHICLE_PLATE_SKILL_NAME = "vehicle-plate-reading"
_OLLAMA_VLM_DEFAULT_BASE_URL = "http://localhost:11434/v1"
logger = logging.getLogger(__name__)

_VLM_MODEL_ALIASES: dict[str, tuple[str, str]] = {
    "gemini": ("gemini", "gemini-2.5-flash"),
    "gemini-flash": ("gemini", "gemini-2.5-flash"),
    "gemini-2.5-flash": ("gemini", "gemini-2.5-flash"),
    "gemma-2b": ("ollama", "gemma4:e2b"),
    "gemma 2b": ("ollama", "gemma4:e2b"),
    "gemma2b": ("ollama", "gemma4:e2b"),
    "gemma4:e2b": ("ollama", "gemma4:e2b"),
    "gemma-4b": ("ollama", "gemma4:e4b"),
    "gemma 4b": ("ollama", "gemma4:e4b"),
    "gemma4b": ("ollama", "gemma4:e4b"),
    "gemma4:e4b": ("ollama", "gemma4:e4b"),
}


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


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using %s", name, raw, default)
        return default


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


def _dashboard_skill_dir() -> Path:
    import openbench

    return Path(openbench.__file__).resolve().parent / "skills" / _DASHBOARD_SKILL_NAME


_DASHBOARD_REVISION_KEYWORDS = (
    "revisi",
    "revision",
    "revise",
    "ubah",
    "diubah",
    "ganti",
    "diganti",
    "change",
    "changed",
    "replace",
    "update",
    "warna",
    "color",
)


def _latest_dashboard_revision_note(agent: BaseAgent) -> str | None:
    for message in reversed(agent.memory.messages):
        if message.role != MessageRole.USER or not message.content:
            continue
        content = str(message.content).strip()
        if content.lower().startswith("goal:"):
            content = content[5:].strip()
        content = content.split("\n\n", 1)[0].strip()
        lowered = content.lower()
        if "dashboard" in lowered or "chart" in lowered or "grafik" in lowered or "panel" in lowered:
            if any(keyword in lowered for keyword in _DASHBOARD_REVISION_KEYWORDS):
                return content
        return None
    return None


def _wrap_dashboard_generate_tool(agent: BaseAgent, tool_fn: Any) -> Any:
    def _generate_dashboard_with_revision_context(**params: Any) -> Any:
        if not params.get("revision_notes"):
            note = _latest_dashboard_revision_note(agent)
            if note:
                params["revision_notes"] = note
        return tool_fn(**params)

    return _generate_dashboard_with_revision_context


def _vehicle_plate_skill_dir() -> Path:
    import openbench

    return Path(openbench.__file__).resolve().parent / "skills" / _VEHICLE_PLATE_SKILL_NAME


def _normalize_vlm_provider(provider: str | None) -> str:
    normalized = (provider or "").strip().lower()
    if normalized in {"gemma", "ollama-gemma"}:
        return "ollama"
    return normalized


def _resolve_vlm_selection() -> tuple[str, str, str]:
    requested = os.getenv("GENERAL_CHAT_VLM_MODEL") or os.getenv("OPENBENCH_VLM_MODEL")
    requested = (requested or "gemini-2.5-flash").strip()
    alias_key = requested.lower()
    provider, model = _VLM_MODEL_ALIASES.get(alias_key, ("", requested))
    provider = _normalize_vlm_provider(
        os.getenv("GENERAL_CHAT_VLM_PROVIDER")
        or os.getenv("OPENBENCH_VLM_PROVIDER")
        or provider
        or ("ollama" if model.lower().startswith("gemma") else "gemini")
    )
    return provider, model, requested


def _sync_agent_system_message(agent: BaseAgent) -> None:
    if agent.memory.messages and agent.memory.messages[0].role == MessageRole.SYSTEM:
        agent.memory.messages[0] = Message(role=MessageRole.SYSTEM, content=agent._system_prompt)
    else:
        agent.memory.add_system(agent._system_prompt)


def _load_dashboard_skill(agent: BaseAgent) -> None:
    """Load only the dashboard SDK skill into General Chat."""
    registry = SkillRegistry()
    registry.load_project_skills([_dashboard_skill_dir()])
    skill_context = registry.compose_context()
    if skill_context:
        agent._system_prompt = f"{agent._system_prompt}\n\n{skill_context}"
        _sync_agent_system_message(agent)

    registered: set[str] = set()
    for tool_name, tool_fn, tool_schema in registry.collect_tools():
        if tool_name in agent.tools._tools:
            raise ValueError(
                f"Dashboard skill tool '{tool_name}' conflicts with an existing chat tool."
            )
        if tool_name == "generate_dashboard":
            tool_fn = _wrap_dashboard_generate_tool(agent, tool_fn)
        agent.tools.register(tool_name, tool_fn, schema=tool_schema)
        registered.add(tool_name)

    agent._skill_registry = registry  # type: ignore[attr-defined]
    agent._dashboard_skill_tools = sorted(registered)  # type: ignore[attr-defined]


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


class _DashboardGeneratorRenderTool(Tool):
    """Tool wrapper that renders dashboard MCP artifacts in General Chat."""

    def __init__(self, inner: Tool):
        self.inner = inner
        self.revision_note_provider: Any | None = None

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

    # Keys returned to the agent. The full payload (viewModel, datasets, kpis,
    # sections) goes to the render queue for the UI only — echoing it back to
    # the LLM bloats the history window and previously drove regenerate loops.
    _AGENT_RESULT_KEYS = (
        "type",
        "title",
        "description",
        "name",
        "url",
        "dashboardUrl",
        "path",
        "mimeType",
        "size",
        "sectionCount",
        "kpiCount",
        "chartCount",
        "tableCount",
        "warnings",
        "templateSource",
        "templateName",
    )

    def execute(self, **params: Any) -> Any:
        if not params.get("revision_notes") and self.revision_note_provider:
            note = self.revision_note_provider()
            if note:
                params["revision_notes"] = note
        payload = self.inner.execute(**params)
        if isinstance(payload, dict) and payload.get("type") == "dashboard" and not payload.get("error"):
            shared_render_queue.push(payload)
            result = {
                key: payload[key] for key in self._AGENT_RESULT_KEYS if key in payload
            }
            result["status"] = "created"
            warnings = payload.get("warnings") or []
            if warnings:
                result["final_answer_hint"] = (
                    "Dashboard artifact was created and its KPIs rendered, but some "
                    "section items were invalid and were dropped (see warnings), so "
                    "charts may be missing. Do NOT re-call generate_dashboard with the "
                    "same ViewModel — that just repeats the error. Either present the "
                    "dashboard as-is and tell the user (in their language) that charts "
                    "need proper chart objects, or call it again ONLY if you supply "
                    "corrected sections[].items as full inline objects: {type:'chart', "
                    "chart_type, title, data:[rows], x_field, y_field} — never bare "
                    "numbers or dataset indices. Do not paste the full ViewModel."
                )
            else:
                result["final_answer_hint"] = (
                    "Dashboard artifact is ready and has been rendered in the side panel. "
                    "Do NOT call generate_dashboard again for this request. Summarize the "
                    "dashboard briefly in the user's language; do not paste the full "
                    "ViewModel."
                )
            return result
        return payload

    def get_schema(self) -> dict[str, Any]:
        return self.inner.get_schema()


def _attach_dashboard_revision_context(agent: BaseAgent) -> None:
    tools = getattr(agent, "tools", None)
    tool_map = getattr(tools, "_tools", None)
    if not isinstance(tool_map, dict):
        return
    for tool in tool_map.values():
        if isinstance(tool, _DashboardGeneratorRenderTool):
            tool.revision_note_provider = lambda agent=agent: _latest_dashboard_revision_note(agent)


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
    namespaced_name = getattr(tool, "namespaced_name", None)
    if (
        isinstance(namespaced_name, str)
        and namespaced_name.startswith((_DASHBOARD_TOOL_PREFIX, _AGGREGATE_TOOL_PREFIX))
        and hasattr(tool, "close_after_execute")
    ):
        # Keep stdio MCP processes alive across multi-step metadata -> aggregate -> render flows.
        tool.close_after_execute = False
    if (
        namespaced_name == _DASHBOARD_GENERATE_TOOL
        and isinstance(tool, Tool)
    ):
        return _DashboardGeneratorRenderTool(tool)
    if (
        namespaced_name == _IMAGE_SEARCH_SIMILAR_TOOL
        and isinstance(tool, Tool)
    ):
        return _ImageSearchRenderTool(tool)
    if namespaced_name == _SAM_COUNT_TOOL and isinstance(tool, Tool):
        return _SamSegmentationCountTool(tool)
    if (
        namespaced_name == _SAM_SERVICE_INFO_TOOL
        and isinstance(tool, Tool)
    ):
        return _DiagnosticMCPToolDescription(tool)
    return tool


def _load_mcp_tools_for_chat(
    permission_session: MCPPermissionSession | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Load MCP-backed OpenBench tools for opt-in General Chat testing."""
    from openbench.mcp.adapters import MCPToolAdapter, load_mcp_tools
    from openbench.mcp.client import MCPClient
    from openbench.mcp.config import MCPConfig, MCPServerConfig
    from openbench.mcp.server import OpenBenchMCPServer
    from openbench.mcp.transports import InMemoryMCPTransport

    mode = os.getenv("GENERAL_CHAT_MCP_MODE", "local").strip().lower()
    allowed_names = set(
        _csv_env("GENERAL_CHAT_MCP_APPROVED_TOOLS", _DEFAULT_MCP_APPROVED_TOOLS)
    )
    permission_session = permission_session or MCPPermissionSession()
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
                if namespaced not in allowed_names:
                    continue
                loaded.append(
                    _wrap_chat_mcp_tool(
                        MCPToolAdapter(
                            client=client,
                            namespaced_name=namespaced,
                            tool_schema=tool_schema,
                            permission_session=permission_session,
                        )
                    )
                )
    else:
        for adapter in load_mcp_tools(config, permission_session=permission_session):
            if adapter.namespaced_name in allowed_names:
                if adapter.namespaced_name.startswith(
                    (_DASHBOARD_TOOL_PREFIX, _AGGREGATE_TOOL_PREFIX)
                ):
                    # Keep these stdio MCP processes alive across the metadata
                    # -> aggregate -> render workflow. On Windows,
                    # closing stdio/AnyIO immediately after each call can hang
                    # long enough for the outer tool timeout to fire even when
                    # the dashboard tool itself has already completed.
                    adapter.close_after_execute = False
                adapter.approved = True
                loaded.append(_wrap_chat_mcp_tool(adapter))

    return loaded, {
        "enabled": True,
        "mode": mode,
        "config_path": str(config_path),
        "allowed_tools": sorted(allowed_names),
        "approved_tools": sorted(allowed_names),
        "tools": [
            {
                "name": tool.namespaced_name,
                "adapter_name": tool.name,
                "description": tool.tool_schema.get("description", ""),
            }
            for tool in loaded
        ],
    }


def _load_external_mcp_tools_for_chat(
    server_ids: set[str] | None = None,
    permission_session: MCPPermissionSession | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Load explicitly enabled MCP registry servers."""
    from general_chat.mcp_registry import MCPServerRegistryStore

    registry_root = _mcp_registry_root()
    if registry_root is None:
        return [], {"enabled": False, "tools": []}

    store = MCPServerRegistryStore(registry_root)
    tools, summary = store.load_enabled_tool_adapters(
        server_ids=server_ids,
        permission_session=permission_session,
    )
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


def _summary_tool_server_map(summary: dict[str, Any]) -> dict[str, str]:
    tools = summary.get("tools")
    if not isinstance(tools, list):
        return {}
    mapping: dict[str, str] = {}
    for item in tools:
        if not isinstance(item, dict):
            continue
        adapter_name = item.get("adapter_name")
        server_id = item.get("server_id")
        if adapter_name and server_id:
            mapping[str(adapter_name)] = str(server_id)
    return mapping


def reload_external_mcp_tools(
    agent: Any,
    server_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Refresh an existing General Chat agent with enabled external MCP tools."""
    selected_server_ids = set(server_ids) if server_ids is not None else None
    previous_names = set(getattr(agent, "_external_mcp_tool_names", set()))
    raw_previous_tools = getattr(agent, "_external_mcp_tools", [])
    previous_tools = (
        list(raw_previous_tools)
        if isinstance(raw_previous_tools, (list, tuple, set))
        else []
    )
    raw_previous_tool_servers = getattr(agent, "_external_mcp_tool_servers", {})
    previous_tool_servers = (
        dict(raw_previous_tool_servers)
        if isinstance(raw_previous_tool_servers, dict)
        else {}
    )
    if selected_server_ids is None:
        names_to_unregister = previous_names
        preserved_names: set[str] = set()
        preserved_tools: list[Any] = []
        preserved_tool_servers: dict[str, str] = {}
    else:
        names_to_unregister = {
            name
            for name in previous_names
            if previous_tool_servers.get(name) in selected_server_ids
        }
        preserved_names = previous_names - names_to_unregister
        preserved_tools = [
            tool
            for tool in previous_tools
            if getattr(tool, "name", None) in preserved_names
        ]
        preserved_tool_servers = {
            name: server_id
            for name, server_id in previous_tool_servers.items()
            if name in preserved_names
        }

    try:
        tools, summary = _load_external_mcp_tools_for_chat(
            server_ids=selected_server_ids,
            permission_session=getattr(agent, "_mcp_permission_session", None),
        )
    except Exception as exc:
        logger.warning("mcp.chat.load_failed error=%s", exc)
        for name in names_to_unregister:
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
        agent._external_mcp_tools = preserved_tools
        agent._external_mcp_tool_names = preserved_names
        agent._external_mcp_tool_servers = preserved_tool_servers
        agent._external_mcp_summary = summary
        return summary

    duplicate_names: dict[str, int] = {}
    for name in preserved_names:
        duplicate_names[name] = duplicate_names.get(name, 0) + 1
    for tool in tools:
        duplicate_names[tool.name] = duplicate_names.get(tool.name, 0) + 1
    registration_errors = [
        f"Multiple MCP tools map to provider tool name {name!r}; rename or disable one."
        for name, count in duplicate_names.items()
        if count > 1
    ]
    if registration_errors:
        logger.warning("mcp.chat.registration_duplicate errors=%s", registration_errors)
        for name in names_to_unregister:
            _unregister_tool(agent, name)
        summary = _with_runtime_verification(
            summary,
            registered=set(),
            registration_errors=registration_errors,
        )
        agent._external_mcp_tools = preserved_tools
        agent._external_mcp_tool_names = preserved_names
        agent._external_mcp_tool_servers = preserved_tool_servers
        agent._external_mcp_summary = summary
        return summary

    for name in names_to_unregister:
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
                server_ids=selected_server_ids,
            )
        except Exception as exc:
            logger.warning("mcp.chat.mark_runtime_failed error=%s", exc)
    new_tool_servers = _summary_tool_server_map(summary)
    agent._external_mcp_tools = preserved_tools + [tool for tool in tools if tool.name in registered]
    agent._external_mcp_tool_names = preserved_names | registered
    agent._external_mcp_tool_servers = {
        **preserved_tool_servers,
        **{name: new_tool_servers[name] for name in registered if name in new_tool_servers},
    }
    agent._external_mcp_summary = summary
    _attach_dashboard_revision_context(agent)
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
    # Gemini 3 reasoning tokens count against the output budget; the SDK default
    # of 8192 lets a large prompt + thinking trip MAX_TOKENS with no answer text
    # (then the agent burns empty-response retries). Give it real headroom.
    max_output_tokens = _env_int("GENERAL_CHAT_MAX_OUTPUT_TOKENS", 32768)
    get_provider_service().configure(
        ProviderConfig(
            name=_PROVIDER_NAME,
            provider_type=ProviderType.LLM,
            provider="gemini",
            plugin_type="chat",
            credentials={"api_key": api_key},
            settings={"model": model, "max_output_tokens": max_output_tokens},
            is_default=True,
        ),
        save=False,
    )


def _configure_general_chat_vlm_provider(
    *,
    api_key: str | None,
    provider: str,
    model: str,
    temperature: float,
    max_output_tokens: int,
) -> dict[str, Any]:
    """Configure the demo VLM provider without writing user-level provider state."""
    provider = _normalize_vlm_provider(provider)
    credentials: dict[str, Any] = {}
    settings: dict[str, Any] = {"model": model, "temperature": temperature}
    base_url: str | None = None

    if provider == "gemini":
        credentials["api_key"] = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        settings["max_output_tokens"] = max_output_tokens
    else:
        if os.getenv("OPENBENCH_VLM_API_KEY") or os.getenv("GEMMA_VLM_API_KEY"):
            credentials["api_key"] = (
                os.getenv("OPENBENCH_VLM_API_KEY") or os.getenv("GEMMA_VLM_API_KEY")
            )
        settings["max_tokens"] = max_output_tokens
        base_url = (
            os.getenv("GENERAL_CHAT_VLM_BASE_URL")
            or os.getenv("OPENBENCH_VLM_BASE_URL")
            or os.getenv("GEMMA_VLM_BASE_URL")
            or _OLLAMA_VLM_DEFAULT_BASE_URL
        )
        settings["base_url"] = base_url

    get_provider_service().configure(
        ProviderConfig(
            name=_VLM_PROVIDER_NAME,
            provider_type=ProviderType.VLM,
            provider=provider,
            plugin_type="vision",
            credentials=credentials,
            settings=settings,
            is_default=True,
        ),
        save=False,
    )
    return {"provider": provider, "model": model, "base_url": base_url}


def _create_vision_agent(api_key: str | None) -> tuple[Any | None, dict[str, Any]]:
    if not _env_flag("GENERAL_CHAT_VLM_ENABLED", default=True):
        return None, {"enabled": False}

    from openbench.intelligence import VisionAgent

    provider, model, requested = _resolve_vlm_selection()
    temperature = _env_float("GENERAL_CHAT_VLM_TEMPERATURE", 0.2)
    max_output_tokens = _env_int("GENERAL_CHAT_VLM_MAX_OUTPUT_TOKENS", 2048)
    provider_details = _configure_general_chat_vlm_provider(
        api_key=api_key,
        provider=provider,
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    print(f"[vision] provider={provider_details['provider']} resolved_model={model}")

    vision_agent = VisionAgent(
        goal="Understand uploaded images for General Chat.",
        model=model,
        provider_name=_VLM_PROVIDER_NAME,
        temperature=temperature,
        skills=[_vehicle_plate_skill_dir()],
        system_prompt=(
            "You are the image understanding stage for General Chat. Describe the "
            "uploaded image only from visible evidence. If the user asks for a vehicle "
            "plate number, follow the vehicle-plate-reading protocol. Otherwise, give a "
            "concise general visual observation that helps the chat agent answer."
        ),
    )
    return vision_agent, {
        "enabled": True,
        "provider": provider,
        "model": model,
        "requested_model": requested,
        "base_url": provider_details.get("base_url"),
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        "skill": _VEHICLE_PLATE_SKILL_NAME,
    }


def create_agent(
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.3,
    mcp_permission_provider: PermissionProvider | None = None,
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
    vision_agent, vlm_summary = _create_vision_agent(key)

    persona_dir = get_persona_dir()
    persona = Persona.from_dir(persona_dir) if persona_dir.is_dir() else None

    mcp_tools: list[Any] = []
    mcp_permission_session = MCPPermissionSession(mcp_permission_provider)
    mcp_summary: dict[str, Any] = {
        "enabled": False,
        "mode": os.getenv("GENERAL_CHAT_MCP_MODE", "local"),
        "tools": [],
        "approved_tools": list(_DEFAULT_MCP_APPROVED_TOOLS),
        "allowed_tools": list(_DEFAULT_MCP_APPROVED_TOOLS),
    }
    mcp_error: str | None = None
    if _env_flag("GENERAL_CHAT_MCP_ENABLED", default=False):
        try:
            mcp_tools, mcp_summary = _load_mcp_tools_for_chat(mcp_permission_session)
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

    # Cap the conversation history sent each turn so the prompt (and latency)
    # stays bounded as sessions grow. Set GENERAL_CHAT_HISTORY_TOKEN_BUDGET=0 to
    # send the full history (old behavior).
    _history_budget = _env_int("GENERAL_CHAT_HISTORY_TOKEN_BUDGET", 16000)
    agent = BaseAgent(
        goal=(
            "Help users by answering questions, reasoning over optional context, "
            "using enabled tools when useful, and thinking through problems. When "
            "the user uploads a CSV/XLSX source and asks for a table, average, "
            "sum, count, group-by, top-N, or other non-dashboard aggregate answer, "
            "use the Aggregate Data MCP: call aggregate_data.extract_metadata when "
            "you need column names, then aggregate_data.aggregate_data with read-only "
            "SQLite against table `data`, and answer from the returned records. When "
            "the user uploads a CSV/XLSX source and asks for a dashboard, follow "
            "the dashboard-generator skill/MCP SOP: (1) call aggregate_data.extract_metadata and inspect "
            "dashboard_memory matches, (2) call load_dashboard_memory when the user "
            "asks for the same dashboard, refreshed data, or a revision, (3) call "
            "aggregate_data.aggregate_data ONCE, passing a list of ALL the SQL queries you need "
            "(one per chart/metric) so every dataset comes back in a single tool "
            "call — do NOT call aggregate_data once per metric, (4) compose a "
            "declarative ViewModel from the returned datasets while preserving "
            "previous panels unless the user asked to change them, then (5) generate "
            "the dashboard artifact with dashboard_generator.generate_dashboard, "
            "source_path, previous_dashboard_id, and "
            "revision_panel_titles for revisions. For uploaded images, use the provided visual "
            "observations as the source of truth for general image understanding and "
            "vehicle plate reading. For uploaded image counting, call the SAM count "
            "tool once per image/concept when that MCP tool is enabled, and answer "
            "from the returned count; /general-chat/uploads paths are for image MCP "
            "tools, not filesystem MCP inspection."
        ),
        model=resolved_model,
        temperature=temperature,
        persona=persona,
        tools=mcp_tools or None,
        history_token_budget=_history_budget if _history_budget > 0 else None,
        max_iterations=_env_int("GENERAL_CHAT_MAX_ITERATIONS", 25),
        parallel_tool_execution=True,
    )
    if _env_flag("GENERAL_CHAT_DASHBOARD_SKILL_ENABLED", default=True):
        _load_dashboard_skill(agent)
    else:
        agent._skill_registry = None  # type: ignore[attr-defined]
        agent._dashboard_skill_tools = []  # type: ignore[attr-defined]
    _attach_dashboard_revision_context(agent)
    agent._mcp_enabled = bool(mcp_summary.get("enabled"))  # type: ignore[attr-defined]
    agent._mcp_summary = mcp_summary  # type: ignore[attr-defined]
    agent._mcp_error = mcp_error  # type: ignore[attr-defined]
    agent._mcp_tools = mcp_tools  # type: ignore[attr-defined]
    agent._mcp_permission_session = mcp_permission_session  # type: ignore[attr-defined]
    agent._external_mcp_summary = external_mcp_summary  # type: ignore[attr-defined]
    agent._external_mcp_tools = external_mcp_tools  # type: ignore[attr-defined]
    agent._external_mcp_tool_names = {tool.name for tool in external_mcp_tools}  # type: ignore[attr-defined]
    agent._external_mcp_tool_servers = {}  # type: ignore[attr-defined]
    agent._vision_agent = vision_agent  # type: ignore[attr-defined]
    agent._vlm_summary = vlm_summary  # type: ignore[attr-defined]
    if _mcp_registry_root() is not None:
        reload_external_mcp_tools(agent)
    return agent
