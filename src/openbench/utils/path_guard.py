"""Filesystem jail for tool arguments that name a local file.

Tool arguments are chosen by a language model, which in turn reads
attacker-influenced text (uploads, web pages, shared sources). A tool that
opens whatever path it is handed lets a prompt injection read server files
such as ``/proc/1/environ`` or another tenant's uploads.

The jail is opt-in so the SDK keeps working as a plain library: when
``OPENBENCH_TOOL_FILE_ROOTS`` is unset, paths pass through unchanged. A
server that exposes tools to untrusted input sets it to the directories
tools may touch (``os.pathsep``-separated), and anything that resolves
outside them is refused.
"""

from __future__ import annotations

import os
from pathlib import Path

TOOL_FILE_ROOTS_ENV = "OPENBENCH_TOOL_FILE_ROOTS"


class ToolPathError(ValueError):
    """Raised when a tool path resolves outside the allowed directories."""


def tool_file_roots() -> list[Path]:
    """Return the configured allowed roots, resolved; empty when unrestricted."""
    raw = os.environ.get(TOOL_FILE_ROOTS_ENV, "")
    roots: list[Path] = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            roots.append(Path(part).expanduser().resolve())
    return roots


def is_within_roots(path: str | os.PathLike[str], roots: list[Path]) -> bool:
    """Return True when ``path`` resolves inside one of ``roots``.

    Resolution follows symlinks and collapses ``..`` first, so neither can
    be used to escape.
    """
    candidate = Path(path).expanduser().resolve()
    for root in roots:
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        return True
    return False


def resolve_tool_path(
    path: str | os.PathLike[str], *, roots: list[Path] | None = None
) -> Path:
    """Return ``path`` as a ``Path``, enforcing the tool file jail.

    Args:
        path: Path supplied to a tool.
        roots: Allowed roots; defaults to :func:`tool_file_roots`.

    Returns:
        The path unchanged when no roots are configured, otherwise the
        fully resolved path.

    Raises:
        ToolPathError: Roots are configured and the path is outside them.
    """
    allowed = tool_file_roots() if roots is None else roots
    if not allowed:
        return Path(path)
    if not is_within_roots(path, allowed):
        raise ToolPathError("Path is outside the directories this tool may access.")
    return Path(path).expanduser().resolve()
