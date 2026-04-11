"""Tools for the export-excel SDK skill.

Writes records to .xlsx files and returns a file render item in the
shape expected by ``openbench.chat.renderers.file.FileRenderer``:

    {"name": "<filename>", "url": "<path or url>", "size": <bytes>?, ...}

``pandas`` and ``openpyxl`` are imported lazily so that loading this
skill does not require the ``[data]`` extra at install time — the
failure only surfaces when the agent actually calls one of the tools.

Deployment config (read at tool-call time, not at import time):

- ``OPENBENCH_EXPORT_DIR`` — absolute path where every exported file
  should land. Defaults to the process CWD, which is almost never
  what you want in production (files end up in the repo root).
- ``OPENBENCH_EXPORT_URL_BASE`` — URL prefix used to build the
  downloadable ``url`` field on the returned render item. For
  example, ``/downloads`` makes the card link to
  ``/downloads/<filename>``. When unset the render item falls back
  to the absolute filesystem path, which the frontend cannot fetch
  over HTTP — so in any deployed context you want BOTH env vars set
  together.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

__all__ = [
    "export_to_excel",
    "export_multi_sheet_excel",
    "EXPORT_TO_EXCEL_SCHEMA",
    "EXPORT_MULTI_SHEET_EXCEL_SCHEMA",
]


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
    2. ``OPENBENCH_EXPORT_DIR`` environment variable
    3. Process CWD (legacy fallback — usually wrong in production)

    Parent directories are created on demand. The filename always
    gets a unique suffix so concurrent or repeated exports don't
    collide.
    """
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
        return str(path)
    return f"{base}/{path.name}"


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

    return _file_item(out_path, [sheet_name])


# ---------------------------------------------------------------------------
# export_multi_sheet_excel
# ---------------------------------------------------------------------------


def export_multi_sheet_excel(
    sheets: dict[str, list[dict[str, Any]]],
    filename: str,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Write multiple named sheets to one .xlsx file.

    Args:
        sheets: Mapping of sheet name -> list of record dicts.
        filename: Output filename.
        output_dir: Optional directory.

    Returns:
        A file render item with every successfully-written sheet listed.
    """
    try:
        import pandas as pd
    except ImportError:
        return _error("pandas is required — install openbench[data]")

    if not isinstance(sheets, dict) or not sheets:
        return _error("`sheets` must be a non-empty mapping of sheet_name -> records")

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

    return _file_item(out_path, list(frames.keys()))


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
    "Write a list of records to a single-sheet .xlsx file. Returns a file "
    "render item (name, url, size) that the chat UI renders as a download card.",
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
        "output_dir": {
            "type": "string",
            "description": "Optional directory. Defaults to the current working directory.",
        },
    },
    ["records", "filename"],
)

EXPORT_MULTI_SHEET_EXCEL_SCHEMA = _schema(
    "export_multi_sheet_excel",
    "Write multiple named sheets to one .xlsx file. Use this for reports "
    "that naturally split along one dimension (per region, per category, "
    "per year). Sheet names are truncated to 31 chars (Excel limit).",
    {
        "sheets": {
            "type": "object",
            "description": "Mapping of sheet_name -> list of records. Keys are sheet names, values are dict lists.",
        },
        "filename": {"type": "string"},
        "output_dir": {"type": "string"},
    },
    ["sheets", "filename"],
)
