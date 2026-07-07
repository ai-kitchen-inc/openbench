"""Read-only store for user-defined functions.

Functions are written by the general-chat API (auth-gated) into a directory
this container mounts read-only at ``CUSTOM_FN_DIR`` (default
``/data/functions``). Each function is a pair:

    <name>.py     exactly one top-level ``def <name>(...)``
    <name>.json   {"name", "description", "created_at"}

Names are strict identifiers so they can never traverse paths or clash with
tool syntax.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")


def functions_dir() -> Path:
    return Path(os.getenv("CUSTOM_FN_DIR", "/data/functions"))


def validate_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not NAME_RE.match(cleaned):
        raise ValueError(
            f"invalid function name {name!r}: lowercase letters, digits, underscore; "
            "must start with a letter or underscore; max 64 chars"
        )
    return cleaned


def list_meta() -> list[dict[str, Any]]:
    """Metadata for every stored function, sorted by name."""
    root = functions_dir()
    if not root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for meta_path in sorted(root.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = str(meta.get("name") or meta_path.stem)
        if NAME_RE.match(name) and (root / f"{name}.py").is_file():
            result.append(meta)
    return result


def load(name: str) -> tuple[str, dict[str, Any]]:
    """(code, meta) for a stored function; raises FileNotFoundError/ValueError."""
    name = validate_name(name)
    root = functions_dir()
    code_path = root / f"{name}.py"
    if not code_path.is_file():
        raise FileNotFoundError(f"no such function: {name}")
    code = code_path.read_text(encoding="utf-8")
    meta: dict[str, Any] = {"name": name}
    meta_path = root / f"{name}.json"
    if meta_path.is_file():
        try:
            meta = {**json.loads(meta_path.read_text(encoding="utf-8")), "name": name}
        except (OSError, ValueError):
            pass
    return code, meta
