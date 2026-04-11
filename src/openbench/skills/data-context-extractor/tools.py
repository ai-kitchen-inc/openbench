"""Tools for the data-context-extractor SDK skill.

Reads CSV, TSV, XLSX/XLS, and JSON files and returns a normalized
``{source, format, row_count, columns, sample, records}`` payload.

Pandas and openpyxl are imported lazily inside tool functions so that
loading this skill does not require the ``[data]`` extra at install
time — the failure only shows up when the agent actually tries to run
a tool on a real file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "extract_file_context",
    "read_csv_file",
    "read_excel_file",
    "list_excel_sheets",
    "EXTRACT_FILE_CONTEXT_SCHEMA",
    "READ_CSV_FILE_SCHEMA",
    "READ_EXCEL_FILE_SCHEMA",
    "LIST_EXCEL_SHEETS_SCHEMA",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_SAMPLE_ROWS = 5
_DEFAULT_LIMIT = 1000


def _error(source: str, message: str) -> dict[str, Any]:
    """Return a uniform error payload (never raises)."""
    return {"error": message, "source": source}


def _detect_format(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in {".csv"}:
        return "csv"
    if suffix in {".tsv"}:
        return "tsv"
    if suffix in {".xlsx"}:
        return "xlsx"
    if suffix in {".xls"}:
        return "xls"
    if suffix in {".json"}:
        return "json"
    return None


def _df_to_payload(df: Any, source: str, fmt: str, include_records: bool) -> dict[str, Any]:
    """Convert a pandas DataFrame to the standard payload shape."""
    columns = [{"name": str(c), "dtype": str(df.dtypes[c])} for c in df.columns]
    sample_df = df.head(_SAMPLE_ROWS)
    payload: dict[str, Any] = {
        "source": source,
        "format": fmt,
        "row_count": len(df),
        "columns": columns,
        "sample": sample_df.to_dict(orient="records"),
    }
    if include_records:
        payload["records"] = df.to_dict(orient="records")
    return payload


# ---------------------------------------------------------------------------
# extract_file_context — auto-detect + schema summary
# ---------------------------------------------------------------------------


def extract_file_context(path: str) -> dict[str, Any]:
    """Auto-detect a file's format and return a schema summary.

    Never raises — returns ``{"error": "..."}`` on failure so the agent
    can continue reasoning.
    """
    p = Path(path)
    if not p.exists():
        return _error(path, f"File not found: {path}")

    fmt = _detect_format(p)
    if fmt is None:
        return _error(path, f"Unsupported file extension: {p.suffix!r}")

    if fmt in {"csv", "tsv"}:
        return read_csv_file(path, limit=_SAMPLE_ROWS, full=False)
    if fmt in {"xlsx", "xls"}:
        # For Excel, return the first sheet's schema by default
        sheets = list_excel_sheets(path)
        if "error" in sheets:
            return sheets
        if not sheets["sheets"]:
            return _error(path, "Workbook has no sheets")
        return read_excel_file(path, sheet=sheets["sheets"][0], limit=_SAMPLE_ROWS, full=False)
    if fmt == "json":
        return _read_json_file(p)

    return _error(path, f"Unsupported format: {fmt}")


# ---------------------------------------------------------------------------
# read_csv_file
# ---------------------------------------------------------------------------


def read_csv_file(
    path: str,
    separator: str | None = None,
    limit: int | None = _DEFAULT_LIMIT,
    full: bool = False,
) -> dict[str, Any]:
    """Read a CSV/TSV file and return the standard payload.

    Args:
        path: File path.
        separator: Field separator. Defaults to comma for ``.csv`` and
            tab for ``.tsv``.
        limit: Max rows to return (default 1000). Pass ``None`` to read
            the whole file.
        full: If True, include ``records`` (the full dataset) alongside
            the sample. If False, ``records`` is omitted to keep the
            response lean.
    """
    try:
        import pandas as pd
    except ImportError:
        return _error(path, "pandas is required — install openbench[data]")

    p = Path(path)
    if not p.exists():
        return _error(path, f"File not found: {path}")

    if separator is None:
        separator = "\t" if p.suffix.lower() == ".tsv" else ","

    fmt = "tsv" if separator == "\t" else "csv"

    try:
        df = pd.read_csv(p, sep=separator, encoding="utf-8-sig", nrows=limit)
    except Exception as e:
        return _error(path, f"Failed to read CSV: {e}")

    return _df_to_payload(df, str(p.resolve()), fmt, include_records=full)


# ---------------------------------------------------------------------------
# read_excel_file
# ---------------------------------------------------------------------------


def read_excel_file(
    path: str,
    sheet: str | None = None,
    limit: int | None = _DEFAULT_LIMIT,
    full: bool = False,
) -> dict[str, Any]:
    """Read a single sheet from an Excel workbook.

    Args:
        path: Path to the .xlsx/.xls file.
        sheet: Sheet name. If omitted, the first sheet is read.
        limit: Max rows to return (default 1000).
        full: If True, include full records.
    """
    try:
        import pandas as pd
    except ImportError:
        return _error(path, "pandas is required — install openbench[data]")

    p = Path(path)
    if not p.exists():
        return _error(path, f"File not found: {path}")

    try:
        df = pd.read_excel(p, sheet_name=sheet or 0, nrows=limit)
    except ImportError as e:
        return _error(path, f"Excel reader missing: {e} — install openbench[data]")
    except Exception as e:
        return _error(path, f"Failed to read Excel sheet: {e}")

    payload = _df_to_payload(
        df, str(p.resolve()), p.suffix.lower().lstrip("."), include_records=full
    )
    payload["sheet"] = sheet or 0
    return payload


# ---------------------------------------------------------------------------
# list_excel_sheets
# ---------------------------------------------------------------------------


def list_excel_sheets(path: str) -> dict[str, Any]:
    """List every sheet name in an Excel workbook."""
    try:
        import pandas as pd
    except ImportError:
        return _error(path, "pandas is required — install openbench[data]")

    p = Path(path)
    if not p.exists():
        return _error(path, f"File not found: {path}")

    try:
        xl = pd.ExcelFile(p)
    except ImportError as e:
        return _error(path, f"Excel reader missing: {e} — install openbench[data]")
    except Exception as e:
        return _error(path, f"Failed to open workbook: {e}")

    return {
        "source": str(p.resolve()),
        "format": p.suffix.lower().lstrip("."),
        "sheets": list(xl.sheet_names),
    }


# ---------------------------------------------------------------------------
# JSON helper (not exposed as a tool — used by extract_file_context)
# ---------------------------------------------------------------------------


def _read_json_file(p: Path) -> dict[str, Any]:
    try:
        text = p.read_text(encoding="utf-8")
        data = json.loads(text)
    except Exception as e:
        return _error(str(p), f"Failed to parse JSON: {e}")

    records: list[dict[str, Any]] = []
    if isinstance(data, list):
        records = [row for row in data if isinstance(row, dict)]
    elif isinstance(data, dict):
        for key in ("data", "records", "rows"):
            val = data.get(key)
            if isinstance(val, list):
                records = [row for row in val if isinstance(row, dict)]
                break
        if not records:
            # Scalar dict — treat as a single record
            records = [{k: v for k, v in data.items() if not isinstance(v, (list, dict))}]

    columns: list[dict[str, str]] = []
    if records:
        seen: dict[str, str] = {}
        for row in records:
            for k, v in row.items():
                if k not in seen:
                    seen[k] = type(v).__name__
        columns = [{"name": k, "dtype": dt} for k, dt in seen.items()]

    return {
        "source": str(p.resolve()),
        "format": "json",
        "row_count": len(records),
        "columns": columns,
        "sample": records[:_SAMPLE_ROWS],
    }


# ---------------------------------------------------------------------------
# Tool schemas — BaseAgent's Skill loader discovers these by convention.
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


EXTRACT_FILE_CONTEXT_SCHEMA = _schema(
    "extract_file_context",
    "Auto-detect a file's format (CSV, Excel, JSON) and return its schema + "
    "a small sample of rows. Use this FIRST whenever the user uploads or "
    "points at a file and you need to know what's inside it.",
    {"path": {"type": "string", "description": "Absolute or relative file path"}},
    ["path"],
)

READ_CSV_FILE_SCHEMA = _schema(
    "read_csv_file",
    "Read a CSV or TSV file. Returns schema + sample rows; pass full=true to "
    "also return the complete dataset.",
    {
        "path": {"type": "string"},
        "separator": {
            "type": "string",
            "description": "Field separator. Defaults to ',' for .csv and tab for .tsv.",
        },
        "limit": {
            "type": "integer",
            "description": "Max rows to read (default 1000). Omit or 0 for all rows.",
        },
        "full": {
            "type": "boolean",
            "description": "Include the complete dataset under 'records'. Default false.",
        },
    },
    ["path"],
)

READ_EXCEL_FILE_SCHEMA = _schema(
    "read_excel_file",
    "Read one sheet from an Excel workbook. Call list_excel_sheets first if "
    "you don't know the sheet name.",
    {
        "path": {"type": "string"},
        "sheet": {
            "type": "string",
            "description": "Sheet name. Omit to read the first sheet.",
        },
        "limit": {"type": "integer", "description": "Max rows to read (default 1000)"},
        "full": {"type": "boolean"},
    },
    ["path"],
)

LIST_EXCEL_SHEETS_SCHEMA = _schema(
    "list_excel_sheets",
    "List every sheet name in an Excel workbook. Cheap — reads workbook "
    "metadata only, not the sheet contents.",
    {"path": {"type": "string"}},
    ["path"],
)
