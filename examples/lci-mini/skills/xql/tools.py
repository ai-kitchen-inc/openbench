"""XQL — Excel as RDBMS.

Three-layer implementation of the XQL skill: CATALOG (discover tables),
QUERY (single-table relational operators), and TRANSFORM (multi-table
operators + LCI IO-Table builder).

All tools share a single ``_STATE`` dict keyed by ``table_id``. A table_id
is "<file_stem>.<sheet_name>" (e.g. ``input.Sheet14``). The state survives
across tool calls within the same process so Claude can build a catalog
once and then run many queries against it.
"""

from __future__ import annotations

import contextvars
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# Module-level config loaded once from config/*.yaml
# ---------------------------------------------------------------------------

_SKILL_DIR = Path(__file__).resolve().parent
_CONFIG_DIR = _SKILL_DIR / "config"


def _load_yaml(name: str) -> dict:
    path = _CONFIG_DIR / name
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


_ALIASES_CFG = _load_yaml("aliases.yaml").get("aliases", {})
_UNITS_CFG = _load_yaml("units.yaml")
_RULES_CFG = _load_yaml("lci_rules.yaml")


# ---------------------------------------------------------------------------
# State — cached DataFrames + schema map
# ---------------------------------------------------------------------------


class _TableMeta:
    __slots__ = ("alias_map", "df", "file", "header_row", "sheet", "table_id")

    def __init__(
        self,
        table_id: str,
        file: str,
        sheet: str,
        header_row: int | list[int],
        df: pd.DataFrame,
        alias_map: dict[str, str],
    ) -> None:
        self.table_id = table_id
        self.file = file
        self.sheet = sheet
        self.header_row = header_row
        self.df = df
        self.alias_map = alias_map  # logical alias -> physical column name

    def describe(self) -> dict[str, Any]:
        cols = []
        for i, col in enumerate(self.df.columns):
            series = self.df[col]
            alias = next((a for a, p in self.alias_map.items() if p == col), None)
            cols.append(
                {
                    "index": i,
                    "name": str(col),
                    "alias": alias,
                    "dtype": str(series.dtype),
                    "nulls": int(series.isna().sum()),
                }
            )
        return {
            "table_id": self.table_id,
            "file": self.file,
            "sheet": self.sheet,
            "header_row": self.header_row,
            "row_count": len(self.df),
            "columns": cols,
        }


_STATE: dict[str, _TableMeta] = {}


# ContextVar populated by the server (/awp handler) with the absolute paths of
# files the user attached to the current chat turn. When xql_catalog is called
# with files=None, it falls back to this list. This lets Claude just say
# "catalog the uploaded file" without having to guess a path.
_UPLOADED_FILES: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "lci_mini_xql_uploaded_files", default=None
)


def set_uploaded_files(paths: list[str] | None) -> None:
    """Set the list of uploaded file paths for the current request.

    Called by the FastAPI server on every /awp request after resolving
    attachment IDs to on-disk paths. Pass ``None`` to clear.
    """
    _UPLOADED_FILES.set(paths)


def get_uploaded_files() -> list[str]:
    """Return the list of uploaded file paths set by the server."""
    return list(_UPLOADED_FILES.get() or [])


def _reset_state() -> None:
    """Clear the catalog. Primarily used by tests."""
    _STATE.clear()
    _UPLOADED_FILES.set(None)


# ---------------------------------------------------------------------------
# Helpers — alias resolution, header detection, unit conversion
# ---------------------------------------------------------------------------


def _resolve_alias(alias_map: dict[str, str], name: str) -> str:
    """Resolve a logical alias to a physical column, or return name unchanged.

    If ``name`` is already a physical column in the alias_map values, it is
    returned as-is. If it's a logical alias, its physical name is returned.
    Otherwise raises ``KeyError`` listing available names.
    """
    if name in alias_map:
        return alias_map[name]
    if name in alias_map.values():
        return name
    # Not an alias and not a physical match — be explicit about what's available
    available = sorted(set(list(alias_map.keys()) + list(alias_map.values())))
    raise KeyError(f"Column {name!r} not found. Available (aliases + physical): {available}")


def _build_alias_map(columns: list[str]) -> dict[str, str]:
    """Pick the first matching physical column for every logical alias."""
    alias_map: dict[str, str] = {}
    cols_lower = {c.lower().strip(): c for c in columns}
    for logical, candidates in _ALIASES_CFG.items():
        for cand in candidates:
            if cand in columns:
                alias_map[logical] = cand
                break
            if cand.lower().strip() in cols_lower:
                alias_map[logical] = cols_lower[cand.lower().strip()]
                break
    return alias_map


def _detect_header_row(raw: pd.DataFrame, max_scan: int = 5) -> int:
    """Guess which row in the first ``max_scan`` rows is the header.

    Strategy: score each row by how many cells are non-numeric strings —
    the header usually has the highest string count. If row 0 already
    looks like data (mostly numeric), we still return 0 and let the
    caller treat it as headerless (column names become "col_0", ...).
    """
    scan = min(max_scan, len(raw))
    best_row = 0
    best_score = -1
    for r in range(scan):
        row = raw.iloc[r]
        score = sum(1 for v in row if isinstance(v, str) and not v.strip().isdigit())
        if score > best_score:
            best_score = score
            best_row = r
    return best_row


def _flatten_multi_header(headers: list[list[str]]) -> list[str]:
    """Join N header rows into one flat list, skipping empty cells."""
    flat = []
    for col_idx in range(len(headers[0])):
        parts = []
        for row in headers:
            v = row[col_idx]
            if pd.isna(v):
                continue
            s = str(v).strip()
            if s and s not in parts:
                parts.append(s)
        flat.append("_".join(parts) if parts else f"_unnamed_{col_idx}")
    return flat


def _find_unit_dimension(unit: str) -> str | None:
    for dim, cfg in _UNITS_CFG.items():
        if not isinstance(cfg, dict):
            continue
        if unit in cfg.get("conversions", {}):
            return dim
    return None


def _convert_to_base(value: float, unit: str, dim: str) -> float:
    factors = _UNITS_CFG[dim]["conversions"]
    return float(value) * float(factors[unit])


def _convert_value(value: float, from_unit: str, to_unit: str) -> float:
    src_dim = _find_unit_dimension(from_unit)
    dst_dim = _find_unit_dimension(to_unit)
    if src_dim is None:
        raise ValueError(f"Unknown source unit: {from_unit!r}")
    if dst_dim is None:
        raise ValueError(f"Unknown target unit: {to_unit!r}")
    if src_dim != dst_dim:
        raise ValueError(
            f"Cannot convert {from_unit!r} ({src_dim}) to {to_unit!r} ({dst_dim}) "
            f"— different physical dimensions."
        )
    factors = _UNITS_CFG[src_dim]["conversions"]
    base = float(value) * float(factors[from_unit])
    return base / float(factors[to_unit])


def _get_table(table_id: str) -> _TableMeta:
    if table_id not in _STATE:
        raise KeyError(f"Table {table_id!r} not in catalog. Loaded: {sorted(_STATE.keys())}")
    return _STATE[table_id]


def _coerce_numeric(value: Any) -> float | None:
    """Try to coerce a value to float. Return None if not possible.

    Used for numeric comparisons where the LLM sends string values
    (Gemini's tool schema forces strings) but the DataFrame column is
    numeric.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _apply_condition(df: pd.DataFrame, col: str, op: str, value: Any) -> pd.DataFrame:
    """Apply a single (col, op, value) filter to a DataFrame.

    String and numeric values are both supported: numeric ops auto-coerce
    both the column and the value to ``float`` so LLM-supplied strings
    like ``"100"`` work the same as Python ints.
    """
    series = df[col]
    op = op.upper() if isinstance(op, str) else op

    numeric_ops = {">", "<", ">=", "<="}
    if op in numeric_ops:
        num_series = pd.to_numeric(series, errors="coerce")
        num_value = _coerce_numeric(value)
        if num_value is None:
            raise ValueError(f"Cannot compare {col!r} {op} {value!r}: value is not numeric")
        if op == ">":
            return df[num_series > num_value]
        if op == "<":
            return df[num_series < num_value]
        if op == ">=":
            return df[num_series >= num_value]
        if op == "<=":
            return df[num_series <= num_value]

    if op == "==":
        num_value = _coerce_numeric(value)
        if num_value is not None:
            num_series = pd.to_numeric(series, errors="coerce")
            mask = num_series == num_value
            if mask.any():
                return df[mask]
        return df[series.astype(str) == str(value)]
    if op == "!=":
        num_value = _coerce_numeric(value)
        if num_value is not None:
            num_series = pd.to_numeric(series, errors="coerce")
            return df[num_series != num_value]
        return df[series.astype(str) != str(value)]
    if op == "IN":
        values = (
            list(value) if not isinstance(value, str) else [v.strip() for v in value.split(",")]
        )
        return df[series.isin(values)]
    if op == "NOT IN":
        values = (
            list(value) if not isinstance(value, str) else [v.strip() for v in value.split(",")]
        )
        return df[~series.isin(values)]
    if op == "LIKE":
        pat = str(value).replace("%", ".*")
        return df[series.astype(str).str.contains(pat, case=False, regex=True, na=False)]
    if op == "IS NULL":
        return df[series.isna()]
    if op == "IS NOT NULL":
        return df[series.notna()]
    raise ValueError(f"Unsupported operator: {op!r}")


def _df_to_records(df: pd.DataFrame, limit: int | None = None) -> list[dict]:
    """Convert a DataFrame to a JSON-friendly list of row dicts."""
    if limit is not None:
        df = df.head(limit)
    # Replace NaN with None so json.dumps doesn't choke
    return [
        {k: (None if pd.isna(v) else v) for k, v in row.items()}
        for row in df.to_dict(orient="records")
    ]


# ---------------------------------------------------------------------------
# Layer 0 — CATALOG
# ---------------------------------------------------------------------------


def xql_catalog(files: list[str] | None = None) -> dict:
    """Register every sheet in every given .xlsx file as a queryable table.

    Detects the header row, builds an alias map from config/aliases.yaml,
    and stores the pandas DataFrame in the module-level state dict. Returns
    a catalog summary. Calling it again with the same file rebuilds the
    entry for that file.

    If ``files`` is ``None`` or empty, falls back to files the user attached
    to the current chat turn (set by the server via ``set_uploaded_files``).
    This is the normal path — Claude doesn't need to know disk paths.

    Args:
        files: Explicit .xlsx paths, or None to use attached uploads.

    Returns:
        Dict with keys ``registered`` (list of table_id) and ``tables``
        (list of per-table metadata, same shape as ``xql_describe_table``).
        If no files are available, ``error`` explains what the user should do.
    """
    if not files:
        files = get_uploaded_files()
    if not files:
        return {
            "registered": [],
            "tables": [],
            "error": (
                "No files to catalog. Ask the user to attach an .xlsx "
                "workbook to the chat, then call xql_catalog again."
            ),
        }

    registered: list[str] = []
    table_infos: list[dict] = []

    for file in files:
        path = Path(file).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Workbook not found: {path}")
        stem = path.stem
        xl = pd.ExcelFile(path, engine="openpyxl")
        for sheet in xl.sheet_names:
            raw = xl.parse(sheet, header=None)
            if raw.empty:
                continue
            header_row = _detect_header_row(raw)
            # Promote detected header row to column names
            df = raw.iloc[header_row + 1 :].copy()
            df.columns = [
                str(c) if pd.notna(c) else f"_unnamed_{i}"
                for i, c in enumerate(raw.iloc[header_row])
            ]
            df.reset_index(drop=True, inplace=True)
            alias_map = _build_alias_map(list(df.columns))
            table_id = f"{stem}.{sheet}"
            meta = _TableMeta(
                table_id=table_id,
                file=str(path),
                sheet=sheet,
                header_row=int(header_row),
                df=df,
                alias_map=alias_map,
            )
            _STATE[table_id] = meta
            registered.append(table_id)
            table_infos.append(meta.describe())

    return {"registered": registered, "tables": table_infos}


def xql_list_tables() -> dict:
    """List every table currently in the catalog with its row count."""
    tables = [
        {
            "table_id": m.table_id,
            "file": m.file,
            "sheet": m.sheet,
            "row_count": len(m.df),
            "column_count": len(m.df.columns),
            "aliases": sorted(m.alias_map.keys()),
        }
        for m in _STATE.values()
    ]
    return {"tables": tables, "total": len(tables)}


def xql_describe_table(table_id: str) -> dict:
    """Return schema metadata for a single table."""
    return _get_table(table_id).describe()


# ---------------------------------------------------------------------------
# Layer 1 — QUERY
# ---------------------------------------------------------------------------


def xql_select(table_id: str, limit: int | None = 50) -> dict:
    """Return rows from a table, optionally limited."""
    meta = _get_table(table_id)
    return {
        "table_id": table_id,
        "rows": _df_to_records(meta.df, limit=limit),
        "total_rows": len(meta.df),
    }


def xql_project(table_id: str, columns: list[str], limit: int | None = 50) -> dict:
    """Return only the requested columns. Columns can be aliases or physical names."""
    meta = _get_table(table_id)
    resolved = [_resolve_alias(meta.alias_map, c) for c in columns]
    projected = meta.df[resolved]
    return {
        "table_id": table_id,
        "columns": resolved,
        "rows": _df_to_records(projected, limit=limit),
        "total_rows": len(projected),
    }


def xql_where(
    table_id: str,
    conditions: list[list[Any]],
    limit: int | None = 50,
) -> dict:
    """Filter rows. ``conditions`` is a list of [column, op, value] triples.

    Supported ops: ``==``, ``!=``, ``>``, ``<``, ``>=``, ``<=``, ``IN``,
    ``NOT IN``, ``LIKE`` (``%`` wildcard), ``IS NULL``, ``IS NOT NULL``.
    """
    meta = _get_table(table_id)
    df = meta.df
    for cond in conditions:
        col, op, *rest = cond
        value = rest[0] if rest else None
        physical = _resolve_alias(meta.alias_map, col)
        df = _apply_condition(df, physical, op, value)
    return {
        "table_id": table_id,
        "rows": _df_to_records(df, limit=limit),
        "filtered_rows": len(df),
        "total_rows": len(meta.df),
    }


def xql_order(
    table_id: str,
    by: str,
    ascending: bool = True,
    limit: int | None = 50,
) -> dict:
    """Sort a table by a column (alias or physical name)."""
    meta = _get_table(table_id)
    physical = _resolve_alias(meta.alias_map, by)
    # Try numeric sort; fall back to string sort
    try:
        sort_key = pd.to_numeric(meta.df[physical], errors="raise")
        sorted_df = (
            meta.df.assign(_sort=sort_key)
            .sort_values("_sort", ascending=ascending)
            .drop(columns="_sort")
        )
    except (ValueError, TypeError):
        sorted_df = meta.df.sort_values(physical, ascending=ascending)
    return {
        "table_id": table_id,
        "rows": _df_to_records(sorted_df, limit=limit),
        "total_rows": len(sorted_df),
    }


def xql_distinct(table_id: str, columns: list[str]) -> dict:
    """Return unique combinations of the given columns."""
    meta = _get_table(table_id)
    resolved = [_resolve_alias(meta.alias_map, c) for c in columns]
    unique = meta.df[resolved].drop_duplicates().reset_index(drop=True)
    return {
        "table_id": table_id,
        "columns": resolved,
        "rows": _df_to_records(unique, limit=None),
        "unique_count": len(unique),
    }


def xql_group(
    table_id: str,
    group_by: list[str],
    agg: dict[str, str] | None = None,
    having: dict | None = None,
    limit: int | None = 50,
    # Flat form for LLM tool calls — Gemini's schema can't express free-form
    # object maps, so we accept parallel arrays + a single-condition having.
    agg_columns: list[str] | None = None,
    agg_functions: list[str] | None = None,
    having_column: str | None = None,
    having_op: str | None = None,
    having_value: Any = None,
) -> dict:
    """GROUP BY + aggregation.

    Accepts two equivalent call styles:

    1. **Dict form** (Python/tests):
       ``agg={"amount": "sum", "material": "count"}``,
       ``having={"amount_sum": [">", 1000]}``.

    2. **Flat form** (LLM tool calls): parallel ``agg_columns`` +
       ``agg_functions`` arrays, plus a single ``having_column`` /
       ``having_op`` / ``having_value`` triple. Gemini's tool schema
       doesn't support free-form object maps, so this is the shape
       the LLM uses.

    Args:
        table_id: Table to operate on.
        group_by: Columns (aliases or physical) to group by.
        agg: Dict mapping of column -> aggregation function. Supported:
            ``sum``, ``count``, ``mean``, ``min``, ``max``, ``first``,
            ``last``, ``nunique``, ``list``. Mutually exclusive with
            ``agg_columns``/``agg_functions``.
        having: Optional filter on aggregated result.
            Format: ``{"<col>_<agg>": ["op", value]}``.
        limit: Max rows in the response (None for all).
        agg_columns: Parallel to ``agg_functions``. Columns to aggregate.
        agg_functions: Parallel to ``agg_columns``. Functions per column.
        having_column: Aggregated column name (e.g. ``"amount_sum"``).
        having_op: Comparison operator for HAVING (e.g. ``">"``).
        having_value: Comparison value (stringified for LLM use).
    """
    # Resolve agg from flat form if dict not provided
    if agg is None and (agg_columns or agg_functions):
        if not (agg_columns and agg_functions):
            raise ValueError("agg_columns and agg_functions must both be provided.")
        if len(agg_columns) != len(agg_functions):
            raise ValueError(
                f"agg_columns ({len(agg_columns)}) and agg_functions "
                f"({len(agg_functions)}) must have equal length."
            )
        agg = dict(zip(agg_columns, agg_functions, strict=True))
    if agg is None:
        raise ValueError("Provide either agg={col: fn} or both agg_columns and agg_functions.")

    # Resolve having from flat form if dict not provided
    if having is None and having_column and having_op:
        having = {having_column: [having_op, having_value]}

    meta = _get_table(table_id)
    group_cols = [_resolve_alias(meta.alias_map, c) for c in group_by]
    resolved_agg = {_resolve_alias(meta.alias_map, c): fn for c, fn in agg.items()}

    # Coerce numeric columns for numeric aggregations
    df = meta.df.copy()
    for col, fn in resolved_agg.items():
        if fn in {"sum", "mean", "min", "max"}:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    grouped = df.groupby(group_cols, dropna=False).agg(resolved_agg).reset_index()
    # Flatten column names: "<col>_<agg>"
    grouped.columns = [
        f"{col}_{resolved_agg[col]}" if col in resolved_agg else col for col in grouped.columns
    ]

    if having:
        for col, (op, value) in having.items():
            grouped = _apply_condition(grouped, col, op, value)

    return {
        "table_id": table_id,
        "group_by": group_cols,
        "rows": _df_to_records(grouped, limit=limit),
        "total_rows": len(grouped),
    }


def xql_pareto(
    table_id: str,
    group_by: str,
    value_col: str = "amount",
    threshold: float = 0.80,
    filter: list[list[Any]] | None = None,
    rest_bucket: str | None = None,
) -> dict:
    """Compute an 80/20 Pareto breakdown.

    Groups rows by ``group_by``, sums ``value_col``, sorts descending,
    and returns items whose cumulative share reaches ``threshold``. The
    remaining items are rolled into a single "rest" row labeled by
    ``rest_bucket`` (default comes from config/lci_rules.yaml).
    """
    meta = _get_table(table_id)
    df = meta.df.copy()

    if filter:
        for cond in filter:
            col, op, *rest = cond
            value = rest[0] if rest else None
            physical = _resolve_alias(meta.alias_map, col)
            df = _apply_condition(df, physical, op, value)

    group_col = _resolve_alias(meta.alias_map, group_by)
    value_physical = _resolve_alias(meta.alias_map, value_col)
    df[value_physical] = pd.to_numeric(df[value_physical], errors="coerce").fillna(0)

    summed = (
        df.groupby(group_col, dropna=False)[value_physical]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
    )
    total = float(summed[value_physical].sum()) or 1.0
    summed["share"] = summed[value_physical] / total
    summed["cumulative"] = summed["share"].cumsum()

    bucket_label = rest_bucket or _RULES_CFG.get("pareto", {}).get("bucket_name", "Lainnya")

    # Everything that lies strictly before the threshold is a hotspot,
    # plus the first item that crosses the threshold.
    hotspot_mask = summed["cumulative"] <= threshold
    if not hotspot_mask.any():
        hotspot_mask.iloc[0] = True
    else:
        # Include the item that pushes cumulative past the threshold
        last_true = hotspot_mask[hotspot_mask].index[-1]
        if last_true + 1 < len(summed) and summed.loc[last_true, "cumulative"] < threshold:
            hotspot_mask.iloc[last_true + 1] = True

    hotspots = summed[hotspot_mask].copy()
    rest = summed[~hotspot_mask]

    result_rows = _df_to_records(hotspots)
    if len(rest) > 0:
        result_rows.append(
            {
                group_col: bucket_label,
                value_physical: float(rest[value_physical].sum()),
                "share": float(rest["share"].sum()),
                "cumulative": 1.0,
            }
        )

    return {
        "table_id": table_id,
        "group_by": group_col,
        "value_col": value_physical,
        "threshold": threshold,
        "total": total,
        "hotspot_count": int(hotspot_mask.sum()),
        "rest_count": int((~hotspot_mask).sum()),
        "rows": result_rows,
    }


# ---------------------------------------------------------------------------
# Layer 2 — TRANSFORM
# ---------------------------------------------------------------------------


def xql_join(
    left: str,
    right: str,
    on: list[str],
    how: str = "inner",
    limit: int | None = 50,
) -> dict:
    """Join two tables on alias columns. Columns are resolved per side."""
    lmeta = _get_table(left)
    rmeta = _get_table(right)
    left_on = [_resolve_alias(lmeta.alias_map, c) for c in on]
    right_on = [_resolve_alias(rmeta.alias_map, c) for c in on]

    merged = pd.merge(
        lmeta.df,
        rmeta.df,
        left_on=left_on,
        right_on=right_on,
        how=how,
        suffixes=("_left", "_right"),
    )
    return {
        "left": left,
        "right": right,
        "on": on,
        "how": how,
        "rows": _df_to_records(merged, limit=limit),
        "matched_rows": len(merged),
    }


def xql_union(tables: list[str], align_by: str = "alias", limit: int | None = 50) -> dict:
    """Stack tables vertically. ``align_by`` is "alias" (default) or "column"."""
    frames: list[pd.DataFrame] = []
    for table_id in tables:
        meta = _get_table(table_id)
        if align_by == "alias":
            # Rename physical columns to logical aliases where possible
            reverse = {phys: alias for alias, phys in meta.alias_map.items()}
            renamed = meta.df.rename(columns=reverse)
            frames.append(renamed)
        else:
            frames.append(meta.df)
    stacked = pd.concat(frames, ignore_index=True, sort=False)
    return {
        "tables": tables,
        "align_by": align_by,
        "rows": _df_to_records(stacked, limit=limit),
        "total_rows": len(stacked),
    }


def xql_pivot(
    table_id: str,
    index: str,
    columns: str,
    values: str,
    aggfunc: str = "sum",
    limit: int | None = 50,
) -> dict:
    """Reshape a table — index rows, columns columns, aggregated values."""
    meta = _get_table(table_id)
    idx = _resolve_alias(meta.alias_map, index)
    col = _resolve_alias(meta.alias_map, columns)
    val = _resolve_alias(meta.alias_map, values)

    df = meta.df.copy()
    df[val] = pd.to_numeric(df[val], errors="coerce")

    pivoted = df.pivot_table(
        index=idx, columns=col, values=val, aggfunc=aggfunc, fill_value=0
    ).reset_index()
    pivoted.columns = [str(c) for c in pivoted.columns]
    return {
        "table_id": table_id,
        "rows": _df_to_records(pivoted, limit=limit),
        "total_rows": len(pivoted),
    }


def xql_build_io_table(
    source: str,
    products: dict | None = None,
    exclude_process: list[str] | None = None,
    pareto_threshold: float | None = None,
    # LLM-friendly alias for products — Gemini's schema can't express
    # nested object maps with unknown keys, so the LLM passes a JSON
    # string that we decode here.
    products_json: str | None = None,
) -> dict:
    """Build an LCI Input-Output table from a source LDI sheet.

    Applies category-specific grouping rules from ``config/lci_rules.yaml``,
    excludes processes matching regex patterns, computes amount totals per
    group, and applies a Pareto cut to each category.

    Args:
        source: Catalog table_id of the source LDI sheet.
        products: Dict ``{product_name: {amount, unit, energy_factor,
            energy_unit}}`` used for functional-unit columns in the output.
            Mutually exclusive with ``products_json``.
        exclude_process: Optional list of regex patterns to drop before
            aggregation. Defaults come from ``default_exclude_process``.
        pareto_threshold: Cumulative share cut-off. Defaults to
            ``pareto.default_threshold`` in lci_rules.yaml.
        products_json: JSON-encoded version of ``products`` for LLM callers
            (Gemini tool schemas can't express nested object maps with
            unknown keys). Passed straight through ``json.loads``.

    Returns:
        Dict with ``categories`` (one entry per category with grouped rows,
        totals, and Pareto selection) and ``products`` echoed back.
    """
    if products is None and products_json:
        try:
            products = json.loads(products_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"products_json is not valid JSON: {e}") from e
    if products is None:
        products = {}
    if not isinstance(products, dict):
        raise TypeError(f"products must be a dict, got {type(products).__name__}")

    meta = _get_table(source)
    df = meta.df.copy()

    category_col = _resolve_alias(meta.alias_map, "category")
    process_col = _resolve_alias(meta.alias_map, "process")
    material_col = _resolve_alias(meta.alias_map, "material")
    amount_col = _resolve_alias(meta.alias_map, "amount")

    # Exclude rows
    patterns = exclude_process or _RULES_CFG.get("default_exclude_process", [])
    for pat in patterns:
        mask = ~df[process_col].astype(str).str.fullmatch(pat, na=False)
        df = df[mask]

    df[amount_col] = pd.to_numeric(df[amount_col], errors="coerce").fillna(0)

    grouping_rules = _RULES_CFG.get("grouping_rules", {})
    threshold = pareto_threshold
    if threshold is None:
        threshold = _RULES_CFG.get("pareto", {}).get("default_threshold", 0.80)
    bucket_name = _RULES_CFG.get("pareto", {}).get("bucket_name", "Lainnya")

    categories_out: list[dict] = []
    for category_value, cat_df in df.groupby(category_col, dropna=False):
        rule = grouping_rules.get(category_value, grouping_rules.get("*", "material"))
        if rule == "produced_from":
            group_col = meta.alias_map.get("produced_from", material_col)
        elif rule == "semantic":
            # Fall back to material — callers that need real semantic
            # groupings should override via a separate tool call.
            group_col = material_col
        else:
            group_col = material_col

        summed = (
            cat_df.groupby(group_col, dropna=False)[amount_col]
            .sum()
            .sort_values(ascending=False)
            .reset_index()
        )
        total = float(summed[amount_col].sum()) or 1.0
        summed["share"] = summed[amount_col] / total
        summed["cumulative"] = summed["share"].cumsum()

        hotspot_mask = summed["cumulative"] <= threshold
        if not hotspot_mask.any():
            hotspot_mask.iloc[0] = True

        hotspots = summed[hotspot_mask]
        rest = summed[~hotspot_mask]
        rows = _df_to_records(hotspots)
        if len(rest) > 0:
            rows.append(
                {
                    group_col: bucket_name,
                    amount_col: float(rest[amount_col].sum()),
                    "share": float(rest["share"].sum()),
                    "cumulative": 1.0,
                }
            )

        categories_out.append(
            {
                "category": category_value,
                "rule": rule,
                "grouped_by": group_col,
                "total": total,
                "hotspot_count": int(hotspot_mask.sum()),
                "rows": rows,
            }
        )

    return {
        "source": source,
        "pareto_threshold": threshold,
        "exclude_process": patterns,
        "products": products,
        "categories": categories_out,
    }


# ---------------------------------------------------------------------------
# Schemas — every tool that gets registered must declare a JSON schema
# named <TOOL_NAME_UPPER>_SCHEMA. BaseAgent's Skill loader discovers the
# (name, callable, schema) triples automatically.
# ---------------------------------------------------------------------------


def _fn_schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
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


XQL_CATALOG_SCHEMA = _fn_schema(
    "xql_catalog",
    "Register every sheet in each given .xlsx file as a queryable table. "
    "Must be called before any other xql_* tool. Call with no arguments "
    "(or files=[]) to catalog whatever the user has attached to the chat.",
    {
        "files": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Optional. Explicit .xlsx paths. If omitted, the server "
                "will use files attached to the current chat turn."
            ),
        }
    },
    [],
)

XQL_LIST_TABLES_SCHEMA = _fn_schema(
    "xql_list_tables",
    "List every table currently in the catalog.",
    {},
    [],
)

XQL_DESCRIBE_TABLE_SCHEMA = _fn_schema(
    "xql_describe_table",
    "Return schema metadata (columns, aliases, dtypes) for one table.",
    {"table_id": {"type": "string", "description": "Catalog table id"}},
    ["table_id"],
)

XQL_SELECT_SCHEMA = _fn_schema(
    "xql_select",
    "Return rows from a table. Pass limit=null for all rows.",
    {
        "table_id": {"type": "string"},
        "limit": {"type": "integer", "description": "Max rows (default 50)"},
    },
    ["table_id"],
)

XQL_PROJECT_SCHEMA = _fn_schema(
    "xql_project",
    "Return only the requested columns. Columns can be aliases.",
    {
        "table_id": {"type": "string"},
        "columns": {"type": "array", "items": {"type": "string"}},
        "limit": {"type": "integer"},
    },
    ["table_id", "columns"],
)

XQL_WHERE_SCHEMA = _fn_schema(
    "xql_where",
    "Filter rows. conditions is a list of [column, op, value] triples. "
    "Supported ops: ==, !=, >, <, >=, <=, IN, NOT IN, LIKE, IS NULL, IS NOT NULL. "
    'All three parts are strings — numeric values like "100" are auto-coerced.',
    {
        "table_id": {"type": "string"},
        "conditions": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "string"},
            },
            "description": (
                "List of [column, op, value] triples. Example: "
                '[["category", "==", "Liquid Fuels"], '
                '["amount", ">", "100"]]'
            ),
        },
        "limit": {"type": "integer"},
    },
    ["table_id", "conditions"],
)

XQL_ORDER_SCHEMA = _fn_schema(
    "xql_order",
    "Sort rows by a column.",
    {
        "table_id": {"type": "string"},
        "by": {"type": "string"},
        "ascending": {"type": "boolean", "default": True},
        "limit": {"type": "integer"},
    },
    ["table_id", "by"],
)

XQL_DISTINCT_SCHEMA = _fn_schema(
    "xql_distinct",
    "Return unique combinations of the given columns.",
    {
        "table_id": {"type": "string"},
        "columns": {"type": "array", "items": {"type": "string"}},
    },
    ["table_id", "columns"],
)

XQL_GROUP_SCHEMA = _fn_schema(
    "xql_group",
    "GROUP BY + aggregation. Supported aggregations: sum, count, mean, min, "
    "max, first, last, nunique, list. Optional single-condition HAVING filter.",
    {
        "table_id": {"type": "string"},
        "group_by": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Columns to group by (aliases or physical names).",
        },
        "agg_columns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Parallel to agg_functions: columns to aggregate.",
        },
        "agg_functions": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Parallel to agg_columns: function per column. One of: "
                "sum, count, mean, min, max, first, last, nunique, list."
            ),
        },
        "having_column": {
            "type": "string",
            "description": (
                "Optional. Aggregated column name for HAVING filter, "
                "e.g. 'amount_sum' (agg-name suffix included)."
            ),
        },
        "having_op": {
            "type": "string",
            "description": "Optional. Comparison op for HAVING: ==, !=, >, <, >=, <=.",
        },
        "having_value": {
            "type": "string",
            "description": "Optional. Comparison value for HAVING (auto-coerced).",
        },
        "limit": {"type": "integer"},
    },
    ["table_id", "group_by", "agg_columns", "agg_functions"],
)

XQL_PARETO_SCHEMA = _fn_schema(
    "xql_pareto",
    "80/20 Pareto breakdown: sums value_col by group_by and returns the "
    "hotspots plus a rest-of-distribution bucket. Same filter format as "
    "xql_where — list of [column, op, value] triples.",
    {
        "table_id": {"type": "string"},
        "group_by": {"type": "string"},
        "value_col": {
            "type": "string",
            "description": "Column to sum (default 'amount').",
        },
        "threshold": {
            "type": "number",
            "description": "Cumulative share cut-off, default 0.80.",
        },
        "filter": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "string"},
            },
            "description": (
                "Optional pre-aggregation filter. Same format as "
                "xql_where.conditions: list of [col, op, value] triples."
            ),
        },
        "rest_bucket": {
            "type": "string",
            "description": "Label for the rest-of-distribution bucket (default 'Lainnya').",
        },
    },
    ["table_id", "group_by"],
)

XQL_JOIN_SCHEMA = _fn_schema(
    "xql_join",
    "Join two tables on alias columns. how: inner, left, right, outer.",
    {
        "left": {"type": "string"},
        "right": {"type": "string"},
        "on": {"type": "array", "items": {"type": "string"}},
        "how": {"type": "string", "default": "inner"},
        "limit": {"type": "integer"},
    },
    ["left", "right", "on"],
)

XQL_UNION_SCHEMA = _fn_schema(
    "xql_union",
    "Stack tables vertically, aligning by alias (default) or raw column name.",
    {
        "tables": {"type": "array", "items": {"type": "string"}},
        "align_by": {"type": "string", "default": "alias"},
        "limit": {"type": "integer"},
    },
    ["tables"],
)

XQL_PIVOT_SCHEMA = _fn_schema(
    "xql_pivot",
    "Reshape: group rows by index, pivot columns, aggregate values.",
    {
        "table_id": {"type": "string"},
        "index": {"type": "string"},
        "columns": {"type": "string"},
        "values": {"type": "string"},
        "aggfunc": {"type": "string", "default": "sum"},
        "limit": {"type": "integer"},
    },
    ["table_id", "index", "columns", "values"],
)

XQL_BUILD_IO_TABLE_SCHEMA = _fn_schema(
    "xql_build_io_table",
    "Build an LCI IO Table from a source sheet, applying category-specific "
    "grouping rules, process exclusions, and a Pareto cut per category.",
    {
        "source": {
            "type": "string",
            "description": "Catalog table_id of the source LDI sheet.",
        },
        "products_json": {
            "type": "string",
            "description": (
                "Optional JSON object declaring the products used for FU "
                'columns. Example: \'{"Crude Oil": {"amount": 369113.5, '
                '"unit": "barrel"}}\'. Empty or omitted means no FU columns.'
            ),
        },
        "exclude_process": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Regex patterns for processes to skip (default: CSR.*).",
        },
        "pareto_threshold": {
            "type": "number",
            "description": "Pareto cumulative share cut-off, default 0.80.",
        },
    },
    ["source"],
)
