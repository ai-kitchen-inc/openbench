"""Hermes-backed agent runtime for admin-managed agent profiles.

A profile with ``runtime == "hermes"`` is answered by that agent's own
Hermes Agent profile (own skills, MCP servers, memory, sessions,
credentials) instead of the built-in OpenBench ``BaseAgent``. Two modes:

- **Managed** (``hermes_url`` empty, the default): general-chat renders the
  Hermes profile from the agent's panel fields and runs its gateway on the
  same host through :class:`~general_chat.hermes_supervisor.HermesSupervisor`.
  Keys never leave the server: the per-agent ``API_SERVER_KEY`` lives in
  that agent's profile dir, the LLM key and MCP secrets are handed to the
  gateway as environment.
- **Remote** (``hermes_url`` set): an externally run Hermes profile; its
  bearer key is read from ``GENERAL_CHAT_HERMES_KEY_<AGENT_ID>``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from general_chat.hermes_profile import (
    DEFAULT_MODEL,
    LLM_KEY_ENV,
    HermesMCPServer,
    HermesProfileSpec,
    secret_env_name,
)
from general_chat.hermes_supervisor import BACKEND_DOCKER
from openbench.adapters.hermes import HermesAdapter, HermesAgent

if TYPE_CHECKING:
    from pathlib import Path

    from general_chat.agent_store import AgentProfileRecord
    from general_chat.hermes_supervisor import HermesSupervisor

HERMES_KEY_ENV_PREFIX = "GENERAL_CHAT_HERMES_KEY_"
_SECRET_REF_RE = re.compile(r"\$\{secret:([A-Za-z0-9_.-]+)\}")
_ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_DOCKER_COMMANDS = ("docker", "docker.exe")


class HermesRuntimeConfigError(ValueError):
    """Raised when a Hermes-backed profile cannot be built."""


@dataclass
class ManagedHermesPlan:
    """What the supervisor needs to run one agent, plus what could not be carried over."""

    spec: HermesProfileSpec
    env: dict[str, str] = field(default_factory=dict)
    #: Human-readable notes for the admin panel (skipped skills / MCP servers).
    warnings: list[str] = field(default_factory=list)


def hermes_key_env_name(agent_id: str) -> str:
    """Env var that holds the ``API_SERVER_KEY`` of a *remote* Hermes profile."""
    return HERMES_KEY_ENV_PREFIX + re.sub(r"[^A-Z0-9]", "_", agent_id.strip().upper())


def validate_hermes_url(value: str) -> str:
    """Normalize a Hermes API server URL; raise ``ValueError`` when unusable."""
    url = value.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("URL Hermes harus berupa http(s)://host[:port]")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("URL Hermes tidak boleh memuat kredensial, query, atau fragment")
    return url


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def plan_managed_profile(
    profile: AgentProfileRecord,
    *,
    soul: str,
    skill_dirs: list[Path],
    mcp_servers: list[Any],
    secret_lookup: Any,
    backend: str,
    default_model: str = "",
) -> ManagedHermesPlan:
    """Map an agent's panel fields onto a minimal Hermes profile.

    Args:
        profile: The agent profile record.
        soul: Composed persona text (global/agent persona + guardrails).
        skill_dirs: Directories of the skills selected for this agent.
        mcp_servers: ``RegisteredMCPServer`` objects selected for this agent.
        secret_lookup: ``(server_id, key) -> str | None`` (the MCP secret store).
        backend: Supervisor backend — decides which MCP transports can run.
        default_model: Runtime default when the agent has no model of its own.
    """
    warnings: list[str] = []
    env: dict[str, str] = {}
    llm_key = os.getenv(LLM_KEY_ENV, "").strip()
    if llm_key:
        env[LLM_KEY_ENV] = llm_key
    else:
        warnings.append(f"{LLM_KEY_ENV} tidak diset di server; Hermes tidak dapat memanggil LLM.")

    knowledge_skills = []
    for skill_dir in skill_dirs:
        if (skill_dir / "tools.py").is_file():
            warnings.append(
                f"Skill '{skill_dir.name}' memakai tools.py dan tidak berjalan di Hermes (dilewati)."
            )
        else:
            knowledge_skills.append(skill_dir)

    servers: list[HermesMCPServer] = []
    for server in mcp_servers:
        config = dict(server.config or {})
        command = str(config.get("command") or "").strip().lower()
        if not server.enabled:
            warnings.append(f"Server MCP '{server.name}' nonaktif (dilewati).")
            continue
        if not config.get("url") and not command:
            warnings.append(
                f"Server MCP '{server.name}' hanya berjalan di dalam SSS dan tidak tersedia "
                "untuk Hermes (dilewati)."
            )
            continue
        if (
            backend == BACKEND_DOCKER
            and command
            and (command in _DOCKER_COMMANDS or command.endswith(("\\docker.exe", "/docker")))
        ):
            warnings.append(
                f"Server MCP '{server.name}' dijalankan lewat docker; container Hermes tidak "
                "punya akses docker (dilewati). Gunakan server MCP berbasis URL."
            )
            continue
        for text in _strings(config):
            for key in _SECRET_REF_RE.findall(text):
                value = secret_lookup(server.id, key)
                if value:
                    env[secret_env_name(key)] = value
                else:
                    warnings.append(f"Secret '{key}' untuk server MCP '{server.name}' belum diisi.")
            for name in _ENV_REF_RE.findall(_SECRET_REF_RE.sub("", text)):
                if os.getenv(name):
                    env[name] = os.environ[name]
        servers.append(
            HermesMCPServer(
                name=re.sub(r"[^a-z0-9_-]", "-", str(server.name).strip().lower()) or server.id,
                config=config,
                include_tools=[tool.name for tool in server.tools if tool.enabled],
            )
        )

    spec = HermesProfileSpec(
        agent_id=profile.id,
        soul=soul,
        model=profile.model or default_model or DEFAULT_MODEL,
        skill_dirs=knowledge_skills,
        mcp_servers=servers,
        memory_enabled=profile.hermes_memory,
    )
    return ManagedHermesPlan(spec=spec, env=env, warnings=warnings)


def build_hermes_agent(
    profile: AgentProfileRecord,
    *,
    supervisor: HermesSupervisor | None = None,
    plan: ManagedHermesPlan | None = None,
) -> HermesAgent:
    """Build the chat-pipeline agent for a Hermes-backed profile."""
    if not profile.hermes_url:
        if supervisor is None or plan is None:
            raise HermesRuntimeConfigError(
                f"agent {profile.id!r}: managed Hermes is not enabled on this server "
                "(set GENERAL_CHAT_HERMES_BACKEND) and no Hermes URL is configured"
            )
        endpoint = supervisor.ensure(plan.spec, plan.env)
        return HermesAgent(HermesAdapter(endpoint.url, api_key=endpoint.api_key, model=profile.id))
    try:
        url = validate_hermes_url(profile.hermes_url)
    except ValueError as exc:
        raise HermesRuntimeConfigError(f"agent {profile.id!r}: {exc}") from exc
    env_name = hermes_key_env_name(profile.id)
    api_key = os.getenv(env_name, "").strip()
    if not api_key:
        raise HermesRuntimeConfigError(f"agent {profile.id!r}: env {env_name} is not set")
    return HermesAgent(HermesAdapter(url, api_key=api_key, model=profile.id))
