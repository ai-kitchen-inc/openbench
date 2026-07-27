"""Tools for the export-markdown SDK skill.

Writes markdown text to a downloadable ``.md`` file and returns a file
render item in the shape expected by
``openbench.chat.renderers.file.FileRenderer``:

    {"name": "<filename>", "url": "<path or url>", "size": <bytes>?, ...}

Two output paths, mirroring the export-excel skill:

1. **Bound store (preferred)** — the host app calls
   ``skill.bind(output_store=..., output_url_base=...)`` during agent
   construction; bytes route through ``FileStore.store(...)``.
2. **Legacy env-var fallback** — write to ``OPENBENCH_EXPORT_DIR`` and
   expose at ``OPENBENCH_EXPORT_URL_BASE/<filename>``.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openbench.chat.files import FileStore

__all__ = [
    "generate_markdown",
    "GENERATE_MARKDOWN_SCHEMA",
]

_MD_MIME = "text/markdown"


_output_store: FileStore | None = None
_output_url_base: str | None = None


def bind(
    output_store: FileStore | None = None,
    output_url_base: str | None = None,
    **_: object,
) -> None:
    """Inject the FileStore the agent was configured with.

    Called by :meth:`SkillRegistry.bind` during :class:`BaseAgent`
    construction. Extra kwargs are ignored so future bindings can
    layer on without breaking this skill.
    """
    global _output_store, _output_url_base
    _output_store = output_store
    _output_url_base = output_url_base


def _error(message: str) -> dict[str, Any]:
    return {"error": message}


def _resolve_output(filename: str) -> Path:
    """Absolute output path (bound store → tempdir; else export dir)."""
    if _output_store is not None:
        import tempfile

        target_dir: str | None = tempfile.gettempdir()
    else:
        target_dir = os.environ.get("OPENBENCH_EXPORT_DIR") or None
    stem = Path(Path(filename).name).stem or "document"
    unique_name = f"{stem}-{uuid.uuid4().hex[:8]}.md"
    p = Path(target_dir) / unique_name if target_dir else Path(unique_name)
    p = p.resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _public_url(path: Path) -> str:
    base = os.environ.get("OPENBENCH_EXPORT_URL_BASE")
    if not base:
        return path.as_posix()
    from openbench.utils.download_tokens import sign_download_url

    return sign_download_url(f"{base.rstrip('/')}/{path.name}")


def _push_to_render_queue(item: dict[str, Any]) -> None:
    """Push onto ``openbench.chat.render_queue`` if available (no-op otherwise)."""
    try:
        from openbench.chat.render_queue import push as _push
    except Exception:
        return
    with contextlib.suppress(Exception):
        _push(item)


def _persist_via_bound_store(on_disk_path: Path) -> dict[str, Any]:
    assert _output_store is not None
    try:
        content = on_disk_path.read_bytes()
    except OSError as exc:
        return _error(f"Failed to read markdown bytes: {exc}")
    with contextlib.suppress(OSError):
        on_disk_path.unlink()

    stored = _output_store.store(on_disk_path.name, content, _MD_MIME)
    if stored.web_view_link:
        url = stored.web_view_link
    elif _output_url_base:
        url = f"{_output_url_base.rstrip('/')}/{stored.id}/{stored.name}"
    else:
        url = stored.path
    item: dict[str, Any] = {
        "name": stored.name,
        "url": url,
        "mimeType": stored.mime_type or _MD_MIME,
        "size": stored.size_bytes,
    }
    if stored.web_view_link:
        item["external"] = True
    return item


def generate_markdown(
    content: str,
    filename: str,
    title: str | None = None,
) -> dict[str, Any]:
    """Write text content to a downloadable Markdown (.md) file.

    Args:
        content: Markdown body text.
        filename: Output filename (``.md`` extension enforced).
        title: Optional title prepended as an H1 when the content does
            not already start with a heading.

    Returns:
        A file render item ``{"name", "url", "mimeType", "size"?}``.
        On failure returns ``{"error": "..."}``.
    """
    if not isinstance(content, str) or not content.strip():
        return _error("`content` must be a non-empty string")

    body = content.strip()
    if title and title.strip() and not body.lstrip().startswith("#"):
        body = f"# {title.strip()}\n\n{body}"

    out_path = _resolve_output(filename)
    try:
        out_path.write_text(body + "\n", encoding="utf-8")
    except OSError as exc:
        return _error(f"Failed to write markdown file: {exc}")

    if _output_store is not None:
        item = _persist_via_bound_store(out_path)
    else:
        try:
            size = out_path.stat().st_size
        except OSError:
            size = None
        item = {
            "name": out_path.name,
            "url": _public_url(out_path),
            "mimeType": _MD_MIME,
        }
        if size is not None:
            item["size"] = size
    _push_to_render_queue(item)
    return item


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


GENERATE_MARKDOWN_SCHEMA = _schema(
    "generate_markdown",
    "Write text content to a downloadable Markdown (.md) file. Returns a "
    "file render item the chat UI renders as a download card. Use when the "
    "user asks for a markdown/text file deliverable, in any language — "
    "English 'save as markdown', 'download as .md', 'export these notes'; "
    "Indonesian 'simpan sebagai markdown', 'unduh file md', 'buatkan "
    "catatan dalam berkas'. For PDF use generate_pdf, for spreadsheets use "
    "export_to_excel.",
    {
        "content": {"type": "string", "description": "Markdown body text."},
        "filename": {
            "type": "string",
            "description": "Output filename (.md extension added if missing).",
        },
        "title": {
            "type": "string",
            "description": "Optional H1 title prepended when content lacks a heading.",
        },
    },
    ["content", "filename"],
)
