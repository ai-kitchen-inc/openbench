"""Host-side store + sandboxed test-runner for user-defined Python functions.

The Functions panel (auth-gated routes in app.py) writes function files here;
the `custom_function` MCP container mounts the same directory read-only and
executes them (see mcp/custom-function-mcp/). Storage contract:

    <root>/<name>.py     exactly one top-level ``def <name>(...)``
    <root>/<name>.json   {"name", "description", "created_at"}

``test_run`` spawns the same sandbox image as a one-shot container so the UI
"Test run" exercises exactly the path the agent uses.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")
MAX_CODE_BYTES = 64 * 1024

_DEFAULT_IMAGE = "us-central1-docker.pkg.dev/sss-poc1-corporate/openbench/custom-function-mcp:0.1.0"
_TEST_RUN_TIMEOUT_SECONDS = 40


class CustomFunctionError(ValueError):
    """Validation error surfaced to the UI as HTTP 400."""


class CustomFunctionStore:
    """CRUD for user functions + sandboxed one-shot test runs."""

    def __init__(self, storage_root: str) -> None:
        configured = os.getenv("CUSTOM_FN_DATA_PATH", "").strip()
        self.root = Path(configured) if configured else Path(storage_root) / "custom-functions"
        self.root.mkdir(parents=True, exist_ok=True)

    # -- validation -------------------------------------------------------

    @staticmethod
    def _validate_name(name: str) -> str:
        cleaned = (name or "").strip()
        if not NAME_RE.match(cleaned):
            raise CustomFunctionError(
                "invalid name: lowercase letters, digits, underscore; must start "
                "with a letter or underscore; max 64 chars"
            )
        return cleaned

    @staticmethod
    def _validate_code(name: str, code: str) -> None:
        if not code or not code.strip():
            raise CustomFunctionError("code is empty")
        if len(code.encode("utf-8")) > MAX_CODE_BYTES:
            raise CustomFunctionError(f"code exceeds {MAX_CODE_BYTES // 1024}KB limit")
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise CustomFunctionError(f"syntax error: {exc}") from exc
        functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if len(functions) != 1:
            raise CustomFunctionError("code must define exactly one top-level function")
        if functions[0].name != name:
            raise CustomFunctionError(
                f"the function must be named {name!r} (found {functions[0].name!r})"
            )

    # -- CRUD ---------------------------------------------------------------

    def save(self, name: str, code: str, description: str = "") -> dict[str, Any]:
        name = self._validate_name(name)
        self._validate_code(name, code)
        meta = {
            "name": name,
            "description": str(description or "")[:500],
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (self.root / f"{name}.py").write_text(code, encoding="utf-8")
        (self.root / f"{name}.json").write_text(json.dumps(meta), encoding="utf-8")
        return meta

    def list(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for meta_path in sorted(self.root.glob("*.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            name = str(meta.get("name") or meta_path.stem)
            if NAME_RE.match(name) and (self.root / f"{name}.py").is_file():
                meta["code"] = (self.root / f"{name}.py").read_text(encoding="utf-8")
                result.append(meta)
        return result

    def names(self) -> set[str]:
        """Return valid saved function names without loading function code."""
        names: set[str] = set()
        for meta_path in sorted(self.root.glob("*.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            name = str(meta.get("name") or meta_path.stem)
            if NAME_RE.match(name) and (self.root / f"{name}.py").is_file():
                names.add(name)
        return names

    def exists(self, name: str) -> bool:
        """Return whether a valid function definition is already saved."""
        name = self._validate_name(name)
        return name in self.names()

    def delete(self, name: str) -> bool:
        name = self._validate_name(name)
        existed = False
        for suffix in (".py", ".json"):
            path = self.root / f"{name}{suffix}"
            if path.is_file():
                path.unlink()
                existed = True
        return existed

    # -- sandboxed test run ---------------------------------------------------

    def test_run(self, name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Run a function once in the sandbox image (same path the agent uses)."""
        name = self._validate_name(name)
        if not (self.root / f"{name}.py").is_file():
            raise FileNotFoundError(f"no such function: {name}")
        image = os.getenv("CUSTOM_FN_IMAGE", _DEFAULT_IMAGE)
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{self.root}:/data/functions:ro",
            "--network", "none",
            "--memory", "512m",
            "--cpus", "1",
            "--pids-limit", "128",
            image,
            "python", "-m", "app.runner", name, json.dumps(kwargs),
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_TEST_RUN_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"test run timed out after {_TEST_RUN_TIMEOUT_SECONDS}s"}
        except FileNotFoundError:
            return {"ok": False, "error": "docker is not available in this environment"}

        stdout = (proc.stdout or "").strip()
        last_line = stdout.splitlines()[-1] if stdout else ""
        try:
            return json.loads(last_line)
        except (ValueError, IndexError):
            return {
                "ok": False,
                "error": f"sandbox produced no JSON (exit {proc.returncode})",
                "stderr": (proc.stderr or "")[-2000:],
            }
