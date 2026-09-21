"""Hermes-backed agent runtime for admin-managed agent profiles.

A profile with ``runtime == "hermes"`` is answered by that agent's own
Hermes Agent profile (own skills, MCP servers, memory, sessions,
credentials) instead of the built-in OpenBench ``BaseAgent``. The profile
record stores only the Hermes API server URL; the bearer key is read from
the server environment (``GENERAL_CHAT_HERMES_KEY_<AGENT_ID>``) so one
agent's Hermes credential never sits in the shared profile store or reaches
the admin UI.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from openbench.adapters.hermes import HermesAdapter, HermesAgent

if TYPE_CHECKING:
    from general_chat.agent_store import AgentProfileRecord

HERMES_KEY_ENV_PREFIX = "GENERAL_CHAT_HERMES_KEY_"


class HermesRuntimeConfigError(ValueError):
    """Raised when a Hermes-backed profile cannot be built."""


def hermes_key_env_name(agent_id: str) -> str:
    """Env var that holds the ``API_SERVER_KEY`` of this agent's Hermes profile."""
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


def build_hermes_agent(profile: AgentProfileRecord) -> HermesAgent:
    """Build the chat-pipeline agent for a Hermes-backed profile."""
    try:
        url = validate_hermes_url(profile.hermes_url)
    except ValueError as exc:
        raise HermesRuntimeConfigError(f"agent {profile.id!r}: {exc}") from exc
    env_name = hermes_key_env_name(profile.id)
    api_key = os.getenv(env_name, "").strip()
    if not api_key:
        raise HermesRuntimeConfigError(f"agent {profile.id!r}: env {env_name} is not set")
    return HermesAgent(HermesAdapter(url, api_key=api_key, model=profile.id))
