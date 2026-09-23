"""Render one minimal, isolated Hermes Agent profile per agent.

A Hermes *profile* is a self-contained ``HERMES_HOME`` directory (own
``config.yaml``, ``.env``, ``SOUL.md``, ``skills/``, ``memories/``,
``sessions/``, ``state.db``). Hermes' defaults load far more than a narrow
business agent needs — every built-in toolset (terminal, files, browser,
web, cron, delegation, ...), ~100 bundled skills in the prompt index, the
memory + user-profile tools, and every configured MCP server. This module
writes a profile that starts from *nothing* and adds back only what the
agent was given:

- ``platform_toolsets.api_server`` is an explicit allow-list (Hermes treats
  a saved list as authoritative), and ``agent.disabled_toolsets`` — which
  Hermes applies last — additionally suppresses every built-in toolset that
  was not selected, so a Hermes default change can never re-enable one.
- ``.no-bundled-skills`` stops Hermes seeding/re-syncing bundled skills;
  only the agent's own knowledge skills are copied into ``skills/``.
- ``mcp_servers`` holds only this agent's servers, each with a
  ``tools.include`` allow-list and resources/prompts wrappers off.
- ``.env`` holds only this agent's credentials: a freshly generated
  ``API_SERVER_KEY`` plus *empty* slots for the LLM key and MCP secrets
  (filled in by the operator on the host — never written by this module).

Verified against Hermes Agent v2026.9.14 (``hermes_cli/tools_config.py``,
``toolsets.py``, ``tools/skills_sync.py``, ``tools/mcp_tool_registration.py``,
``gateway/platforms/api_server_openai_routes.py``).
"""

from __future__ import annotations

import argparse
import re
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

HERMES_VERSION_VERIFIED = "v2026.9.14"
NO_BUNDLED_SKILLS_MARKER = ".no-bundled-skills"
DEFAULT_API_PORT = 8642
API_PLATFORM = "api_server"
NO_MCP_SENTINEL = "no_mcp"
LLM_KEY_ENV = "GOOGLE_API_KEY"
DEFAULT_PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-3.5-flash"

#: Every configurable built-in Hermes toolset. Anything not explicitly
#: selected for an agent lands in ``agent.disabled_toolsets``.
BUILTIN_TOOLSETS = (
    "web",
    "x_search",
    "vision",
    "video",
    "image_gen",
    "video_gen",
    "computer_use",
    "terminal",
    "skills",
    "browser",
    "cronjob",
    "file",
    "tts",
    "todo",
    "memory",
    "session_search",
    "connections",
    "clarify",
    "code_execution",
    "delegation",
    "homeassistant",
    "kanban",
    "discord",
    "discord_admin",
    "spotify",
)

#: Toolsets that reach the host (shell, files, browser, code, sub-agents,
#: scheduled jobs). Profiles are not a sandbox, so these are refused unless
#: the caller opts in explicitly per agent.
HOST_ACCESS_TOOLSETS = frozenset(
    {"terminal", "file", "browser", "code_execution", "delegation", "cronjob", "computer_use"}
)

_SSS_SECRET_RE = re.compile(r"\$\{secret:([A-Za-z0-9_.-]+)\}")
_PROFILE_DIRS = ("memories", "sessions", "skills", "logs", "workspace", "home")


class HermesProfileError(ValueError):
    """Raised when a profile spec is invalid."""


@dataclass
class HermesMCPServer:
    """One MCP server this agent may use, with its tool allow-list."""

    name: str
    #: OpenBench ``MCPServerConnectionConfig``-shaped dict (command/args/env
    #: or url/headers). ``${secret:NAME}`` placeholders become ``${NAME}``
    #: env references resolved from this profile's own ``.env``.
    config: dict[str, Any]
    include_tools: list[str] = field(default_factory=list)


@dataclass
class HermesProfileSpec:
    """Everything that defines one agent's Hermes profile."""

    agent_id: str
    soul: str
    model: str = DEFAULT_MODEL
    provider: str = DEFAULT_PROVIDER
    port: int = DEFAULT_API_PORT
    host: str = "127.0.0.1"
    #: Built-in Hermes toolsets this agent gets (default: none).
    toolsets: list[str] = field(default_factory=list)
    allow_host_access: bool = False
    #: Knowledge-only skill directories (each holds a SKILL.md) to copy in.
    skill_dirs: list[Path] = field(default_factory=list)
    mcp_servers: list[HermesMCPServer] = field(default_factory=list)
    memory_enabled: bool = False
    max_turns: int = 30


def _env_name(secret_name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", secret_name.upper())


def _translate_secrets(value: Any, found: set[str]) -> Any:
    """``${secret:NAME}`` (OpenBench) -> ``${NAME}`` (Hermes env reference)."""
    if isinstance(value, str):

        def _sub(match: re.Match[str]) -> str:
            name = _env_name(match.group(1))
            found.add(name)
            return "${" + name + "}"

        return _SSS_SECRET_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {key: _translate_secrets(item, found) for key, item in value.items()}
    if isinstance(value, list):
        return [_translate_secrets(item, found) for item in value]
    return value


def validate_spec(spec: HermesProfileSpec) -> None:
    if not re.fullmatch(r"[a-z0-9-]{1,64}", spec.agent_id):
        raise HermesProfileError(f"invalid agent id {spec.agent_id!r}")
    if not spec.soul.strip():
        raise HermesProfileError("soul text is required (Hermes would seed its default SOUL)")
    unknown = sorted(set(spec.toolsets) - set(BUILTIN_TOOLSETS))
    if unknown:
        raise HermesProfileError(f"unknown Hermes toolsets: {', '.join(unknown)}")
    risky = sorted(set(spec.toolsets) & HOST_ACCESS_TOOLSETS)
    if risky and not spec.allow_host_access:
        raise HermesProfileError(
            f"toolsets {', '.join(risky)} reach the host; set allow_host_access to accept that"
        )
    names = [server.name for server in spec.mcp_servers]
    if len(names) != len(set(names)):
        raise HermesProfileError("duplicate MCP server names")
    for name in names:
        if name in BUILTIN_TOOLSETS or name == NO_MCP_SENTINEL or not name.strip():
            raise HermesProfileError(f"MCP server name {name!r} collides with a Hermes toolset")
    for skill_dir in spec.skill_dirs:
        if not (skill_dir / "SKILL.md").is_file():
            raise HermesProfileError(f"skill {skill_dir} has no SKILL.md")
        if (skill_dir / "tools.py").exists():
            raise HermesProfileError(
                f"skill {skill_dir.name} has tools.py — OpenBench tool skills do not run in "
                "Hermes; expose the tools through an MCP server instead"
            )


def render_config(spec: HermesProfileSpec) -> tuple[dict[str, Any], list[str]]:
    """Build the profile ``config.yaml`` dict and the secret env names it references."""
    validate_spec(spec)
    secret_envs: set[str] = set()
    toolsets = sorted(set(spec.toolsets))
    if spec.skill_dirs and "skills" not in toolsets:
        toolsets.append("skills")
    if spec.memory_enabled and "memory" not in toolsets:
        toolsets.append("memory")

    mcp_block: dict[str, Any] = {}
    for server in spec.mcp_servers:
        source = _translate_secrets(server.config, secret_envs)
        entry: dict[str, Any] = {}
        for key in ("command", "args", "env", "url", "headers"):
            if source.get(key):
                entry[key] = source[key]
        if "command" not in entry and "url" not in entry:
            raise HermesProfileError(f"MCP server {server.name!r} has neither command nor url")
        entry["enabled"] = True
        entry["tools"] = {
            "include": sorted(set(server.include_tools)),
            "resources": False,
            "prompts": False,
        }
        entry["sampling"] = {"enabled": False}
        mcp_block[server.name] = entry

    platform_list = toolsets + (sorted(mcp_block) if mcp_block else [NO_MCP_SENTINEL])
    config: dict[str, Any] = {
        "model": {"default": spec.model, "provider": spec.provider},
        "platform_toolsets": {API_PLATFORM: platform_list},
        "agent": {
            "max_turns": spec.max_turns,
            "disabled_toolsets": sorted(set(BUILTIN_TOOLSETS) - set(toolsets)),
        },
        "skills": {"creation_nudge_interval": 0},
        "memory": {
            "memory_enabled": spec.memory_enabled,
            "user_profile_enabled": False,
            "nudge_interval": 0,
        },
        "terminal": {"backend": "local", "home_mode": "profile"},
        "updates": {"check": False},
        "telemetry": {"shared_metrics": {"enabled": False, "send": False}},
    }
    if mcp_block:
        config["mcp_servers"] = mcp_block
    return config, sorted(secret_envs)


def _merge_env(existing: str, wanted: dict[str, str]) -> str:
    """Keep every value already in ``.env``; append only missing keys."""
    present = {
        line.split("=", 1)[0].strip()
        for line in existing.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    lines = existing.rstrip("\n").splitlines() if existing.strip() else []
    lines += [f"{key}={value}" for key, value in wanted.items() if key not in present]
    return "\n".join(lines) + "\n"


def write_profile(root: str | Path, spec: HermesProfileSpec) -> Path:
    """Create or refresh ``<root>/<agent_id>/``; returns the profile dir.

    Re-running is safe: ``config.yaml``, ``SOUL.md`` and ``skills/`` are
    rewritten from the spec, while ``.env`` values, memories, sessions and
    ``state.db`` are never touched.
    """
    config, secret_envs = render_config(spec)
    profile_dir = Path(root) / spec.agent_id
    if spec.allow_host_access:
        # Pin tool subprocesses to the profile's own workspace, not the launch dir.
        config["terminal"]["cwd"] = str((profile_dir / "workspace").resolve())
    for subdir in _PROFILE_DIRS:
        (profile_dir / subdir).mkdir(parents=True, exist_ok=True)
    (profile_dir / NO_BUNDLED_SKILLS_MARKER).touch()
    header = (
        f"# Generated by general_chat.hermes_profile for agent {spec.agent_id!r}.\n"
        f"# Minimal by design — verified against Hermes Agent {HERMES_VERSION_VERIFIED}.\n"
    )
    (profile_dir / "config.yaml").write_text(
        header + yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    (profile_dir / "SOUL.md").write_text(spec.soul.strip() + "\n", encoding="utf-8")

    skills_root = profile_dir / "skills"
    wanted = {skill_dir.name for skill_dir in spec.skill_dirs}
    for stale in skills_root.iterdir():
        if stale.is_dir() and stale.name not in wanted:
            shutil.rmtree(stale)
    for skill_dir in spec.skill_dirs:
        target = skills_root / skill_dir.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(skill_dir, target)
        _ensure_frontmatter(target / "SKILL.md", skill_dir.name)

    env_path = profile_dir / ".env"
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    wanted_env = {
        "API_SERVER_ENABLED": "true",
        "API_SERVER_HOST": spec.host,
        "API_SERVER_PORT": str(spec.port),
        "API_SERVER_MODEL_NAME": spec.agent_id,
        "API_SERVER_KEY": secrets.token_urlsafe(32),
        LLM_KEY_ENV: "",
        **dict.fromkeys(secret_envs, ""),
    }
    env_path.write_text(_merge_env(existing, wanted_env), encoding="utf-8")
    return profile_dir


def _ensure_frontmatter(skill_md: Path, fallback_name: str) -> None:
    """Hermes indexes skills by YAML frontmatter; OpenBench uses H1 + first paragraph."""
    text = skill_md.read_text(encoding="utf-8")
    if text.lstrip().startswith("---"):
        return
    lines = [line.strip() for line in text.splitlines()]
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), fallback_name)
    body = [line for line in lines if line and not line.startswith("#")]
    description = (body[0] if body else title)[:300]
    front = yaml.safe_dump(
        {"name": fallback_name, "description": description or title},
        sort_keys=False,
        allow_unicode=True,
    )
    skill_md.write_text(f"---\n{front}---\n\n{text}", encoding="utf-8")


def unfilled_env_keys(profile_dir: str | Path) -> list[str]:
    """Names in the profile ``.env`` that still have an empty value."""
    env_path = Path(profile_dir) / ".env"
    if not env_path.exists():
        return []
    empty = []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if not value.strip():
                empty.append(key.strip())
    return empty


def _load_spec_file(path: Path) -> list[HermesProfileSpec]:
    """Parse a ``agents: [...]`` YAML spec file (see hermes/agents.example.yaml)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    specs = []
    for index, item in enumerate(raw.get("agents") or []):
        soul = str(item.get("soul") or "")
        if item.get("soul_file"):
            soul = (path.parent / str(item["soul_file"])).read_text(encoding="utf-8")
        specs.append(
            HermesProfileSpec(
                agent_id=str(item.get("id") or ""),
                soul=soul,
                model=str(item.get("model") or DEFAULT_MODEL),
                provider=str(item.get("provider") or DEFAULT_PROVIDER),
                port=int(item.get("port") or DEFAULT_API_PORT + index),
                host=str(item.get("host") or "127.0.0.1"),
                toolsets=[str(name) for name in item.get("toolsets") or []],
                allow_host_access=bool(item.get("allow_host_access", False)),
                skill_dirs=[path.parent / str(p) for p in item.get("skills") or []],
                mcp_servers=[
                    HermesMCPServer(
                        name=str(server.get("name") or ""),
                        config=dict(server.get("config") or {}),
                        include_tools=[str(t) for t in server.get("include_tools") or []],
                    )
                    for server in item.get("mcp_servers") or []
                ],
                memory_enabled=bool(item.get("memory", False)),
                max_turns=int(item.get("max_turns") or 30),
            )
        )
    ports = [spec.port for spec in specs]
    if len(ports) != len(set(ports)):
        raise HermesProfileError("two agents share an API port")
    return specs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render minimal per-agent Hermes profiles.")
    parser.add_argument("spec", type=Path, help="YAML spec file with an 'agents' list")
    parser.add_argument("--out", type=Path, required=True, help="profiles root directory")
    args = parser.parse_args(argv)
    for spec in _load_spec_file(args.spec):
        profile_dir = write_profile(args.out, spec)
        missing = ", ".join(unfilled_env_keys(profile_dir)) or "none"
        print(f"{spec.agent_id}: {profile_dir} (port {spec.port}; empty .env keys: {missing})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
