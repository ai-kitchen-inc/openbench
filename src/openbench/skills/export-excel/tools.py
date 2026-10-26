"""Tools for the export-excel SDK skill.

Writes records to .xlsx files and returns a file render item in the
shape expected by ``openbench.chat.renderers.file.FileRenderer``:

    {"name": "<filename>", "url": "<path or url>", "size": <bytes>?, ...}

``pandas`` and ``openpyxl`` are imported lazily so that loading this
skill does not require the ``[data]`` extra at install time — the
failure only surfaces when the agent actually calls one of the tools.

Two output paths:

1. **Bound store (preferred)** — the host app calls
   ``skill.bind(output_store=..., output_url_base=...)`` during agent
   construction. Exports go through ``FileStore.store(...)``, which
   routes to the user's Drive ``OpenBench/downloads/`` for
   Drive-connected users or to disk for local deployments. The
   returned ``url`` points at ``<output_url_base>/<id>/<name>`` — an
   HTTP route the server resolves via ``output_store.get_local_path``.

2. **Legacy env-var fallback** — when no store is bound, write
   directly to ``OPENBENCH_EXPORT_DIR`` and expose at
   ``OPENBENCH_EXPORT_URL_BASE/<filename>``. Preserves the original
   behaviour for hosts that haven't migrated yet.
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
    "export_to_excel",
    "export_multi_sheet_excel",
    "EXPORT_TO_EXCEL_SCHEMA",
    "EXPORT_MULTI_SHEET_EXCEL_SCHEMA",
]


# ---------------------------------------------------------------------------
# Bound output store (optional — populated by skill.bind() at agent build)
# ---------------------------------------------------------------------------


_output_store: FileStore | None = None
_output_url_base: str | None = None


def bind(
    output_store: FileStore | None = None,
    output_url_base: str | None = None,
    **_: object,
) -> None:
    """Inject the FileStore the agent was configured with.

    Called by :meth:`SkillRegistry.bind` during :class:`BaseAgent`
    construction. Extra kwargs are ignored so future bindings (e.g.
    ``scratchpad=``) can layer on without breaking this skill.

    Args:
        output_store: Optional file store for export artifacts. When
            provided, supersedes the :envvar:`OPENBENCH_EXPORT_DIR`
            flow — exports route through the store's
            :meth:`~openbench.chat.files.FileStore.store`.
        output_url_base: URL prefix the frontend uses to download stored
            files. Joined with the :class:`StoredFile` id to build the
            download URL.
    """
    global _output_store, _output_url_base
    _output_store = output_store
    _output_url_base = output_url_base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error(message: str) -> dict[str, Any]:
    return {"error": message}


def _default_output_dir() -> str | None:
    """Return the configured default output directory.

    Read from env at call time so tests (and hot reloads) pick up
    changes without reimporting the module.
    """
    return os.environ.get("OPENBENCH_EXPORT_DIR") or None


def _url_base() -> str | None:
    """Return the configured HTTP URL base for exported files."""
    base = os.environ.get("OPENBENCH_EXPORT_URL_BASE")
    if not base:
        return None
    # Strip trailing slash so joins don't double up.
    return base.rstrip("/")


def _unique_filename(filename: str) -> str:
    """Add a short unique suffix to avoid overwriting previous exports.

    Multiple turns in the same chat may export files with the same
    ``filename`` parameter (e.g. ``"report.xlsx"``). Without a unique
    suffix the second export clobbers the first, which breaks the
    download link in older messages. Insert an 8-char uuid before
    the extension so every export gets its own file.
    """
    p = Path(filename).name  # drop any directory components
    stem = Path(p).stem
    suffix = Path(p).suffix or ".xlsx"
    return f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"


def _resolve_output(filename: str, output_dir: str | None) -> Path:
    """Return an absolute path for the output file.

    Precedence for the directory:
    1. Explicit ``output_dir`` argument (tool caller / tests)
    2. If a FileStore is bound: an OS tempdir — the file is a
       throwaway; bytes get shipped into the store and the local
       copy unlinked right after.
    3. ``OPENBENCH_EXPORT_DIR`` environment variable
    4. Process CWD (legacy fallback — usually wrong in production)

    Parent directories are created on demand. The filename always
    gets a unique suffix so concurrent or repeated exports don't
    collide.
    """
    if output_dir is None and _output_store is not None:
        import tempfile

        target_dir: str | None = tempfile.gettempdir()
    else:
        target_dir = output_dir or _default_output_dir()
    unique_name = _unique_filename(filename)
    p = Path(target_dir) / unique_name if target_dir else Path(unique_name)
    p = p.resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() != ".xlsx":
        p = p.with_suffix(".xlsx")
    return p


def _public_url(path: Path) -> str:
    """Return a URL the frontend can use to download the file.

    When ``OPENBENCH_EXPORT_URL_BASE`` is set, join it with the
    filename so the server's static mount (e.g. ``/downloads``) can
    serve it over HTTP. Otherwise fall back to the absolute
    filesystem path, which is only useful for local / CLI callers.
    """
    base = _url_base()
    if base is None:
        return path.as_posix()
    from openbench.utils.download_tokens import sign_download_url

    return sign_download_url(f"{base}/{path.name}")


def _file_item(path: Path, sheets: list[str]) -> dict[str, Any]:
    """Build a file render item consumable by FileRenderer."""
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    item: dict[str, Any] = {
        "name": path.name,
        "url": _public_url(path),
        "sheets": sheets,
        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    if size is not None:
        item["size"] = size
    return item


def _XLSX_MIME() -> str:
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _persist_via_bound_store(
    filename: str, on_disk_path: Path, sheets: list[str]
) -> dict[str, Any]:
    """Read the workbook bytes, push through the bound output store,
    and return a render item pointing at the store's HTTP URL.

    Cleans up the local tempfile after reading so we don't double-
    store. If :data:`_output_store` isn't bound, the caller should
    fall through to the legacy flow.
    """
    assert _output_store is not None

    try:
        content = on_disk_path.read_bytes()
    except OSError as exc:
        return _error(f"Failed to read workbook bytes: {exc}")
    # Clean up — the bytes live in the store now (plus its cache if
    # Drive-backed).
    with contextlib.suppress(OSError):
        on_disk_path.unlink()

    # Preserve the unique suffix added by ``_resolve_output`` — two
    # consecutive ``export_to_excel(..., "report.xlsx")`` calls must
    # land as distinct files, not overwrite each other.
    stored = _output_store.store(on_disk_path.name, content, _XLSX_MIME())

    # URL precedence, most-preferred first:
    # 1. Cloud viewer link (Drive ``webViewLink``) — opens the file in
    #    the user's own Drive UI in a new tab, no backend proxy.
    # 2. Backend route ``<base>/<id>/<name>`` — the host app resolves
    #    the id back to bytes via ``output_store.get_local_path``.
    #    Used for local-only deployments.
    # 3. Absolute cache path — CLI / Python-only callers who just
    #    want the file on disk.
    if stored.web_view_link:
        url = stored.web_view_link
    elif _output_url_base:
        base = _output_url_base.rstrip("/")
        url = f"{base}/{stored.id}/{stored.name}"
    else:
        url = stored.path

    item: dict[str, Any] = {
        "name": stored.name,
        "url": url,
        "sheets": sheets,
        "mimeType": stored.mime_type or _XLSX_MIME(),
        "size": stored.size_bytes,
    }
    # Signal to the frontend that this URL points to a third-party
    # viewer — ObFileCard uses it to open in a new tab with rel=noopener.
    if stored.web_view_link:
        item["external"] = True
    return item


def _push_to_render_queue(item: dict[str, Any]) -> None:
    """Push the file item onto ``openbench.chat.render_queue`` if available.

    Imported lazily so the skill still loads cleanly in contexts that
    don't install the chat extras. Silently no-ops if the queue module
    can't be imported — the tool still returns the item to the LLM as
    tool-result context, which is what the agent reads.
    """
    try:
        from openbench.chat.render_queue import push as _push
    except Exception:
        return
    # Never let a render-queue hiccup break the tool call itself.
    with contextlib.suppress(Exception):
        _push(item)


# ---------------------------------------------------------------------------
# export_to_excel
# ---------------------------------------------------------------------------


def export_to_excel(
    records: list[dict[str, Any]],
    filename: str,
    sheet_name: str = "Sheet1",
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Write one list of records to a single-sheet .xlsx file.

    Args:
        records: List of dicts — each dict becomes a row.
        filename: Output filename. ``.xlsx`` extension is added if missing.
        sheet_name: Sheet name (default ``"Sheet1"``).
        output_dir: Optional directory. Defaults to the current working
            directory. Parent dirs are created on demand.

    Returns:
        A file render item: ``{"name", "url", "sheets", "size"?}``. On
        failure returns ``{"error": "..."}``.
    """
    try:
        import pandas as pd
    except ImportError:
        return _error("pandas is required — install openbench[data]")

    if not isinstance(records, list):
        return _error("`records` must be a list of dicts")
    if not records:
        return _error("`records` is empty — nothing to export")

    try:
        df = pd.DataFrame(records)
    except Exception as e:
        return _error(f"Failed to build DataFrame: {e}")

    out_path = _resolve_output(filename, output_dir)
    try:
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    except ImportError as e:
        return _error(f"Excel writer missing: {e} — install openbench[data]")
    except Exception as e:
        return _error(f"Failed to write workbook: {e}")

    if _output_store is not None:
        item = _persist_via_bound_store(filename, out_path, [sheet_name])
    else:
        item = _file_item(out_path, [sheet_name])
    # Push onto the shared render queue so ChatEngine surfaces an
    # ObFileCard in the next assistant turn. The return value is still
    # used as tool-result context for the LLM.
    _push_to_render_queue(item)
    return item


# ---------------------------------------------------------------------------
# export_multi_sheet_excel
# ---------------------------------------------------------------------------


def _normalize_sheets(
    sheets: dict[str, list[dict[str, Any]]] | list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]] | None:
    """Accept either the mapping form or the list-of-objects form.

    The tool schema advertises a list of ``{"sheet_name", "records"}``
    objects because a bare ``{"type": "object"}`` parameter carries no
    ``properties`` and function-calling models cannot populate it. Direct
    Python callers (and older tests) still pass the natural mapping, so
    both shapes are normalised to a mapping here. Returns ``None`` when
    the input is neither shape.
    """
    if isinstance(sheets, dict):
        return sheets
    if not isinstance(sheets, list):
        return None
    normalized: dict[str, list[dict[str, Any]]] = {}
    for entry in sheets:
        if not isinstance(entry, dict):
            return None
        name = entry.get("sheet_name") or entry.get("name")
        if not isinstance(name, str) or not name:
            return None
        normalized[name] = entry.get("records", [])
    return normalized


def export_multi_sheet_excel(
    sheets: dict[str, list[dict[str, Any]]] | list[dict[str, Any]],
    filename: str,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Write multiple named sheets to one .xlsx file.

    Args:
        sheets: Either a mapping of sheet name -> list of record dicts, or
            a list of ``{"sheet_name": ..., "records": [...]}`` objects
            (the shape the tool schema advertises to the model).
        filename: Output filename.
        output_dir: Optional directory.

    Returns:
        A file render item with every successfully-written sheet listed.
    """
    try:
        import pandas as pd
    except ImportError:
        return _error("pandas is required — install openbench[data]")

    sheets = _normalize_sheets(sheets)  # type: ignore[assignment]
    if not isinstance(sheets, dict) or not sheets:
        return _error(
            "`sheets` must be a non-empty mapping of sheet_name -> records, "
            "or a non-empty list of {sheet_name, records} objects"
        )

    frames: dict[str, Any] = {}
    for name, records in sheets.items():
        if not isinstance(records, list):
            return _error(f"sheet {name!r}: records must be a list")
        try:
            frames[name] = pd.DataFrame(records)
        except Exception as e:
            return _error(f"sheet {name!r}: failed to build DataFrame: {e}")

    out_path = _resolve_output(filename, output_dir)
    try:
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            for name, df in frames.items():
                df.to_excel(writer, sheet_name=name[:31], index=False)
    except ImportError as e:
        return _error(f"Excel writer missing: {e} — install openbench[data]")
    except Exception as e:
        return _error(f"Failed to write workbook: {e}")

    if _output_store is not None:
        item = _persist_via_bound_store(filename, out_path, list(frames.keys()))
    else:
        item = _file_item(out_path, list(frames.keys()))
    _push_to_render_queue(item)
    return item


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


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


EXPORT_TO_EXCEL_SCHEMA = _schema(
    "export_to_excel",
    "Write a list of records to a single-sheet .xlsx file and return a "
    "download card the user can click. Use whenever the user asks for a "
    "spreadsheet / Excel / xlsx deliverable, in any language — English "
    "'export', 'download', 'save as excel', 'send me a spreadsheet'; "
    "Indonesian 'ekspor', 'unduh', 'buatkan file excel', 'simpan sebagai "
    "xlsx'. When a file is requested, replying with a markdown table alone "
    "is not enough — call this tool. For multi-sheet workbooks use "
    "export_multi_sheet_excel; for PDF use generate_pdf; for markdown/text "
    "use generate_markdown.",
    {
        "records": {
            "type": "array",
            "items": {"type": "object"},
            "description": "List of dicts — each dict becomes a row.",
        },
        "filename": {
            "type": "string",
            "description": "Output filename (xlsx extension added if missing)",
        },
        "sheet_name": {"type": "string", "description": "Sheet name (default 'Sheet1')"},
        # `output_dir` is intentionally NOT exposed to the model: the host
        # resolves the export directory from env, and offering the parameter
        # only invites a bogus path. It remains a Python kwarg for tests/CLI.
    },
    ["records", "filename"],
)

EXPORT_MULTI_SHEET_EXCEL_SCHEMA = _schema(
    "export_multi_sheet_excel",
    "Write multiple named sheets to one .xlsx file and return a download "
    "card. Use when a spreadsheet request naturally splits along one "
    "dimension (per region, per category, per year) — English 'export a "
    "workbook with a sheet per…', Indonesian 'buatkan file excel per…'. "
    "For a single sheet use export_to_excel; for PDF use generate_pdf. "
    "Sheet names are truncated to 31 chars (Excel limit).",
    {
        "sheets": {
            "type": "array",
            "description": "One entry per worksheet, in the order they should appear.",
            "items": {
                "type": "object",
                "properties": {
                    "sheet_name": {
                        "type": "string",
                        "description": "Worksheet name (truncated to 31 chars).",
                    },
                    "records": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Rows for this sheet — each dict becomes a row.",
                    },
                },
                "required": ["sheet_name", "records"],
            },
        },
        "filename": {
            "type": "string",
            "description": "Output filename (xlsx extension added if missing)",
        },
        # See EXPORT_TO_EXCEL_SCHEMA — `output_dir` stays host-side.
    },
    ["sheets", "filename"],
)
