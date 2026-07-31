"""Convert uploaded spreadsheets and CSVs into queryable Parquet tables.

Spreadsheets are the worst case for prompt-stuffing: a 50,000-row sheet
rendered as markdown is both enormous and useless for arithmetic. This
module converts each sheet to Parquet once at ingest and produces a
compact schema card describing it, so the model reasons about the shape
of the data and runs SQL for the values.

``pandas``/``pyarrow`` are imported inside functions so importing this
module never fails on an install without the ``tabular`` extra.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TABULAR_EXTENSIONS = {".csv", ".tsv", ".xlsx", ".xls", ".xlsm"}
TABULAR_MIME_HINTS = (
    "text/csv",
    "text/tab-separated-values",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml",
)

#: Sample rows kept per table for the schema card.
SAMPLE_ROWS = 3
#: Columns profiled before the card starts summarizing.
MAX_PROFILED_COLUMNS = 200

_SLUG_RE = re.compile(r"[^0-9a-zA-Z]+")


def _slug(value: str) -> str:
    """Normalize a sheet or file name into a SQL-safe table alias."""
    slug = _SLUG_RE.sub("_", value or "").strip("_").lower()
    if not slug:
        slug = "table"
    if slug[0].isdigit():
        slug = f"t_{slug}"
    return slug[:60]


def _json_safe(value: Any) -> Any:
    """Coerce a pandas/numpy scalar into something JSON can hold."""
    if value is None:
        return None
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (str, int, bool)):
        return value
    for attr in ("isoformat", "item"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                return _json_safe(method())
            except Exception:
                break
    try:
        if value != value:  # NaN/NaT are the only values unequal to themselves
            return None
    except Exception:
        pass
    return str(value)


def is_tabular_file(name: str, mime_type: str = "") -> bool:
    """True when a file should be converted to Parquet."""
    if Path(name or "").suffix.lower() in TABULAR_EXTENSIONS:
        return True
    mime = (mime_type or "").lower()
    return any(mime.startswith(hint) for hint in TABULAR_MIME_HINTS)


@dataclass
class TableColumn:
    """Profile of a single column, as shown on the schema card."""

    name: str
    dtype: str
    null_count: int = 0
    distinct_estimate: int | None = None
    min: Any = None
    max: Any = None
    sample_values: list[Any] = field(default_factory=list)

    def describe(self) -> str:
        """One-line description for the schema card."""
        parts = [f"{self.name} {self.dtype}"]
        if self.min is not None and self.max is not None and self.min != self.max:
            parts.append(f"({self.min}..{self.max})")
        elif self.distinct_estimate:
            parts.append(f"({self.distinct_estimate} distinct)")
        if self.null_count:
            parts.append(f"[{self.null_count} null]")
        return " ".join(parts)


@dataclass
class TableArtifact:
    """One Parquet table derived from an uploaded file."""

    table_id: str
    source_id: str
    name: str
    display_name: str
    parquet_path: str
    row_count: int
    columns: list[TableColumn] = field(default_factory=list)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    source_hash: str = ""
    created_at: str = ""
    warnings: list[str] = field(default_factory=list)

    def schema_card(self, *, max_columns: int = 40, max_sample_rows: int = SAMPLE_ROWS) -> str:
        """Render the compact description that goes into the prompt."""
        lines = [
            f'Table "{self.name}"  {self.row_count:,} rows x {len(self.columns)} cols'
            f"  (from {self.display_name})"
        ]
        shown = self.columns[:max_columns]
        lines.extend(f"  - {column.describe()}" for column in shown)
        if len(self.columns) > len(shown):
            lines.append(f"  ... and {len(self.columns) - len(shown)} more columns")
        lines.extend(f"  sample: {row}" for row in self.sample_rows[:max_sample_rows])
        lines.extend(f"  note: {warning}" for warning in self.warnings)
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TableArtifact:
        payload = dict(data)
        payload["columns"] = [
            column if isinstance(column, TableColumn) else TableColumn(**column)
            for column in payload.get("columns") or []
        ]
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in payload.items() if key in known})


def _file_hash(path: Path) -> str:
    """Content hash of the source file, for change detection."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()[:16]}"


def _read_csv(path: Path, separator: str | None):
    import pandas as pd

    try:
        return pd.read_csv(path, sep=separator, encoding="utf-8-sig")
    except UnicodeDecodeError:
        # Matches the fallback the general-chat CSV parser already uses.
        return pd.read_csv(path, sep=separator, encoding="latin-1")


def _dedupe_columns(frame) -> tuple[Any, list[str]]:
    """Make column names unique and string-typed.

    Parquet cannot store duplicate field names, and pandas happily reads
    spreadsheets that have them.
    """
    warnings: list[str] = []
    seen: dict[str, int] = {}
    renamed: list[str] = []
    for raw in frame.columns:
        name = str(raw).strip() or "column"
        if name in seen:
            seen[name] += 1
            new_name = f"{name}_{seen[name]}"
            warnings.append(f'duplicate column "{name}" renamed to "{new_name}"')
            name = new_name
        else:
            seen[name] = 0
        renamed.append(name)
    frame.columns = renamed
    return frame, warnings


def _profile_columns(frame) -> list[TableColumn]:
    """Build per-column profiles for the schema card."""
    columns: list[TableColumn] = []
    for name in list(frame.columns)[:MAX_PROFILED_COLUMNS]:
        series = frame[name]
        dtype = str(series.dtype)
        try:
            null_count = int(series.isna().sum())
        except Exception:
            null_count = 0

        minimum = maximum = None
        distinct = None
        try:
            non_null = series.dropna()
            if not non_null.empty:
                if str(series.dtype).startswith(("int", "float", "datetime")):
                    minimum = _json_safe(non_null.min())
                    maximum = _json_safe(non_null.max())
                else:
                    distinct = int(non_null.nunique())
        except Exception:
            pass

        samples: list[Any] = []
        with contextlib.suppress(Exception):
            samples = [_json_safe(value) for value in series.dropna().head(2).tolist()]

        columns.append(
            TableColumn(
                name=str(name),
                dtype=dtype,
                null_count=null_count,
                distinct_estimate=distinct,
                min=minimum,
                max=maximum,
                sample_values=samples,
            )
        )
    return columns


def _sample_rows(frame, limit: int = SAMPLE_ROWS) -> list[dict[str, Any]]:
    try:
        head = frame.head(limit)
    except Exception:
        return []
    return [
        {str(key): _json_safe(value) for key, value in record.items()}
        for record in head.to_dict(orient="records")
    ]


def _write_parquet(frame, destination: Path, compression: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    destination.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(table, destination, compression=compression)


def convert_to_parquet(
    path: str | Path,
    *,
    dest_dir: str | Path,
    source_id: str,
    max_rows: int | None = None,
    compression: str = "zstd",
    separator: str | None = None,
) -> list[TableArtifact]:
    """Convert a CSV/TSV/Excel file into one Parquet table per sheet.

    Args:
        path: The uploaded file.
        dest_dir: Directory to write Parquet files into.
        source_id: Owning source id, used to build table ids.
        max_rows: Optional row cap per table.
        compression: Parquet codec.
        separator: Explicit CSV separator; inferred from the suffix when
            not given.

    Returns:
        One :class:`TableArtifact` per non-empty sheet. Sheets that fail
        to convert are skipped and logged rather than aborting the file.

    Raises:
        ImportError: If pandas or pyarrow are not installed.
        ValueError: If the file cannot be read at all.
    """
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "Parquet conversion requires pandas and pyarrow. Install openbench[tabular]."
        ) from exc

    source_path = Path(path)
    if not source_path.is_file():
        raise ValueError(f"Tabular file not found: {source_path}")

    dest = Path(dest_dir)
    suffix = source_path.suffix.lower()
    source_hash = _file_hash(source_path)
    created_at = datetime.now(timezone.utc).isoformat()

    frames: list[tuple[str, Any]] = []
    try:
        if suffix in (".xlsx", ".xls", ".xlsm"):
            sheets = pd.read_excel(source_path, sheet_name=None)
            frames = list(sheets.items())
        else:
            sep = separator if separator is not None else ("\t" if suffix == ".tsv" else ",")
            frames = [(source_path.stem, _read_csv(source_path, sep))]
    except Exception as exc:
        raise ValueError(f"Could not read tabular file: {exc}") from exc

    artifacts: list[TableArtifact] = []
    used_names: set[str] = set()

    for sheet_name, frame in frames:
        try:
            if frame is None or frame.empty:
                continue
            frame, warnings = _dedupe_columns(frame.copy())
            if max_rows is not None and len(frame) > max_rows:
                warnings.append(f"truncated to the first {max_rows:,} rows")
                frame = frame.head(max_rows)

            alias = _slug(str(sheet_name))
            candidate = alias
            counter = 2
            while candidate in used_names:
                candidate = f"{alias}_{counter}"
                counter += 1
            used_names.add(candidate)

            parquet_path = dest / f"{candidate}.parquet"
            _write_parquet(frame, parquet_path, compression)

            artifacts.append(
                TableArtifact(
                    table_id=f"{source_id}--{candidate}",
                    source_id=source_id,
                    name=candidate,
                    display_name=str(sheet_name),
                    parquet_path=str(parquet_path),
                    row_count=len(frame),
                    columns=_profile_columns(frame),
                    sample_rows=_sample_rows(frame),
                    source_hash=source_hash,
                    created_at=created_at,
                    warnings=warnings,
                )
            )
        except Exception as exc:
            # One unreadable sheet must not cost the user the whole file.
            logger.warning("Skipping sheet %r of %s: %s", sheet_name, source_path.name, exc)

    return artifacts


__all__ = [
    "MAX_PROFILED_COLUMNS",
    "SAMPLE_ROWS",
    "TABULAR_EXTENSIONS",
    "TableArtifact",
    "TableColumn",
    "convert_to_parquet",
    "is_tabular_file",
]
