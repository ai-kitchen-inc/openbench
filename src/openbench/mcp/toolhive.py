"""ToolHive discovery and control helpers for OpenBench MCP clients."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, urlparse, urlunparse

from openbench.mcp.config import MCPServerConnectionConfig, TransportName
from openbench.mcp.policy import redact_secrets
from openbench.mcp.schema import normalize_server_name

DEFAULT_TOOLHIVE_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_TOOLHIVE_TIMEOUT_SECONDS = 5.0
DEFAULT_TOOLHIVE_START_TIMEOUT_SECONDS = 180.0
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "host.docker.internal", "host.containers.internal"}
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ToolHiveError(RuntimeError):
    """User-safe ToolHive integration error."""


@dataclass(frozen=True)
class ToolHiveStatus:
    """ToolHive availability and version details."""

    available: bool
    api_available: bool = False
    cli_available: bool = False
    version: str | None = None
    api_base_url: str = DEFAULT_TOOLHIVE_BASE_URL
    source: str | None = None
    error: str | None = None
    setup_hint: str | None = None
    ui_cli_detected: bool = False
    cli_path: str | None = None
    management_mode: str = "unavailable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "apiAvailable": self.api_available,
            "api_available": self.api_available,
            "cliAvailable": self.cli_available,
            "cli_available": self.cli_available,
            "version": self.version,
            "apiBaseUrl": self.api_base_url,
            "api_base_url": self.api_base_url,
            "source": self.source,
            "error": self.error,
            "setupHint": self.setup_hint,
            "setup_hint": self.setup_hint,
            "uiCliDetected": self.ui_cli_detected,
            "ui_cli_detected": self.ui_cli_detected,
            "cliPath": self.cli_path,
            "cli_path": self.cli_path,
            "managementMode": self.management_mode,
            "management_mode": self.management_mode,
        }


@dataclass(frozen=True)
class ToolHiveWorkload:
    """Running ToolHive workload with its local MCP proxy URL."""

    name: str
    status: str = "unknown"
    url: str | None = None
    package: str | None = None
    port: int | None = None
    group: str | None = None
    created: str | None = None
    transport: TransportName | str | None = None
    source: str = "toolhive"
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "url": self.url,
            "package": self.package,
            "port": self.port,
            "group": self.group,
            "created": self.created,
            "transport": self.transport,
            "source": self.source,
            "raw": redact_secrets(self.raw),
        }


@dataclass(frozen=True)
class ToolHiveRegistryServer:
    """ToolHive registry server summary."""

    name: str
    title: str | None = None
    description: str | None = None
    transport: str | None = None
    tier: str | None = None
    server_type: str | None = None
    url: str | None = None
    tools: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title or self.name,
            "description": self.description,
            "transport": self.transport,
            "tier": self.tier,
            "type": self.server_type,
            "url": self.url,
            "tools": self.tools,
            "raw": redact_secrets(self.raw),
        }


def detect_toolhive_transport(url: str) -> TransportName:
    """Infer the MCP transport from a ToolHive proxy URL."""
    parsed = _parse_url(url)
    path = parsed.path.rstrip("/").lower()
    if path.endswith("/mcp") or path == "/mcp":
        return "streamable-http"
    if path.endswith("/sse") or path == "/sse" or parsed.fragment:
        return "sse"
    raise ToolHiveError("ToolHive MCP URLs must end in /mcp or /sse.")


def rewrite_toolhive_url(url: str, host: str | None = None) -> str:
    """Rewrite localhost ToolHive proxy URLs for containerized OpenBench."""
    target_host = (host or os.getenv("TOOLHIVE_HOST") or "").strip()
    if not target_host:
        return url
    parsed = _parse_url(url)
    if (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost"}:
        return url
    netloc = target_host
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def validate_toolhive_proxy_url(url: str, *, allow_remote: bool = False) -> str:
    """Validate a ToolHive MCP URL before storing or connecting to it."""
    parsed = _parse_url(url)
    if parsed.scheme not in {"http", "https"}:
        raise ToolHiveError("ToolHive MCP URLs must use http or https.")
    if not allow_remote and parsed.scheme != "http":
        raise ToolHiveError("ToolHive local proxy URLs must use http.")
    if allow_remote:
        detect_toolhive_transport(url)
        return url

    host = (parsed.hostname or "").lower()
    if not _is_allowed_local_host(host):
        raise ToolHiveError(
            "ToolHive proxy URL must use localhost, 127.0.0.1, host.docker.internal, "
            "host.containers.internal, or a configured private host."
        )
    detect_toolhive_transport(url)
    return url


def validate_toolhive_name(name: str) -> str:
    """Validate user-provided workload names passed to ToolHive."""
    cleaned = name.strip()
    if not _NAME_RE.match(cleaned):
        raise ToolHiveError(
            "ToolHive workload names may contain letters, numbers, dots, underscores, and hyphens."
        )
    return cleaned


def parse_toolhive_mcpservers_json(
    raw_json: str, *, host: str | None = None
) -> list[ToolHiveWorkload]:
    """Parse ``thv list --format mcpservers`` output."""
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ToolHiveError(f"ToolHive returned invalid mcpServers JSON: {exc.msg}.") from exc
    servers = payload.get("mcpServers") if isinstance(payload, dict) else None
    if not isinstance(servers, dict):
        raise ToolHiveError("ToolHive output did not contain a top-level mcpServers object.")

    workloads: list[ToolHiveWorkload] = []
    seen: set[str] = set()
    for raw_name, raw_config in servers.items():
        if not isinstance(raw_name, str) or not isinstance(raw_config, dict):
            raise ToolHiveError("ToolHive mcpServers entries must be objects keyed by name.")
        name = normalize_server_name(raw_name)
        if name in seen:
            raise ToolHiveError(
                f"Duplicate ToolHive server name after normalization: {raw_name!r}."
            )
        seen.add(name)
        url = raw_config.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ToolHiveError(f"ToolHive server {raw_name!r} did not include a URL.")
        rewritten = rewrite_toolhive_url(url.strip(), host=host)
        workloads.append(
            ToolHiveWorkload(
                name=name,
                status="running",
                url=validate_toolhive_proxy_url(rewritten),
                transport=detect_toolhive_transport(rewritten),
                raw=raw_config,
            )
        )
    return workloads


def toolhive_workload_to_mcp_config(
    workload: ToolHiveWorkload,
    *,
    host: str | None = None,
    allow_remote: bool = False,
) -> MCPServerConnectionConfig:
    """Convert a ToolHive workload into OpenBench MCP client config."""
    if not workload.url:
        raise ToolHiveError(f"ToolHive workload {workload.name!r} does not expose an MCP URL.")
    rewritten = rewrite_toolhive_url(workload.url, host=host)
    url = validate_toolhive_proxy_url(rewritten, allow_remote=allow_remote)
    return MCPServerConnectionConfig(
        transport=detect_toolhive_transport(url),
        namespace=normalize_server_name(workload.name),
        url=url,
        enabled=True,
        allowed=True,
    )


class ToolHiveService:
    """API-first ToolHive service with CLI fallback."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        cli_path: str | None = None,
        timeout_seconds: float | None = None,
        start_timeout_seconds: float | None = None,
        host: str | None = None,
    ):
        self.base_url = (
            base_url or os.getenv("TOOLHIVE_BASE_URL") or DEFAULT_TOOLHIVE_BASE_URL
        ).rstrip("/")
        self.cli_path = cli_path
        self.timeout_seconds = _timeout_from_env(
            "TOOLHIVE_TIMEOUT",
            timeout_seconds,
            DEFAULT_TOOLHIVE_TIMEOUT_SECONDS,
        )
        self.start_timeout_seconds = _timeout_from_env(
            "TOOLHIVE_START_TIMEOUT",
            start_timeout_seconds,
            DEFAULT_TOOLHIVE_START_TIMEOUT_SECONDS,
        )
        self.host = host or os.getenv("TOOLHIVE_HOST")

    def status(self) -> ToolHiveStatus:
        """Return ToolHive availability using API first, then CLI."""
        api_error: str | None = None
        cli_path, cli_source = self._resolve_cli()
        ui_cli_detected = cli_source == "ui-cli"
        try:
            payload = self._api_get("/api/v1beta/version")
            return ToolHiveStatus(
                available=True,
                api_available=True,
                cli_available=cli_path is not None,
                version=_extract_version(payload),
                api_base_url=self.base_url,
                source="api",
                ui_cli_detected=ui_cli_detected,
                cli_path=cli_path,
                management_mode="api",
            )
        except Exception as exc:
            api_error = _safe_error(exc)

        try:
            result = self._run_thv(["version"])
            _, source = self._resolve_cli()
            return ToolHiveStatus(
                available=True,
                api_available=False,
                cli_available=True,
                version=_version_from_cli(result.stdout),
                api_base_url=self.base_url,
                source=source or "cli",
                error=f"ToolHive API is not reachable at {self.base_url}: {api_error}",
                setup_hint="Start the local ToolHive API with: thv serve",
                ui_cli_detected=source == "ui-cli",
                cli_path=self._resolve_cli()[0],
                management_mode=source or "cli",
            )
        except ToolHiveError as exc:
            return ToolHiveStatus(
                available=False,
                api_available=False,
                cli_available=False,
                api_base_url=self.base_url,
                error=_safe_error(exc),
                setup_hint=(
                    "Install ToolHive or ToolHive UI, then open a new terminal and run thv version. "
                    "Start the local API with thv serve for full UI management."
                ),
                ui_cli_detected=False,
                cli_path=None,
                management_mode="unavailable",
            )

    def list_workloads(self) -> list[ToolHiveWorkload]:
        """List running ToolHive workloads with local proxy URLs."""
        try:
            payload = self._api_get("/api/v1beta/workloads")
            return [
                _workload_from_mapping(item, host=self.host)
                for item in _items(payload, "workloads")
            ]
        except Exception:
            result = self._run_thv(["list", "--format", "mcpservers"])
            return parse_toolhive_mcpservers_json(result.stdout, host=self.host)

    def list_registry_servers(self) -> list[ToolHiveRegistryServer]:
        """List servers in ToolHive's default registry."""
        try:
            payload = self._api_get("/api/v1beta/registry/default/servers")
            return [_registry_server_from_mapping(item) for item in _registry_items(payload)]
        except Exception:
            try:
                result = self._run_thv(["registry", "list", "--format", "json"])
                payload = json.loads(result.stdout)
            except Exception:
                return []
            return [_registry_server_from_mapping(item) for item in _registry_items(payload)]

    def start_workload(
        self,
        target: str,
        *,
        name: str | None = None,
        allow_remote: bool = False,
    ) -> ToolHiveWorkload:
        """Start or proxy a ToolHive workload from a registry name or remote MCP URL."""
        target = _validate_start_target(target, allow_remote=allow_remote)
        workload_name = validate_toolhive_name(name) if name else None
        api_payload = {"name": workload_name or _default_workload_name(target), "package": target}
        if _looks_like_url(target):
            api_payload["url"] = target
        try:
            payload = self._api_post(
                "/api/v1beta/workloads",
                api_payload,
                timeout_seconds=self.start_timeout_seconds,
            )
            if isinstance(payload, dict):
                return _workload_from_mapping(payload, host=self.host)
        except Exception:
            pass

        args = ["run", target]
        if workload_name:
            args.extend(["--name", workload_name])
        self._run_thv(args, timeout_seconds=self.start_timeout_seconds)
        return self._find_started_workload(workload_name or _default_workload_name(target))

    def stop_workload(self, name: str) -> None:
        name = validate_toolhive_name(name)
        try:
            self._api_post(f"/api/v1beta/workloads/{name}/stop", {})
            return
        except Exception:
            self._run_thv(["stop", name])

    def restart_workload(self, name: str) -> None:
        name = validate_toolhive_name(name)
        try:
            self._api_post(f"/api/v1beta/workloads/{name}/restart", {})
            return
        except Exception:
            self._run_thv(["restart", name])

    def delete_workload(self, name: str) -> None:
        name = validate_toolhive_name(name)
        try:
            self._api_delete(f"/api/v1beta/workloads/{name}")
            return
        except Exception:
            try:
                self._run_thv(["rm", name])
            except ToolHiveError:
                self._run_thv(["delete", name])

    def _find_started_workload(self, name: str) -> ToolHiveWorkload:
        normalized = normalize_server_name(name)
        for workload in self.list_workloads():
            if normalize_server_name(workload.name) == normalized:
                return workload
        raise ToolHiveError(f"ToolHive started {name!r}, but no MCP proxy URL was discovered yet.")

    def _api_get(self, path: str) -> Any:
        return self._api_request("GET", path)

    def _api_post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        return self._api_request(
            "POST", path, json_payload=payload, timeout_seconds=timeout_seconds
        )

    def _api_delete(self, path: str) -> Any:
        return self._api_request("DELETE", path)

    def _api_request(
        self,
        method: str,
        path: str,
        json_payload: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        try:
            import requests
        except ImportError as exc:
            raise ToolHiveError("requests is required for ToolHive API access.") from exc
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method,
                url,
                json=json_payload,
                timeout=timeout_seconds or self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ToolHiveError(f"ToolHive API request failed: {method} {path}") from exc
        if not response.content:
            return {}
        return response.json()

    def _run_thv(
        self,
        args: list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cli_path, _ = self._resolve_cli()
        if not cli_path:
            raise ToolHiveError(
                "ToolHive CLI is not installed or was not found on PATH or in the ToolHive UI bundle."
            )
        try:
            result = subprocess.run(
                [cli_path, *args],
                capture_output=True,
                text=True,
                timeout=timeout_seconds or self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ToolHiveError(
                "ToolHive CLI is not installed or was not found on PATH or in the ToolHive UI bundle."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ToolHiveError(f"ToolHive CLI timed out: thv {' '.join(args)}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise ToolHiveError(f"ToolHive CLI failed: {detail or 'unknown error'}")
        return result

    def _cli_available(self) -> bool:
        return self._resolve_cli()[0] is not None

    def _resolve_cli(self) -> tuple[str | None, str | None]:
        if self.cli_path:
            if shutil.which(self.cli_path) or self._path_exists(self.cli_path):
                return self.cli_path, "cli"
            return None, None
        path_cli = shutil.which("thv")
        if path_cli:
            return path_cli, "cli"
        for candidate in _toolhive_ui_cli_candidates():
            if self._path_exists(candidate):
                return candidate, "ui-cli"
        return None, None

    def _path_exists(self, path: str) -> bool:
        return Path(path).is_file()


def _parse_url(url: str) -> ParseResult:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ToolHiveError("ToolHive URL must be absolute.")
    return parsed


def _toolhive_ui_cli_candidates() -> list[str]:
    candidates: list[str] = []
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        candidates.append(str(Path(local_app_data) / "ToolHive" / "bin" / "thv.exe"))
    candidates.append(str(Path.home() / ".toolhive" / "bin" / "thv"))
    return candidates


def _is_allowed_local_host(host: str) -> bool:
    allowed = set(_LOCAL_HOSTS)
    allowed.update(
        item.strip().lower()
        for item in os.getenv("TOOLHIVE_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    )
    if host in allowed:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def _looks_like_url(value: str) -> bool:
    return bool(urlparse(value).scheme and urlparse(value).netloc)


def _validate_start_target(target: str, *, allow_remote: bool) -> str:
    cleaned = target.strip()
    if not cleaned:
        raise ToolHiveError("ToolHive server or remote MCP URL is required.")
    if _looks_like_url(cleaned):
        parsed = _parse_url(cleaned)
        if parsed.scheme not in {"http", "https"}:
            raise ToolHiveError("Remote MCP URLs must use http or https.")
        if not allow_remote and not _is_allowed_local_host((parsed.hostname or "").lower()):
            raise ToolHiveError("Remote MCP URLs require explicit user approval.")
        return cleaned
    return cleaned


def _default_workload_name(target: str) -> str:
    if _looks_like_url(target):
        parsed = urlparse(target)
        candidate = parsed.path.rstrip("/").rsplit("/", 1)[-1] or parsed.hostname or "remote-mcp"
        return validate_toolhive_name(normalize_server_name(candidate))
    return normalize_server_name(target.rsplit("/", 1)[-1])


def _items(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _registry_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    items: list[dict[str, Any]] = []
    for key in ("servers", "remote_servers", "registryServers"):
        value = payload.get(key)
        if isinstance(value, list):
            items.extend(item for item in value if isinstance(item, dict))
    return items


def _workload_from_mapping(raw: dict[str, Any], *, host: str | None = None) -> ToolHiveWorkload:
    raw_name = raw.get("name") or raw.get("workload_name") or raw.get("id") or "toolhive"
    raw_url = raw.get("url") or raw.get("mcp_url") or raw.get("proxy_url") or raw.get("endpoint")
    url = rewrite_toolhive_url(str(raw_url), host=host) if raw_url else None
    transport = (
        str(raw.get("transport") or detect_toolhive_transport(url)) if url else raw.get("transport")
    )
    return ToolHiveWorkload(
        name=normalize_server_name(str(raw_name)),
        status=str(raw.get("status") or "unknown"),
        url=url,
        package=_optional_str(raw.get("package") or raw.get("image") or raw.get("server")),
        port=_optional_int(raw.get("port") or raw.get("proxy_port")),
        group=_optional_str(raw.get("group")),
        created=_optional_str(raw.get("created") or raw.get("created_at")),
        transport=transport,
        raw=raw,
    )


def _registry_server_from_mapping(raw: dict[str, Any]) -> ToolHiveRegistryServer:
    name = str(raw.get("name") or raw.get("id") or "").strip()
    if not name:
        name = "server"
    tools = raw.get("tools")
    return ToolHiveRegistryServer(
        name=name,
        title=_optional_str(raw.get("title")),
        description=_optional_str(raw.get("description") or raw.get("overview")),
        transport=_optional_str(raw.get("transport")),
        tier=_optional_str(raw.get("tier")),
        server_type=_optional_str(raw.get("type")),
        url=_optional_str(raw.get("url")),
        tools=[str(item) for item in tools] if isinstance(tools, list) else [],
        raw=raw,
    )


def _extract_version(payload: Any) -> str | None:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for key in ("version", "Version", "toolhive_version", "current_version"):
            value = payload.get(key)
            if value:
                return str(value)
    return None


def _version_from_cli(output: str) -> str | None:
    for line in output.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timeout_from_env(name: str, explicit: float | None, default: float) -> float:
    if explicit is not None:
        return explicit
    value = os.getenv(name)
    if not value:
        return default
    try:
        timeout = float(value)
    except ValueError:
        return default
    return timeout if timeout > 0 else default


def _safe_error(exc: BaseException) -> str:
    return str(redact_secrets(str(exc) or exc.__class__.__name__))
