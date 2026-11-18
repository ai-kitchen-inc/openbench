"""Launch policy for MCP servers imported through the HTTP API.

A stdio MCP server is a command line the API process spawns. An imported
config therefore *is* code execution on the API host, and on the deployed
VM the API container holds the Docker socket, which makes it root on the
host. Checking only that ``command`` is a non-empty string (what the config
parser does) is not a control.

This module decides which command lines an API import may register:

* ``docker run`` of an allowlisted image, with a closed set of flags (no
  ``--privileged``, no host mounts outside configured roots, never the
  Docker socket);
* ``docker mcp gateway run [--profile NAME]``;
* ``npx -y <allowlisted package> [args...]``.

Everything else (``bash``, ``python``, ``sh -c`` ...) is rejected. Bundled
servers that legitimately run ``python`` or ``openbench`` are seeded from
the repository's own YAML at startup and never pass through this check.

Modes (``GENERAL_CHAT_MCP_STDIO_IMPORT``):

* ``allowlist`` (default) — the rules above;
* ``off`` — API imports may not contain stdio servers at all;
* ``any`` — no restriction (previous behavior; for trusted single-user dev).

The allowlists are environment-driven so an operator can widen them without
a code change; see the ``*_ENV`` constants.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath

from openbench.mcp.config import MCPClientConfig

MODE_ENV = "GENERAL_CHAT_MCP_STDIO_IMPORT"
IMAGE_PREFIXES_ENV = "GENERAL_CHAT_MCP_DOCKER_IMAGE_PREFIXES"
NPX_PACKAGES_ENV = "GENERAL_CHAT_MCP_NPX_PACKAGES"
VOLUME_ROOTS_ENV = "GENERAL_CHAT_MCP_DOCKER_VOLUME_ROOTS"

MODE_ALLOWLIST = "allowlist"
MODE_OFF = "off"
MODE_ANY = "any"

DEFAULT_IMAGE_PREFIXES = (
    "us-central1-docker.pkg.dev/sss-poc1-corporate/openbench/",
    "openbench/",
    "mcp/",
)
DEFAULT_NPX_PACKAGES = ("@modelcontextprotocol/*", "@isaacphi/mcp-gdrive")

# docker run flags that take no value.
_DOCKER_BOOL_FLAGS = frozenset({"--rm", "-i", "--interactive", "--read-only", "--init"})
# docker run flags that take a value and need no further inspection.
_DOCKER_VALUE_FLAGS = frozenset(
    {
        "-e",
        "--env",
        "--memory",
        "-m",
        "--cpus",
        "--pids-limit",
        "--cap-drop",
        "--name",
        "--tmpfs",
        "--user",
        "-u",
        "--pull",
    }
)
_DOCKER_NETWORKS = frozenset({"none", "bridge"})
_DOCKER_SECURITY_OPTS = frozenset({"no-new-privileges", "no-new-privileges:true"})
_DOCKER_SOCKET_NAMES = ("docker.sock", "containerd.sock")

# Process-environment names that change what the spawned program executes.
_BLOCKED_ENV_NAMES = frozenset({"PATH", "NODE_OPTIONS", "BASH_ENV", "ENV", "IFS"})
_BLOCKED_ENV_PREFIXES = ("LD_", "DYLD_", "PYTHON", "NPM_CONFIG_", "DOCKER_")


class MCPLaunchPolicyError(ValueError):
    """An imported MCP server's command line is not allowed."""


def _csv_env(name: str, default: Iterable[str]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return tuple(default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def stdio_import_mode() -> str:
    """Return the active mode; unknown values fall back to ``allowlist``."""
    mode = os.getenv(MODE_ENV, "").strip().lower()
    return mode if mode in {MODE_ALLOWLIST, MODE_OFF, MODE_ANY} else MODE_ALLOWLIST


def config_has_stdio(config: MCPClientConfig) -> bool:
    """Return True when any server in ``config`` is spawned as a process."""
    return any(server.transport == "stdio" for server in config.servers.values())


def check_import(config: MCPClientConfig) -> None:
    """Validate every stdio server of an API-imported config.

    Raises:
        MCPLaunchPolicyError: A stdio server is not allowed by the active mode.
    """
    mode = stdio_import_mode()
    if mode == MODE_ANY:
        return
    for name, server in config.servers.items():
        if server.transport != "stdio":
            continue
        if mode == MODE_OFF:
            raise MCPLaunchPolicyError(
                f"MCP server {name!r}: importing stdio (command-based) servers is disabled."
            )
        try:
            check_stdio_launch(server.command or "", server.args, server.env, server.cwd)
        except MCPLaunchPolicyError as exc:
            raise MCPLaunchPolicyError(f"MCP server {name!r}: {exc}") from exc


def check_stdio_launch(
    command: str,
    args: list[str],
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
) -> None:
    """Validate one stdio command line against the allowlist rules.

    Raises:
        MCPLaunchPolicyError: The command line is not an allowed launch shape.
    """
    for key in env or {}:
        upper = key.upper()
        if upper in _BLOCKED_ENV_NAMES or upper.startswith(_BLOCKED_ENV_PREFIXES):
            raise MCPLaunchPolicyError(f"environment variable {key!r} is not allowed.")

    if command == "docker":
        _check_docker(list(args))
        return
    if command == "npx":
        # npx reads .npmrc / package.json / node_modules/.bin from its working
        # directory, so a chosen cwd could swap in attacker-supplied code.
        # (docker run ignores cwd: relative mounts and env files are refused.)
        if cwd:
            raise MCPLaunchPolicyError("a working directory (cwd) is not allowed for npx.")
        _check_npx(list(args))
        return
    raise MCPLaunchPolicyError(
        f"command {command!r} is not allowed. Only 'docker run <approved image>', "
        "'docker mcp gateway run' and 'npx -y <approved package>' can be imported."
    )


def _check_docker(args: list[str]) -> None:
    if args[:3] == ["mcp", "gateway", "run"]:
        rest = args[3:]
        if not rest:
            return
        if len(rest) == 2 and rest[0] == "--profile" and _is_plain_token(rest[1]):
            return
        raise MCPLaunchPolicyError("'docker mcp gateway run' only accepts --profile NAME.")
    if not args or args[0] != "run":
        raise MCPLaunchPolicyError("only 'docker run' and 'docker mcp gateway run' are allowed.")

    index = 1
    image: str | None = None
    while index < len(args):
        token = args[index]
        if not token.startswith("-"):
            image = token
            break
        flag, has_inline, inline_value = token.partition("=")
        if flag in _DOCKER_BOOL_FLAGS and not has_inline:
            index += 1
            continue
        if has_inline:
            value = inline_value
            index += 1
        else:
            if index + 1 >= len(args):
                raise MCPLaunchPolicyError(f"docker flag {flag!r} is missing its value.")
            value = args[index + 1]
            index += 2
        _check_docker_value_flag(flag, value)

    if image is None:
        raise MCPLaunchPolicyError("docker run has no image.")
    prefixes = _csv_env(IMAGE_PREFIXES_ENV, DEFAULT_IMAGE_PREFIXES)
    if not _is_plain_token(image) or not image.startswith(prefixes):
        raise MCPLaunchPolicyError(
            f"docker image {image!r} is not in the approved list ({IMAGE_PREFIXES_ENV})."
        )


def _check_docker_value_flag(flag: str, value: str) -> None:
    if flag in _DOCKER_VALUE_FLAGS:
        return
    if flag == "--network":
        if value not in _DOCKER_NETWORKS:
            raise MCPLaunchPolicyError(f"docker network {value!r} is not allowed.")
        return
    if flag == "--security-opt":
        if value not in _DOCKER_SECURITY_OPTS:
            raise MCPLaunchPolicyError(f"docker security option {value!r} is not allowed.")
        return
    if flag in {"-v", "--volume"}:
        _check_docker_volume(value)
        return
    raise MCPLaunchPolicyError(f"docker flag {flag!r} is not allowed.")


def _check_docker_volume(value: str) -> None:
    source = value.split(":", 1)[0]
    if any(name in value for name in _DOCKER_SOCKET_NAMES):
        raise MCPLaunchPolicyError("mounting a container runtime socket is not allowed.")
    roots = _csv_env(VOLUME_ROOTS_ENV, ())
    if not source.startswith("/") or ".." in PurePosixPath(source).parts:
        raise MCPLaunchPolicyError(f"docker volume source {source!r} must be an absolute path.")
    source_path = PurePosixPath(source)
    for root in roots:
        root_path = PurePosixPath(root)
        if source_path == root_path or root_path in source_path.parents:
            return
    raise MCPLaunchPolicyError(
        f"docker volume source {source!r} is outside the approved roots ({VOLUME_ROOTS_ENV})."
    )


def _check_npx(args: list[str]) -> None:
    if len(args) < 2 or args[0] not in {"-y", "--yes"}:
        raise MCPLaunchPolicyError("npx must be invoked as 'npx -y <package> [args...]'.")
    package = args[1]
    if package.startswith("-") or not _is_plain_token(package):
        raise MCPLaunchPolicyError(f"npx package {package!r} is not a valid package name.")
    # Strip a trailing @version, keeping a leading scope ("@scope/name@1.2").
    head, _, _version = package[1:].partition("@")
    name = package[0] + head
    patterns = _csv_env(NPX_PACKAGES_ENV, DEFAULT_NPX_PACKAGES)
    if not any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns):
        raise MCPLaunchPolicyError(
            f"npx package {name!r} is not in the approved list ({NPX_PACKAGES_ENV})."
        )


def _is_plain_token(value: str) -> bool:
    """Reject empty values, unexpanded ``${VAR}`` placeholders and whitespace."""
    return bool(value) and "$" not in value and not any(ch.isspace() for ch in value)
