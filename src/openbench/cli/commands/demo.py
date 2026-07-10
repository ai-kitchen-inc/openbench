"""Demo management CLI commands."""

import ast
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from openbench.core.constants import (
    DEFAULT_HEALTH_WAIT_TIMEOUT_S,
    DEFAULT_PORT_WAIT_TIMEOUT_S,
    DEFAULT_PROC_WAIT_TIMEOUT_S,
)

console = Console()

# Script suffixes to discover as runnable demos
_SCRIPT_SUFFIXES = ("_demo.py", "_workflow.py")
_IGNORED_SCRIPT_PARTS = {
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    "site-packages",
}


_GENERAL_CHAT_MCP_VARIANTS = {
    "dashboard-generator": {
        "name": "general-chat-dashboard-generator",
        "description": "General Chat with dashboard_generator MCP tools",
    },
    "image-search": {
        "name": "general-chat-image-search",
        "description": "General Chat with DINOv3 image_search MCP tools",
    },
    "sam-segmentation": {
        "name": "general-chat-sam-segmentation",
        "description": "General Chat with SAM 3 concept counting MCP tool",
    },
}
_GENERAL_CHAT_ALL_MCP_NAME = "general-chat-all"
_GENERAL_CHAT_ALL_MCP_CONFIGS = (
    "dashboard-generator-stdio.yaml",
    "filesystem-mcp.yaml",
    "generic-api-docker.yaml",
    "image-search-docker.yaml",
    "sam-segmentation-docker.yaml",
    "docker-mcp-gateway.yaml",
    "custom-function-docker.yaml",
)
_CUSTOM_FN_LOCAL_IMAGE = "custom-function-mcp:local"


def _resolve_pnpm_command() -> list[str] | None:
    """Resolve pnpm command across platforms and installations."""
    if os.name == "nt":
        # On Windows, prefer the .cmd shim for CreateProcess compatibility.
        if shutil.which("pnpm.cmd"):
            return ["pnpm.cmd"]
        if shutil.which("pnpm"):
            return ["pnpm"]
    else:
        if shutil.which("pnpm"):
            return ["pnpm"]
    # Fallback when pnpm is managed through Corepack
    if shutil.which("corepack"):
        return ["corepack", "pnpm"]
    return None


def _find_project_root() -> Path:
    """Walk up from this file to find the directory containing pyproject.toml."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise click.ClickException("Could not find project root (no pyproject.toml found)")


def _detect_port(server_py: Path) -> int:
    """Extract port value from server.py, fallback 8000.

    Matches both CLI-style ``--port 8005`` and Python-style
    ``port=8005`` / ``port = 8005`` in uvicorn.run() calls.
    """
    try:
        text = server_py.read_text(encoding="utf-8")
        # --port 8005
        match = re.search(r"--port\s+(\d+)", text)
        if match:
            return int(match.group(1))
        # port=8005 or port = 8005
        match = re.search(r"port\s*=\s*(\d+)", text)
        if match:
            return int(match.group(1))
    except OSError:
        pass
    return 8000


def _get_description(readme: Path) -> str:
    """Get first non-empty, non-heading line from README.md."""
    try:
        for line in readme.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return _truncate(stripped)
    except OSError:
        pass
    return ""


def _get_script_description(script: Path) -> str:
    """Get module docstring first line from a Python script."""
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"))
        docstring = ast.get_docstring(tree)
        if docstring:
            first_line = docstring.strip().splitlines()[0].strip()
            # Remove trailing period/dash artifacts
            first_line = first_line.rstrip(" -.")
            return _truncate(first_line)
    except (OSError, SyntaxError):
        pass
    return ""


def _truncate(text: str, max_len: int = 55) -> str:
    """Truncate text for CLI display."""
    text = _console_safe(text)
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _console_safe(text: str) -> str:
    """Return text that can be written to the active console encoding."""
    text = (
        text.replace("\u2192", "->")
        .replace("\u2014", "--")
        .replace("\u2013", "-")
        .replace("\u2026", "...")
    )
    encoding = getattr(console.file, "encoding", None) or sys.getdefaultencoding()
    return text.encode(encoding, errors="replace").decode(encoding)


def _wait_for_port(port: int, timeout: int = DEFAULT_PORT_WAIT_TIMEOUT_S) -> bool:
    """Wait until a port is accepting connections."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _wait_for_backend_health(port: int, timeout: int = DEFAULT_HEALTH_WAIT_TIMEOUT_S) -> bool:
    """Wait until the backend app has completed startup and answers /health."""
    url = f"http://127.0.0.1:{port}/health"
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= response.status < 300:
                    return True
        except (OSError, urllib.error.URLError):
            time.sleep(0.5)
    return False


def _as_posix_path(path: Path) -> str:
    """Return a resolved path suitable for Docker volume specs."""
    return path.resolve().as_posix()


def _ensure_dir(path: Path) -> Path:
    """Create a demo runtime directory and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def _mcp_example_root(name: str) -> Path:
    """Return the root directory for a standalone MCP example."""
    return _find_project_root() / "mcp" / name


def _general_chat_mcp_env(variant: str, demo_dir: Path) -> dict[str, str]:
    """Build environment overrides for dedicated General Chat MCP demo variants."""
    root = _find_project_root()
    uploads_dir = _ensure_dir(demo_dir / "uploads")
    downloads_dir = _ensure_dir(demo_dir / "downloads")

    common = {
        "GENERAL_CHAT_MCP_ENABLED": "1",
        "GENERAL_CHAT_MCP_MODE": "external",
        "GENERAL_CHAT_MCP_REGISTRY_ENABLED": "0",
    }

    if variant == "dashboard-generator":
        dashboard_mcp_root = root / "mcp" / "dashboard-generator-mcp"
        aggregate_mcp_root = root / "mcp" / "aggregate-data-mcp"
        dashboard_state_dir = _ensure_dir(demo_dir / ".openbench")
        return {
            **common,
            "GENERAL_CHAT_MCP_CONFIG": "mcp/dashboard-generator-stdio.yaml",
            "GENERAL_CHAT_MCP_APPROVED_TOOLS": (
                "aggregate_data.extract_metadata,"
                "aggregate_data.aggregate_data,"
                "dashboard_generator.generate_dashboard"
            ),
            "GENERAL_CHAT_DASHBOARD_SKILL_ENABLED": "0",
            "OPENBENCH_EXPORT_DIR": str(downloads_dir.resolve()),
            "OPENBENCH_EXPORT_URL_BASE": "/downloads",
            "OPENBENCH_DASHBOARD_STATE_PATH": str(
                (dashboard_state_dir / "dashboard_generator_state.json").resolve()
            ),
            "DASHBOARD_GENERATOR_MCP_PYTHON": sys.executable,
            "AGGREGATE_DATA_MCP_PYTHON": sys.executable,
            "DASHBOARD_RENDER_ADAPTER": os.getenv("DASHBOARD_RENDER_ADAPTER", "default"),
            "DASHBOARD_GENERATOR_MCP_PYTHONPATH": os.pathsep.join(
                [str((root / "src").resolve()), str(dashboard_mcp_root.resolve())]
            ),
            "AGGREGATE_DATA_MCP_PYTHONPATH": os.pathsep.join(
                [str((root / "src").resolve()), str(aggregate_mcp_root.resolve())]
            ),
        }

    if variant == "image-search":
        image_search_root = _mcp_example_root("image-search-mcp")
        data_dir = _ensure_dir(image_search_root / "data")
        models_dir = _ensure_dir(image_search_root / "models")
        previews_dir = _ensure_dir(data_dir / "previews")
        hf_cache_dir = _ensure_dir(Path.home() / ".cache" / "huggingface")
        token_path = hf_cache_dir / "token"
        if not token_path.exists():
            console.print(
                "[yellow]Warning:[/yellow] Hugging Face token not found at "
                f"{token_path}. Run 'hf auth login' and accept DINOv3 access if live "
                "indexing fails."
            )
        return {
            **common,
            "GENERAL_CHAT_MCP_CONFIG": "mcp/image-search-docker.yaml",
            "GENERAL_CHAT_MCP_APPROVED_TOOLS": (
                "image_search.list_index_stats,image_search.search_similar_images"
            ),
            "IMAGE_SEARCH_MCP_DATA_PATH": _as_posix_path(data_dir),
            "IMAGE_SEARCH_MCP_MODELS_PATH": _as_posix_path(models_dir),
            "IMAGE_SEARCH_MCP_UPLOADS_PATH": _as_posix_path(uploads_dir),
            "IMAGE_SEARCH_MCP_HF_CACHE_PATH": _as_posix_path(hf_cache_dir),
            "GENERAL_CHAT_IMAGE_SEARCH_PREVIEW_DIR": str(previews_dir.resolve()),
        }

    if variant == "sam-segmentation":
        debug_dir = _ensure_dir(uploads_dir / "_sam_debug")
        return {
            **common,
            "GENERAL_CHAT_MCP_CONFIG": "mcp/sam-segmentation-docker.yaml",
            "GENERAL_CHAT_MCP_APPROVED_TOOLS": "sam_segmentation.count_objects_with_sam3",
            "SAM_SEGMENTATION_MCP_UPLOADS_PATH": _as_posix_path(uploads_dir),
            "SAM_SEGMENTATION_MCP_DEBUG_PATH": _as_posix_path(debug_dir),
        }

    raise click.ClickException(f"Unknown General Chat MCP demo variant: {variant}")


def _general_chat_plain_env() -> dict[str, str]:
    """Build environment overrides for the unified-MCP General Chat demo."""
    return {
        "GENERAL_CHAT_MCP_ENABLED": "0",
        "GENERAL_CHAT_MCP_REGISTRY_ENABLED": "1",
    }


def _command_available(*names: str) -> bool:
    """Return True when any command name resolves on PATH."""
    return any(shutil.which(name) for name in names)


def _docker_image_inspect_error(image: str) -> str | None:
    """Return a short Docker inspect error when an expected local image is unavailable."""
    docker = shutil.which("docker") or shutil.which("docker.exe")
    if not docker:
        return "docker command was not found on PATH"
    try:
        result = subprocess.run(
            [docker, "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "docker image inspect timed out"
    except OSError as exc:
        return str(exc)
    if result.returncode == 0:
        return None
    details = (result.stderr or result.stdout or "").strip()
    return details or f"docker image inspect exited with status {result.returncode}"


def _general_chat_all_mcp_env(
    demo_dir: Path,
    *,
    seed_registry: bool = True,
) -> dict[str, str]:
    """Build environment overrides and seed registry state for all-MCP General Chat."""
    root = _find_project_root()
    uploads_dir = _ensure_dir(demo_dir / "uploads")
    downloads_dir = _ensure_dir(demo_dir / "downloads")
    storage_root = _ensure_dir(demo_dir / ".openbench" / "all-mcp")
    # Same dir CustomFunctionStore uses (it honors CUSTOM_FN_DATA_PATH), so the
    # Functions panel writes and the custom_function MCP mount stay in sync.
    custom_fn_dir = _ensure_dir(storage_root / "custom-functions")
    sandbox_dir = _ensure_dir(demo_dir / "mcp-sandbox")
    sam_debug_dir = _ensure_dir(uploads_dir / "_sam_debug")

    image_search_root = _mcp_example_root("image-search-mcp")
    image_data_dir = _ensure_dir(image_search_root / "data")
    image_models_dir = _ensure_dir(image_search_root / "models")
    image_previews_dir = _ensure_dir(image_data_dir / "previews")
    hf_cache_dir = _ensure_dir(Path.home() / ".cache" / "huggingface")

    env = {
        "GENERAL_CHAT_MCP_ENABLED": "0",
        "GENERAL_CHAT_MCP_REGISTRY_ENABLED": "1",
        "GENERAL_CHAT_STORAGE_ROOT": str(storage_root.resolve()),
        "GENERAL_CHAT_UPLOAD_DIR": str(uploads_dir.resolve()),
        "GENERAL_CHAT_DOWNLOAD_DIR": str(downloads_dir.resolve()),
        "OPENBENCH_EXPORT_DIR": str(downloads_dir.resolve()),
        "OPENBENCH_EXPORT_URL_BASE": "/downloads",
        "DASHBOARD_GENERATOR_MCP_PYTHON": sys.executable,
        "GENERAL_CHAT_MCP_SANDBOX": str(sandbox_dir.resolve()),
        "DASHBOARD_GENERATOR_MCP_PYTHONPATH": os.pathsep.join(
            [
                str((root / "src").resolve()),
                str((root / "mcp" / "dashboard-generator-mcp").resolve()),
            ]
        ),
        "DASHBOARD_RENDER_ADAPTER": os.getenv("DASHBOARD_RENDER_ADAPTER", "default"),
        "GENERAL_CHAT_IMAGE_SEARCH_PREVIEW_DIR": str(image_previews_dir.resolve()),
        "IMAGE_SEARCH_MCP_DATA_PATH": _as_posix_path(image_data_dir),
        "IMAGE_SEARCH_MCP_MODELS_PATH": _as_posix_path(image_models_dir),
        "IMAGE_SEARCH_MCP_UPLOADS_PATH": _as_posix_path(uploads_dir),
        "IMAGE_SEARCH_MCP_HF_CACHE_PATH": _as_posix_path(hf_cache_dir),
        "SAM_SEGMENTATION_MCP_UPLOADS_PATH": _as_posix_path(uploads_dir),
        "SAM_SEGMENTATION_MCP_DEBUG_PATH": _as_posix_path(sam_debug_dir),
        "CUSTOM_FN_DATA_PATH": _as_posix_path(custom_fn_dir),
        "GENERIC_API_USERNAME": os.getenv("GENERIC_API_USERNAME", ""),
        "GENERIC_API_PASSWORD": os.getenv("GENERIC_API_PASSWORD", ""),
        "GENERIC_API_TIMEOUT_SECONDS": os.getenv("GENERIC_API_TIMEOUT_SECONDS", "30"),
    }

    token_path = hf_cache_dir / "token"
    if not token_path.exists():
        console.print(
            "[yellow]Warning:[/yellow] Hugging Face token not found at "
            f"{token_path}. DINOv3 image search may fail until you run 'hf auth login' "
            "and accept gated model access."
        )
    if not _command_available("docker", "docker.exe"):
        console.print(
            "[yellow]Warning:[/yellow] Docker was not found on PATH. Docker-backed MCP "
            "servers such as generic_api, image_search, sam_segmentation, and Docker "
            "MCP Gateway will report connection errors until Docker is available."
        )
    else:
        generic_api_error = _docker_image_inspect_error("openbench/generic-api-mcp:cpu")
        if generic_api_error:
            console.print(
                "[yellow]Warning:[/yellow] Docker image openbench/generic-api-mcp:cpu "
                "is not available or Docker API access failed. generic_api may fail "
                "with 'Connection closed'. Build it with: docker compose -f "
                "mcp\\generic-api-mcp\\docker-compose.yml --profile cpu build. "
                f"Details: {generic_api_error}"
            )
        image_search_error = _docker_image_inspect_error("openbench/image-search-mcp:cpu")
        if image_search_error:
            console.print(
                "[yellow]Warning:[/yellow] Docker image openbench/image-search-mcp:cpu "
                "is not available or Docker API access failed. image_search may fail "
                "with 'Connection closed'. Build it with: docker compose -f "
                "mcp\\image-search-mcp\\docker-compose.yml --profile cpu build. "
                f"Details: {image_search_error}"
            )
        custom_fn_image = os.getenv("CUSTOM_FN_IMAGE", "").strip()
        if not custom_fn_image and not _docker_image_inspect_error(_CUSTOM_FN_LOCAL_IMAGE):
            custom_fn_image = _CUSTOM_FN_LOCAL_IMAGE
        if custom_fn_image:
            env["CUSTOM_FN_IMAGE"] = custom_fn_image
        else:
            console.print(
                f"[yellow]Warning:[/yellow] Docker image {_CUSTOM_FN_LOCAL_IMAGE} is not "
                "available and CUSTOM_FN_IMAGE is unset. custom_function will fall back "
                "to the private Artifact Registry image, which usually cannot be pulled "
                "locally. Build it with: docker build -t "
                f"{_CUSTOM_FN_LOCAL_IMAGE} mcp\\custom-function-mcp"
            )
    if not _command_available("npx", "npx.cmd"):
        console.print(
            "[yellow]Warning:[/yellow] npx was not found on PATH. The filesystem MCP "
            "server will report a connection error until Node.js/npm tooling is available."
        )

    if seed_registry:
        _seed_general_chat_all_mcp_registry(demo_dir, env)

    return env


def _seed_general_chat_all_mcp_registry(demo_dir: Path, env: dict[str, str]) -> None:
    """Seed General Chat's MCP registry with bundled configs and ToolHive workloads."""
    general_chat_src = demo_dir / "src"
    if str(general_chat_src) not in sys.path:
        sys.path.insert(0, str(general_chat_src))

    try:
        from general_chat.mcp_registry import MCPServerRegistryStore

        from openbench.mcp.config import MCPConfig
    except Exception as exc:
        console.print(
            "[yellow]Warning:[/yellow] Could not import General Chat MCP registry "
            f"helpers: {exc}"
        )
        return

    store = MCPServerRegistryStore(env["GENERAL_CHAT_STORAGE_ROOT"])
    config_dir = demo_dir / "mcp"
    previous_env = {key: os.environ.get(key) for key in env}
    seeded_names: list[str] = []

    os.environ.update(env)
    try:
        for filename in _GENERAL_CHAT_ALL_MCP_CONFIGS:
            config_path = config_dir / filename
            if not config_path.exists():
                console.print(
                    "[yellow]Warning:[/yellow] General Chat MCP config not found: "
                    f"{config_path}"
                )
                continue
            try:
                config = MCPConfig.from_file(config_path)
                client_config = config.client_config()
                store.import_client_config(client_config)
                seeded_names.extend(sorted(client_config.servers))
            except Exception as exc:
                console.print(
                    "[yellow]Warning:[/yellow] Could not seed MCP config "
                    f"{config_path.name}: {exc}"
                )
    finally:
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    try:
        workloads = _list_running_toolhive_workloads()
        if workloads:
            store.import_toolhive_workloads(workloads)
            seeded_names.extend(sorted(workload.name for workload in workloads))
        else:
            console.print(
                "[yellow]Warning:[/yellow] No running ToolHive workloads were found. "
                "Start workloads in ToolHive first if you want ToolHive tools in this run."
            )
    except Exception as exc:
        console.print(
            "[yellow]Warning:[/yellow] Could not import running ToolHive workloads: "
            f"{exc}"
        )

    store.list_payload()
    if seeded_names:
        console.print(
            "[green]Seeded MCP registry:[/green] " + ", ".join(sorted(set(seeded_names)))
        )


def _list_running_toolhive_workloads():
    """Return ToolHive workloads through the shared OpenBench ToolHive helper."""
    from openbench.mcp.toolhive import ToolHiveService

    return ToolHiveService().list_workloads()


def _discover_demos() -> list[dict]:
    """Discover all runnable demos: servers and scripts."""
    root = _find_project_root()
    examples_dir = root / "examples"
    demos = []

    if not examples_dir.is_dir():
        return demos

    # 1. Server demos: examples/*/server.py
    for server_py in sorted(examples_dir.glob("*/server.py")):
        demo_dir = server_py.parent
        name = demo_dir.name
        readme = demo_dir / "README.md"
        has_frontend = (demo_dir / "frontend" / "package.json").exists()

        demos.append(
            {
                "name": name,
                "type": "server",
                "dir": demo_dir,
                "script": None,
                "port": _detect_port(server_py),
                "description": _get_description(readme),
                "has_frontend": has_frontend,
            }
        )

        if name == "general-chat":
            for variant, variant_info in _GENERAL_CHAT_MCP_VARIANTS.items():
                demos.append(
                    {
                        "name": variant_info["name"],
                        "type": "server",
                        "dir": demo_dir,
                        "script": None,
                        "port": _detect_port(server_py),
                        "description": variant_info["description"],
                        "has_frontend": has_frontend,
                        "mcp_variant": variant,
                    }
                )
            demos.append(
                {
                    "name": _GENERAL_CHAT_ALL_MCP_NAME,
                    "type": "server",
                    "dir": demo_dir,
                    "script": None,
                    "port": _detect_port(server_py),
                    "description": "General Chat with all bundled MCP integrations",
                    "has_frontend": has_frontend,
                    "mcp_profile": "all",
                }
            )

    # 2. Script demos: examples/**/*_demo.py, *_workflow.py
    server_dirs = {d["dir"] for d in demos}
    for script in sorted(examples_dir.rglob("*.py")):
        # Skip non-demo scripts, __init__, node_modules
        if not any(script.name.endswith(s) for s in _SCRIPT_SUFFIXES):
            continue
        if any(part in _IGNORED_SCRIPT_PARTS for part in script.parts):
            continue
        # Skip scripts inside server demo dirs (they're part of the server demo)
        if script.parent in server_dirs:
            continue

        # Build name from relative path: intelligence/gemini_agent_demo.py -> intelligence/gemini-agent
        rel = script.relative_to(examples_dir)
        stem = rel.stem
        for suffix in ("_demo", "_workflow"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
        stem = stem.replace("_", "-")
        name = "/".join([*rel.parent.parts, stem])

        demos.append(
            {
                "name": name,
                "type": "script",
                "dir": script.parent,
                "script": script,
                "port": None,
                "description": _get_script_description(script),
                "has_frontend": False,
            }
        )

    return demos


@click.group()
def demo():
    """Discover and launch runnable demos."""


@demo.command("list")
def list_demos():
    """List available demos."""
    demos = _discover_demos()

    if not demos:
        console.print("\n[yellow]No demos found.[/yellow]\n")
        return

    servers = [d for d in demos if d["type"] == "server"]
    scripts = [d for d in demos if d["type"] == "script"]

    # Server demos
    if servers:
        table = Table(title="Server Demos")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Backend", justify="center", style="green")
        table.add_column("Frontend", justify="center", style="green")

        for d in servers:
            table.add_row(
                d["name"],
                d["description"],
                f":{d['port']}",
                ":5173" if d["has_frontend"] else "-",
            )

        console.print()
        console.print(table)

    # Script demos
    if scripts:
        table = Table(title="Script Demos")
        table.add_column("Name", style="cyan")
        table.add_column("Description")

        for d in scripts:
            table.add_row(d["name"], d["description"])

        console.print()
        console.print(table)

    console.print()
    console.print("[dim]Run:[/dim] openbench demo run <name>")
    console.print()


@demo.command("run")
@click.argument("name")
@click.option("--port", type=int, default=None, help="Override backend port")
@click.option("--no-frontend", is_flag=True, help="Backend only (skip frontend)")
@click.option("--no-install", is_flag=True, help="Skip pnpm install and auto-setup")
@click.option(
    "--all-mcp",
    is_flag=True,
    help="Run General Chat with all bundled MCP configs and running ToolHive workloads.",
)
def run_demo(name, port, no_frontend, no_install, all_mcp):
    """Run a demo by name.

    Examples:
        openbench demo run chat
        openbench demo run lca-checker --no-frontend
        openbench demo run intelligence/gemini-agent
    """
    demos = _discover_demos()
    demo_map = {d["name"]: d for d in demos}

    if name not in demo_map:
        raise click.ClickException(
            f"Demo '{name}' not found.\n\nAvailable:\n  " + "\n  ".join(sorted(demo_map.keys()))
        )

    info = demo_map[name]
    all_mcp_requested = all_mcp or info.get("mcp_profile") == "all"
    if all_mcp and info["name"] not in {"general-chat", _GENERAL_CHAT_ALL_MCP_NAME}:
        raise click.ClickException(
            "--all-mcp is only supported for 'general-chat'. "
            "Use: openbench demo run general-chat --all-mcp"
        )

    # Script demos -- just run the script
    if info["type"] == "script":
        _run_script(info)
        return

    # Server demos -- uvicorn + pnpm
    _run_server(info, port, no_frontend, no_install, all_mcp=all_mcp_requested)


def _run_script(info: dict):
    """Run a standalone script demo."""
    script = info["script"]
    console.print(f"\n[green]Running:[/green] {info['name']}")
    console.print(f"[dim]{script}[/dim]\n")

    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(info["dir"]),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        if result.returncode not in (0, None):
            console.print(f"\n[red]Script exited with code {result.returncode}.[/red]\n")
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]\n")


def _chat_ui_dist_stale(chat_ui_dir: Path, dist_entry: Path) -> bool:
    """True if any SDK source file is newer than the built dist entry.

    Without this, an existing ``dist/`` is reused even after the SDK source
    changed, so the frontend serves a stale build.
    """
    if not dist_entry.exists():
        return True
    dist_mtime = dist_entry.stat().st_mtime
    for sub in ("src", "styles"):
        source_dir = chat_ui_dir / sub
        if not source_dir.exists():
            continue
        for path in source_dir.rglob("*"):
            if path.is_file() and path.stat().st_mtime > dist_mtime:
                return True
    return False


def _ensure_chat_ui_built(root: Path) -> bool:
    """Build studio/chat-ui if dist/ is missing or stale. Returns True on success."""
    chat_ui_dir = root / "studio" / "chat-ui"
    dist_dir = chat_ui_dir / "dist"
    dist_entry = dist_dir / "index.js"

    built = dist_dir.exists() and any(dist_dir.iterdir())
    stale = _chat_ui_dist_stale(chat_ui_dir, dist_entry)
    if built and not stale:
        return True

    if not chat_ui_dir.exists():
        console.print("[red]Error:[/red] studio/chat-ui not found.")
        return False

    reason = "not built yet" if not built else "out of date"
    console.print(f"\n[yellow]@openbench/chat-ui {reason}.[/yellow] Building automatically...")

    pnpm_cmd = _resolve_pnpm_command()
    if not pnpm_cmd:
        console.print("[red]Error:[/red] pnpm not found (or not resolvable via corepack).")
        return False

    # Install deps only when missing (a rebuild on source change shouldn't reinstall).
    if not (chat_ui_dir / "node_modules").exists():
        console.print("[green]  pnpm install[/green] (studio/chat-ui)")
        result = subprocess.run(
            [*pnpm_cmd, "install"],
            cwd=str(chat_ui_dir),
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        if result.returncode != 0:
            console.print("[red]Error:[/red] pnpm install failed for studio/chat-ui.")
            return False

    # Build
    console.print("[green]  pnpm build[/green] (studio/chat-ui)")
    result = subprocess.run(
        [*pnpm_cmd, "build"],
        cwd=str(chat_ui_dir),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if result.returncode != 0:
        console.print("[red]Error:[/red] pnpm build failed for studio/chat-ui.")
        return False

    console.print("[green]  @openbench/chat-ui built successfully.[/green]\n")
    return True


def _ensure_python_deps(demo_dir: Path):
    """Install Python deps if example has pyproject.toml."""
    pyproject = demo_dir / "pyproject.toml"
    if not pyproject.exists():
        return

    # Check if already installed by looking for .egg-info
    egg_infos = list(demo_dir.glob("src/*.egg-info"))
    if not egg_infos:
        egg_infos = list(demo_dir.glob("*.egg-info"))

    # Quick check: if egg-info exists and has SOURCES.txt, skip
    if egg_infos and any((e / "SOURCES.txt").exists() for e in egg_infos):
        return

    console.print(f"\n[yellow]Installing Python deps:[/yellow] pip install -e {demo_dir.name}")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet"],
        cwd=str(demo_dir),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    if result.returncode != 0:
        console.print(
            f"[yellow]Warning:[/yellow] pip install -e . failed for {demo_dir.name}. "
            "Some imports may be missing."
        )
    else:
        console.print(f"[green]  {demo_dir.name} deps installed.[/green]\n")


def _run_server(
    info: dict,
    port: int | None,
    no_frontend: bool,
    no_install: bool,
    *,
    all_mcp: bool = False,
):
    """Run a server demo (uvicorn + optional frontend)."""
    demo_dir = info["dir"]
    backend_port = port or info["port"]
    has_frontend = info["has_frontend"] and not no_frontend

    pnpm_cmd = _resolve_pnpm_command()

    # Check pnpm if frontend needed
    if has_frontend and not pnpm_cmd:
        console.print(
            "[yellow]Warning:[/yellow] pnpm not found. "
            "Frontend won't start. Use --no-frontend to suppress this warning."
        )
        has_frontend = False

    # Auto-build chat-ui if frontend needed and dist/ missing
    if has_frontend and not no_install:
        root = _find_project_root()
        if not _ensure_chat_ui_built(root):
            console.print(
                "[yellow]Warning:[/yellow] chat-ui build failed. "
                "Frontend may not work. Use --no-frontend to skip."
            )

    # Auto-install Python deps if pyproject.toml exists
    if not no_install:
        _ensure_python_deps(demo_dir)

    processes: list[subprocess.Popen] = []

    def cleanup():
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=DEFAULT_PROC_WAIT_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                proc.kill()

    # Ensure Python subprocesses flush output immediately
    demo_env = {}
    if all_mcp:
        demo_env = _general_chat_all_mcp_env(demo_dir)
    elif info["name"] == "general-chat":
        demo_env = _general_chat_plain_env()
    elif info.get("mcp_variant"):
        demo_env = _general_chat_mcp_env(str(info["mcp_variant"]), demo_dir)
    env = {**os.environ, "PYTHONUNBUFFERED": "1", **demo_env}

    # Use the same Python that runs this CLI -- guaranteed to have deps installed
    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "server:app",
        "--port",
        str(backend_port),
        "--reload",
    ]
    # Watch only source code: reloading on the whole demo dir restarts the
    # server whenever runtime data is written under .openbench/ (e.g. saving
    # a custom function), killing in-flight requests.
    if (demo_dir / "src").is_dir():
        backend_cmd += ["--reload-dir", "src"]

    try:
        # Start backend
        console.print(
            f"\n[green]Starting backend:[/green] {' '.join(backend_cmd[2:])}"
        )
        backend = subprocess.Popen(
            backend_cmd,
            cwd=str(demo_dir),
            env=env,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        processes.append(backend)

        # Wait for backend to be ready before starting frontend
        if has_frontend:
            console.print(f"[dim]Waiting for backend health on :{backend_port}...[/dim]")
            if not _wait_for_backend_health(backend_port):
                console.print(
                    "[yellow]Warning:[/yellow] Backend health not ready after 30s, "
                    "starting frontend anyway."
                )

        # Start frontend
        frontend_started = False
        if has_frontend:
            frontend_dir = demo_dir / "frontend"
            if not frontend_dir.is_dir():
                console.print(
                    f"[yellow]Warning:[/yellow] Frontend directory not found: {frontend_dir}. "
                    "Running backend only."
                )
                has_frontend = False

            if has_frontend and not no_install:
                console.print("[green]Installing frontend dependencies:[/green] pnpm install")
                try:
                    install_result = subprocess.run(
                        [*(pnpm_cmd or ["pnpm"]), "install"],
                        cwd=str(frontend_dir),
                        stdout=sys.stdout,
                        stderr=sys.stderr,
                    )
                except FileNotFoundError as exc:
                    console.print(
                        "[yellow]Warning:[/yellow] Could not run pnpm install. "
                        "pnpm may be missing from PATH or frontend directory is unavailable. "
                        "Running backend only.\n"
                        f"  command: {' '.join([*(pnpm_cmd or ['pnpm']), 'install'])}\n"
                        f"  cwd: {frontend_dir}\n"
                        f"  details: {exc}"
                    )
                    has_frontend = False
                else:
                    if install_result.returncode != 0:
                        console.print(
                            "[red]Error:[/red] pnpm install failed (exit code "
                            f"{install_result.returncode}). Skipping frontend.\n"
                            f"  Try running manually: cd {frontend_dir} && pnpm install"
                        )
                        has_frontend = False

        if has_frontend:
            frontend_dir = demo_dir / "frontend"
            console.print("[green]Starting frontend:[/green] pnpm dev")
            frontend_env = {
                **os.environ,
                "VITE_BACKEND_URL": f"http://localhost:{backend_port}",
            }
            try:
                frontend = subprocess.Popen(
                    [*(pnpm_cmd or ["pnpm"]), "dev"],
                    cwd=str(frontend_dir),
                    env=frontend_env,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                )
            except FileNotFoundError as exc:
                console.print(
                    "[yellow]Warning:[/yellow] Could not start frontend with pnpm dev. "
                    "Running backend only.\n"
                    f"  command: {' '.join([*(pnpm_cmd or ['pnpm']), 'dev'])}\n"
                    f"  cwd: {frontend_dir}\n"
                    f"  details: {exc}"
                )
                frontend = None
            if frontend is None:
                has_frontend = False
            else:
                processes.append(frontend)
                # Brief health check -- give Vite a moment to crash or start
                time.sleep(2)
                if frontend.poll() is not None:
                    console.print(
                        f"[red]Error:[/red] Frontend exited immediately (code {frontend.returncode}). "
                        "Running backend only.\n"
                        f"  Try running manually: cd {frontend_dir} && pnpm dev"
                    )
                    processes.remove(frontend)
                else:
                    frontend_started = True

        # Print summary
        lines = [f"[cyan]Backend:[/cyan]  http://localhost:{backend_port}"]
        if frontend_started:
            lines.append(
                "[cyan]Frontend:[/cyan] http://localhost:5173 (check Vite output if port differs)"
            )
        lines.append("\nPress Ctrl+C to stop.")

        console.print()
        console.print(Panel("\n".join(lines), title=f"[bold]{info['name']}[/bold] demo running"))

        # Wait for Ctrl+C or any process to exit
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)

    except KeyboardInterrupt:
        console.print("\n[yellow]Shutting down...[/yellow]")
    finally:
        cleanup()
        console.print("[green]Done.[/green]\n")
