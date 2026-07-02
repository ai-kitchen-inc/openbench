"""Tools for the data-context-extractor SDK skill.

Reads CSV, TSV, XLSX/XLS, and JSON files and returns a normalized
``{source, format, row_count, columns, sample, records}`` payload.

Also provides a **column profile** system: LLM-inferred column role
mappings (amount, category, metric, label, etc.) are persisted to disk
so the same file never needs re-mapping across sessions or users.
Profiles are keyed by file content hash (SHA-256) so a renamed or
re-uploaded copy of the same file hits the cache.

Pandas and openpyxl are imported lazily inside tool functions so that
loading this skill does not require the ``[data]`` extra at install
time — the failure only shows up when the agent actually tries to run
a tool on a real file.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "extract_file_context",
    "read_csv_file",
    "read_excel_file",
    "list_excel_sheets",
    "save_column_profile",
    "get_column_profile",
    "update_column_profile",
    "EXTRACT_FILE_CONTEXT_SCHEMA",
    "READ_CSV_FILE_SCHEMA",
    "READ_EXCEL_FILE_SCHEMA",
    "LIST_EXCEL_SHEETS_SCHEMA",
    "SAVE_COLUMN_PROFILE_SCHEMA",
    "GET_COLUMN_PROFILE_SCHEMA",
    "UPDATE_COLUMN_PROFILE_SCHEMA",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_SAMPLE_ROWS = 5
_DEFAULT_LIMIT = 1000
_PROFILE_VERSION = "1.0"


def _error(source: str, message: str) -> dict[str, Any]:
    """Return a uniform error payload (never raises)."""
    return {"error": message, "source": source}


# ---------------------------------------------------------------------------
# Column profile helpers
# ---------------------------------------------------------------------------


def _profile_dir() -> Path:
    """Return the directory for column profile storage.

    Reads ``OPENBENCH_PROFILE_DIR`` at call time. Falls back to
    ``<cwd>/profiles/``. Parent dirs are created on demand.
    """
    d = Path(os.environ.get("OPENBENCH_PROFILE_DIR", "profiles")).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file_hash(path: Path) -> str:
    """SHA-256 content hash of a file, truncated to 16 hex chars.

    Same file content = same hash, even if renamed or re-uploaded.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _profile_path(file_hash: str) -> Path:
    return _profile_dir() / f"{file_hash}.json"


def _load_profile(file_hash: str) -> dict[str, Any] | None:
    """Load a column profile from disk. Returns None if not found."""
    p = _profile_path(file_hash)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_profile_to_disk(profile: dict[str, Any], file_hash: str) -> Path:
    """Write a profile to disk. Returns the file path."""
    p = _profile_path(file_hash)
    p.write_text(json.dumps(profile, indent=2, default=str), encoding="utf-8")
    return p


def _build_column_roles(profile: dict[str, Any], sheet: str | None = None) -> dict[str, str]:
    """Extract a flat {column_name: role} map from a profile."""
    sheets = profile.get("sheets", {})
    if sheet and sheet in sheets:
        cols = sheets[sheet].get("columns", [])
    elif sheets:
        cols = next(iter(sheets.values())).get("columns", [])
    else:
        return {}
    return {c["physical_name"]: c["role"] for c in cols if "physical_name" in c and "role" in c}


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

    Also checks for a cached column profile (see ``save_column_profile``).
    When a profile exists, the response includes ``profile_status: "cached"``
    and ``column_roles: {column_name: role}``. When no profile exists,
    ``profile_status: "needs_mapping"`` and ``unmapped_columns: [...]``
    signal the agent to infer roles and call ``save_column_profile``.

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
        result = read_csv_file(path, limit=_SAMPLE_ROWS, full=False)
    elif fmt in {"xlsx", "xls"}:
        sheets = list_excel_sheets(path)
        if "error" in sheets:
            return sheets
        if not sheets["sheets"]:
            return _error(path, "Workbook has no sheets")
        result = read_excel_file(path, sheet=sheets["sheets"][0], limit=_SAMPLE_ROWS, full=False)
    elif fmt == "json":
        result = _read_json_file(p)
    else:
        return _error(path, f"Unsupported format: {fmt}")

    if "error" in result:
        return result

    # Enrich with column profile if available
    try:
        fhash = _file_hash(p)
        result["file_hash"] = fhash
        profile = _load_profile(fhash)
        if profile is not None:
            result["profile_status"] = "cached"
            result["column_roles"] = _build_column_roles(profile)
        else:
            result["profile_status"] = "needs_mapping"
            # Flag columns that have numeric dtype but no known role —
            # these are the ones LLM should infer (amount, metric, FU, etc.)
            unmapped = [
                c["name"]
                for c in result.get("columns", [])
                if c.get("dtype", "").startswith(("float", "int"))
            ]
            result["unmapped_columns"] = unmapped
    except Exception:
        # Profile check failed — degrade gracefully, schema is still valid
        result["profile_status"] = "unavailable"

    return result


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
# save_column_profile — persist LLM-inferred column roles
# ---------------------------------------------------------------------------


def save_column_profile(
    path: str,
    mappings: list[dict[str, str]],
    sheet: str | None = None,
) -> dict[str, Any]:
    """Save column role mappings for a file so they persist across sessions.

    Called by the agent after it infers column roles from
    ``extract_file_context`` + reasoning. Once saved, subsequent calls to
    ``extract_file_context`` for the same file return ``profile_status:
    "cached"`` and the agent can skip re-mapping.

    Args:
        path: The file path (used to compute content hash).
        mappings: List of ``{"column": "<name>", "role": "<role>"}`` dicts.
            Accepted roles: identifier, label, category, amount, metric,
            unit, timestamp, description, source, functional_unit, io,
            process, unknown (and any domain-specific extension).
        sheet: Sheet name. Defaults to the first sheet.

    Returns:
        ``{"saved": true, "file_hash": "...", "profile_path": "..."}``
        or ``{"error": "..."}``.
    """
    p = Path(path)
    if not p.exists():
        return _error(path, f"File not found: {path}")
    if not isinstance(mappings, list) or not mappings:
        return _error(path, "`mappings` must be a non-empty list")

    fhash = _file_hash(p)
    sheet_key = sheet or "default"

    # Load existing profile or start fresh
    profile = _load_profile(fhash) or {
        "version": _PROFILE_VERSION,
        "file_hash": fhash,
        "file_name": p.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mapped_by": "llm",
        "sheets": {},
    }

    # Build column entries
    columns = []
    for m in mappings:
        if not isinstance(m, dict) or "column" not in m or "role" not in m:
            continue
        entry: dict[str, str] = {
            "physical_name": m["column"],
            "role": m["role"],
        }
        if "description" in m:
            entry["description"] = m["description"]
        if "dtype" in m:
            entry["dtype"] = m["dtype"]
        columns.append(entry)

    profile["sheets"][sheet_key] = {"columns": columns}
    profile["updated_at"] = datetime.now(timezone.utc).isoformat()

    saved_path = _save_profile_to_disk(profile, fhash)
    return {"saved": True, "file_hash": fhash, "profile_path": str(saved_path)}


# ---------------------------------------------------------------------------
# get_column_profile — read cached profile
# ---------------------------------------------------------------------------


def get_column_profile(path: str) -> dict[str, Any]:
    """Load the cached column profile for a file.

    Returns the full profile JSON if cached, or ``profile_status:
    "not_found"`` if no profile exists. Use this in a new session to
    check whether column mapping has already been done for this file.

    Args:
        path: The file path.
    """
    p = Path(path)
    if not p.exists():
        return _error(path, f"File not found: {path}")
    fhash = _file_hash(p)
    profile = _load_profile(fhash)
    if profile is None:
        return {"profile_status": "not_found", "file_hash": fhash}
    return {"profile_status": "cached", "file_hash": fhash, "profile": profile}


# ---------------------------------------------------------------------------
# update_column_profile — correct a single column mapping
# ---------------------------------------------------------------------------


def update_column_profile(
    path: str,
    column: str,
    role: str,
    description: str | None = None,
    sheet: str | None = None,
) -> dict[str, Any]:
    """Update the role of a single column in an existing profile.

    Used when the user corrects the LLM's mapping. The correction
    persists so the same file is handled correctly in future sessions.

    Args:
        path: The file path.
        column: Physical column name to update.
        role: New role to assign.
        description: Optional human-readable description.
        sheet: Sheet name. Defaults to the first sheet.
    """
    p = Path(path)
    if not p.exists():
        return _error(path, f"File not found: {path}")
    fhash = _file_hash(p)
    profile = _load_profile(fhash)
    if profile is None:
        return _error(path, "No profile found for this file. Call save_column_profile first.")

    sheet_key = sheet or "default"
    if sheet_key not in profile.get("sheets", {}):
        # Try first available sheet
        sheets = profile.get("sheets", {})
        sheet_key = next(iter(sheets)) if sheets else "default"
        if sheet_key not in profile.get("sheets", {}):
            return _error(path, f"Sheet {sheet_key!r} not in profile")

    cols = profile["sheets"][sheet_key].get("columns", [])
    found = False
    for c in cols:
        if c.get("physical_name") == column:
            c["role"] = role
            if description:
                c["description"] = description
            found = True
            break

    if not found:
        # Column not in profile yet — add it
        entry: dict[str, str] = {"physical_name": column, "role": role}
        if description:
            entry["description"] = description
        cols.append(entry)

    profile["sheets"][sheet_key]["columns"] = cols
    profile["updated_at"] = datetime.now(timezone.utc).isoformat()
    profile["mapped_by"] = "user_corrected"
    _save_profile_to_disk(profile, fhash)
    return {"updated": True, "column": column, "role": role}


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

SAVE_COLUMN_PROFILE_SCHEMA = _schema(
    "save_column_profile",
    "Save column role mappings for a file so they persist across sessions. "
    "Call this AFTER you infer column roles from extract_file_context + "
    "reasoning. Once saved, subsequent extract_file_context calls for the "
    "same file return profile_status='cached' and you can skip re-mapping. "
    "Accepted roles: identifier, label, category, amount, metric, unit, "
    "timestamp, description, source, functional_unit, io, process, unknown.",
    {
        "path": {"type": "string", "description": "File path (used to compute content hash)"},
        "mappings": {
            "type": "array",
            "description": "List of {column, role} dicts. Optionally include description and dtype.",
            "items": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "role": {"type": "string"},
                    "description": {"type": "string"},
                    "dtype": {"type": "string"},
                },
                "required": ["column", "role"],
            },
        },
        "sheet": {"type": "string", "description": "Sheet name. Defaults to first sheet."},
    },
    ["path", "mappings"],
)

GET_COLUMN_PROFILE_SCHEMA = _schema(
    "get_column_profile",
    "Load the cached column profile for a file. Returns the full profile "
    "if cached, or profile_status='not_found' if no profile exists. Use "
    "this at the start of a new session to check if column mapping has "
    "already been done for this file.",
    {"path": {"type": "string"}},
    ["path"],
)

UPDATE_COLUMN_PROFILE_SCHEMA = _schema(
    "update_column_profile",
    "Correct a single column's role in an existing profile. Use when the "
    "user says a column was mapped incorrectly. The correction persists "
    "across sessions.",
    {
        "path": {"type": "string"},
        "column": {"type": "string", "description": "Physical column name to update"},
        "role": {"type": "string", "description": "New role to assign"},
        "description": {"type": "string", "description": "Optional human-readable description"},
        "sheet": {"type": "string"},
    },
    ["path", "column", "role"],
)
