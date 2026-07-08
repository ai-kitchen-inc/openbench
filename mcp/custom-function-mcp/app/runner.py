"""One-shot runner: execute a stored user function and print a JSON result.

    python -m app.runner <name> [<kwargs-json>]

Runs inside the sandbox container (non-root, no network, resource-capped) —
this process IS the untrusted context, the container is the isolation
boundary. Prints exactly one JSON line to stdout:

    {"ok": true,  "result": ..., "stdout": "..."}
    {"ok": false, "error": "...", "stdout": "..."}

Exit code 0 on success, 1 on failure — so callers can branch without parsing.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from typing import Any

from app.store import load, validate_name


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def run(name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Load <name>.py, exec it in a fresh namespace, call the function."""
    name = validate_name(name)
    code, _meta = load(name)

    namespace: dict[str, Any] = {"__name__": "__custom_fn__"}
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        exec(compile(code, f"{name}.py", "exec"), namespace)  # noqa: S102 - sandboxed by design
        fn = namespace.get(name)
        if not callable(fn):
            raise ValueError(f"{name}.py must define a callable named {name!r}")
        result = fn(**kwargs)
    return {"ok": True, "result": _jsonable(result), "stdout": captured.getvalue()}


def main(argv: list[str]) -> int:
    if not argv:
        print(json.dumps({"ok": False, "error": "usage: python -m app.runner <name> [<kwargs-json>]"}))
        return 1
    name = argv[0]
    try:
        kwargs = json.loads(argv[1]) if len(argv) > 1 and argv[1].strip() else {}
        if not isinstance(kwargs, dict):
            raise ValueError("kwargs must be a JSON object")
        payload = run(name, kwargs)
    except Exception as exc:  # noqa: BLE001 - report every failure as JSON
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
