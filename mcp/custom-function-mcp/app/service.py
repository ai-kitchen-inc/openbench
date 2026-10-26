"""Service layer: list/describe stored functions, run one in a subprocess.

``run_function`` shells out to ``python -m app.runner`` so user code gets a
fresh interpreter and a hard wall-clock timeout (``CUSTOM_FN_TIMEOUT_SECONDS``,
default 20). The surrounding container (non-root, ``--network none``, memory/
cpu/pids caps) is the real isolation boundary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.store import list_meta, load, validate_name

# Package root (contains the `app` package) so `-m app.runner` resolves
# regardless of the caller's working directory.
_PKG_ROOT = Path(__file__).resolve().parents[1]


def _timeout_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("CUSTOM_FN_TIMEOUT_SECONDS", "20")))
    except (TypeError, ValueError):
        return 20.0


def list_functions() -> dict[str, Any]:
    return {"functions": list_meta()}


def describe_function(name: str) -> dict[str, Any]:
    code, meta = load(name)
    return {"meta": meta, "code": code}


def run_function(name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    name = validate_name(name)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.runner", name, json.dumps(kwargs)],
            capture_output=True,
            text=True,
            timeout=_timeout_seconds(),
            cwd=_PKG_ROOT,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"function {name!r} timed out after {_timeout_seconds():g}s"}

    stdout = (proc.stdout or "").strip()
    # The runner prints exactly one JSON line; take the last line defensively.
    last_line = stdout.splitlines()[-1] if stdout else ""
    try:
        return json.loads(last_line)
    except (ValueError, IndexError):
        return {
            "ok": False,
            "error": f"runner produced no JSON (exit {proc.returncode})",
            "stderr": (proc.stderr or "")[-2000:],
        }
