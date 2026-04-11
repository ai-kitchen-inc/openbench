"""Tools for the export-excel SDK skill.

Writes records to .xlsx files and returns a file render item in the
shape expected by ``openbench.chat.renderers.file.FileRenderer``:

    {"name": "<filename>", "url": "<path or url>", "size": <bytes>?, ...}

``pandas`` and ``openpyxl`` are imported lazily so that loading this
skill does not require the ``[data]`` extra at install time — the
failure only surfaces when the agent actually calls one of the tools.
"""

from __future__ import annotations

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


def _resolve_output(filename: str, output_dir: str | None) -> Path:
    """Return an absolute path for the output file.

    If ``output_dir`` is given, the file is placed there. Otherwise it
    goes to the current working directory. Parent directories are
    created on demand.
    """
    p = Path(filename)
    if output_dir:
        p = Path(output_dir) / p.name
    p = p.resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() != ".xlsx":
        p = p.with_suffix(".xlsx")
    return p


def _file_item(path: Path, sheets: list[str]) -> dict[str, Any]:
    """Build a file render item consumable by FileRenderer."""
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    item: dict[str, Any] = {
        "name": path.name,
        "url": str(path),
        "sheets": sheets,
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
