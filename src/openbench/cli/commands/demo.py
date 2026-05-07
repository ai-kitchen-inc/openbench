"""Demo management CLI commands."""

import ast
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# Script suffixes to discover as runnable demos
_SCRIPT_SUFFIXES = ("_demo.py", "_workflow.py")


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


def _wait_for_port(port: int, timeout: int = 15) -> bool:
    """Wait until a port is accepting connections."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


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

    # 2. Script demos: examples/**/*_demo.py, *_workflow.py
    server_dirs = {d["dir"] for d in demos}
    for script in sorted(examples_dir.rglob("*.py")):
        # Skip non-demo scripts, __init__, node_modules
        if not any(script.name.endswith(s) for s in _SCRIPT_SUFFIXES):
            continue
        if "node_modules" in str(script) or "__pycache__" in str(script):
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
def run_demo(name, port, no_frontend, no_install):
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

    # Script demos -- just run the script
    if info["type"] == "script":
        _run_script(info)
        return

    # Server demos -- uvicorn + pnpm
    _run_server(info, port, no_frontend, no_install)


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


def _ensure_chat_ui_built(root: Path) -> bool:
    """Build studio/chat-ui if dist/ doesn't exist. Returns True on success."""
    chat_ui_dir = root / "studio" / "chat-ui"
    dist_dir = chat_ui_dir / "dist"

    if dist_dir.exists() and any(dist_dir.iterdir()):
        return True

    if not chat_ui_dir.exists():
        console.print("[red]Error:[/red] studio/chat-ui not found.")
        return False

    console.print("\n[yellow]@openbench/chat-ui not built yet.[/yellow] Building automatically...")

    pnpm_cmd = _resolve_pnpm_command()
    if not pnpm_cmd:
        console.print("[red]Error:[/red] pnpm not found (or not resolvable via corepack).")
        return False

    # Install deps
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


def _run_server(info: dict, port: int | None, no_frontend: bool, no_install: bool):
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
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    # Ensure Python subprocesses flush output immediately
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

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

    try:
        # Start backend
        console.print(
            f"\n[green]Starting backend:[/green] uvicorn server:app --port {backend_port} --reload"
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
            console.print(f"[dim]Waiting for backend on :{backend_port}...[/dim]")
            if not _wait_for_port(backend_port):
                console.print(
                    "[yellow]Warning:[/yellow] Backend not ready after 15s, starting frontend anyway."
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
            try:
                frontend = subprocess.Popen(
                    [*(pnpm_cmd or ["pnpm"]), "dev"],
                    cwd=str(frontend_dir),
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
