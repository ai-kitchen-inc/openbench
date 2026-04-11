"""Tools for the query-explorer SDK skill.

Pure-Python (stdlib only) filter / sort / group / aggregate over lists
of dict records. Every tool accepts a ``records: list[dict]`` argument
and returns a ``list[dict]`` (or a thin wrapper dict for summary-style
results), so operations compose freely in an agent's reasoning loop.

The tools are intentionally permissive about missing keys — a row that
lacks the queried column is simply skipped, not raised. This matches
the behaviour of most LCI/analytics workbooks where column availability
drifts row-to-row.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "filter_records",
    "sort_records",
    "group_and_aggregate",
    "distinct_values",
    "top_n_records",
    "FILTER_RECORDS_SCHEMA",
    "SORT_RECORDS_SCHEMA",
    "GROUP_AND_AGGREGATE_SCHEMA",
    "DISTINCT_VALUES_SCHEMA",
    "TOP_N_RECORDS_SCHEMA",
]


_SUPPORTED_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "contains"}
_SUPPORTED_AGGS = {"sum", "mean", "avg", "count", "min", "max"}


def _error(message: str) -> dict[str, Any]:
    return {"error": message}


# ---------------------------------------------------------------------------
# filter_records
# ---------------------------------------------------------------------------


def _row_matches(row: dict[str, Any], conditions: list[dict[str, Any]]) -> bool:
    """Return True if a row satisfies every condition in the list.

    Conditions that reference a missing column cause the row to be
    excluded (strict AND semantics over present columns).
    """
    for cond in conditions:
        col = cond.get("column")
        op = cond.get("op", "eq")
        target = cond.get("value")
        if col is None or col not in row:
            return False
        value = row[col]
        if op == "eq":
            if value != target:
                return False
        elif op == "ne":
            if value == target:
                return False
        elif op == "gt":
            if not (_as_number(value) is not None and _as_number(value) > _as_number(target)):
                return False
        elif op == "gte":
            if not (_as_number(value) is not None and _as_number(value) >= _as_number(target)):
                return False
        elif op == "lt":
            if not (_as_number(value) is not None and _as_number(value) < _as_number(target)):
                return False
        elif op == "lte":
            if not (_as_number(value) is not None and _as_number(value) <= _as_number(target)):
                return False
        elif op == "in":
            if not isinstance(target, list) or value not in target:
                return False
        elif op == "contains":
            if not (isinstance(value, str) and isinstance(target, str) and target in value):
                return False
        else:
            return False
    return True


def _as_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def filter_records(
    records: list[dict[str, Any]],
    conditions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Keep rows matching ALL conditions (AND semantics).

    Each condition is a dict::

        {"column": "...", "op": "eq|ne|gt|gte|lt|lte|in|contains", "value": ...}

    Op defaults to ``"eq"`` if omitted.

    Args:
        records: List of row dicts.
        conditions: List of condition dicts.

    Returns:
        ``{"records": [...], "count": int}`` or ``{"error": "..."}``.
    """
    if not isinstance(records, list):
        return _error("`records` must be a list of dicts")
    if not isinstance(conditions, list):
        return _error("`conditions` must be a list of condition dicts")
    for i, c in enumerate(conditions):
        if not isinstance(c, dict):
            return _error(f"conditions[{i}] is not a dict")
        op = c.get("op", "eq")
        if op not in _SUPPORTED_OPS:
            return _error(
                f"conditions[{i}] unsupported op {op!r}; use one of {sorted(_SUPPORTED_OPS)}"
            )

    matched = [row for row in records if isinstance(row, dict) and _row_matches(row, conditions)]
    return {"records": matched, "count": len(matched)}


# ---------------------------------------------------------------------------
# sort_records
# ---------------------------------------------------------------------------


def sort_records(
    records: list[dict[str, Any]],
    by: str,
    descending: bool = False,
) -> dict[str, Any]:
    """Sort records by one key. Rows missing the key are placed last."""
    if not isinstance(records, list):
        return _error("`records` must be a list")
    present = [r for r in records if isinstance(r, dict) and by in r]
    missing = [r for r in records if isinstance(r, dict) and by not in r]
    try:
        present.sort(key=lambda r: (r[by] is None, r[by]), reverse=descending)
    except TypeError:
        # Mixed types — fall back to string sort
        present.sort(key=lambda r: (r[by] is None, str(r[by])), reverse=descending)
    return {"records": present + missing, "count": len(records)}


# ---------------------------------------------------------------------------
# group_and_aggregate
# ---------------------------------------------------------------------------


def _aggregate(values: list[Any], op: str) -> Any:
    nums = [_as_number(v) for v in values]
    nums = [v for v in nums if v is not None]
    if op == "count":
        return len(values)
    if not nums:
        return None
    if op == "sum":
        return sum(nums)
    if op in ("mean", "avg"):
        return sum(nums) / len(nums)
    if op == "min":
        return min(nums)
    if op == "max":
        return max(nums)
    return None


def group_and_aggregate(
    records: list[dict[str, Any]],
    group_by: str,
    aggregate: str,
    aggregate_column: str | None = None,
) -> dict[str, Any]:
    """Group rows by one column and aggregate another.

    Args:
        records: List of row dicts.
        group_by: Column to group by.
        aggregate: One of ``sum``, ``mean`` (aka ``avg``), ``count``,
            ``min``, ``max``.
        aggregate_column: Column to aggregate. Required for every
            op except ``count``.

    Returns:
        ``{"groups": [{"<group_by>": key, "<agg>_<col>": value, "count": n}, ...]}``
        or an error dict.
    """
    if aggregate not in _SUPPORTED_AGGS:
        return _error(f"aggregate must be one of {sorted(_SUPPORTED_AGGS)}")
    if aggregate != "count" and not aggregate_column:
        return _error("aggregate_column is required for every op except 'count'")
    if not isinstance(records, list):
        return _error("`records` must be a list")

    buckets: dict[Any, list[Any]] = {}
    group_counts: dict[Any, int] = {}
    for row in records:
        if not isinstance(row, dict) or group_by not in row:
            continue
        key = row[group_by]
        group_counts[key] = group_counts.get(key, 0) + 1
        buckets.setdefault(key, [])
        if aggregate_column and aggregate_column in row:
            buckets[key].append(row[aggregate_column])

    agg_col = aggregate_column or "*"
    agg_key = f"{aggregate}_{agg_col}"
    groups_out: list[dict[str, Any]] = []
    for key, values in buckets.items():
        if aggregate == "count":
            # "count" is always the number of rows in the group,
            # independent of any aggregate_column.
            result: Any = group_counts[key]
        else:
            result = _aggregate(values, aggregate)
        groups_out.append(
            {
                group_by: key,
                agg_key: result,
                "count": group_counts.get(key, 0),
            }
        )
    return {"groups": groups_out, "group_by": group_by, "aggregate": aggregate}


# ---------------------------------------------------------------------------
# distinct_values
# ---------------------------------------------------------------------------


def distinct_values(records: list[dict[str, Any]], column: str) -> dict[str, Any]:
    """Return unique values in ``column`` in first-seen order."""
    if not isinstance(records, list):
        return _error("`records` must be a list")
    seen: list[Any] = []
    seen_set: set[Any] = set()
    for row in records:
        if not isinstance(row, dict) or column not in row:
            continue
        value = row[column]
        try:
            if value in seen_set:
                continue
            seen_set.add(value)
        except TypeError:
            # Unhashable — fall back to linear scan
            if value in seen:
                continue
        seen.append(value)
    return {"column": column, "values": seen, "count": len(seen)}


# ---------------------------------------------------------------------------
# top_n_records
# ---------------------------------------------------------------------------


def top_n_records(
    records: list[dict[str, Any]],
    by: str,
    n: int = 10,
    descending: bool = True,
) -> dict[str, Any]:
    """Return the N rows with the largest (or smallest) value in ``by``."""
    if not isinstance(records, list):
        return _error("`records` must be a list")
    if n <= 0:
        return _error("`n` must be positive")

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in records:
        if not isinstance(row, dict) or by not in row:
            continue
        num = _as_number(row[by])
        if num is None:
            continue
        scored.append((num, row))
    scored.sort(key=lambda t: t[0], reverse=descending)
    top = [row for _, row in scored[:n]]
    return {"records": top, "count": len(top), "by": by}


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


_RECORDS_PROP = {
    "type": "array",
    "description": "List of row dicts to operate on.",
    "items": {"type": "object"},
}


FILTER_RECORDS_SCHEMA = _schema(
    "filter_records",
    "Keep rows that satisfy every condition (AND semantics). Each condition "
    "is a dict with keys {column, op, value}; op defaults to 'eq'.",
    {
        "records": _RECORDS_PROP,
        "conditions": {
            "type": "array",
            "description": "List of condition dicts: {column, op, value}. op is one of eq, ne, gt, gte, lt, lte, in, contains.",
            "items": {"type": "object"},
        },
    },
    ["records", "conditions"],
)

SORT_RECORDS_SCHEMA = _schema(
    "sort_records",
    "Sort rows by one key. Rows missing the key end up last.",
    {
        "records": _RECORDS_PROP,
        "by": {"type": "string", "description": "Column to sort by"},
        "descending": {"type": "boolean", "description": "Default false"},
    },
    ["records", "by"],
)

GROUP_AND_AGGREGATE_SCHEMA = _schema(
    "group_and_aggregate",
    "Group records by one column and aggregate another. Supported ops: "
    "sum, mean (avg), count, min, max. `aggregate_column` is required "
    "for every op except 'count'.",
    {
        "records": _RECORDS_PROP,
        "group_by": {"type": "string"},
        "aggregate": {
            "type": "string",
            "enum": ["sum", "mean", "avg", "count", "min", "max"],
        },
        "aggregate_column": {"type": "string"},
    },
    ["records", "group_by", "aggregate"],
)

DISTINCT_VALUES_SCHEMA = _schema(
    "distinct_values",
    "Return unique values in one column, in first-seen order.",
    {
        "records": _RECORDS_PROP,
        "column": {"type": "string"},
    },
    ["records", "column"],
)

TOP_N_RECORDS_SCHEMA = _schema(
    "top_n_records",
    "Return the N rows with the largest (or smallest) numeric value in `by`.",
    {
        "records": _RECORDS_PROP,
        "by": {"type": "string"},
        "n": {"type": "integer", "description": "Number of rows to return (default 10)"},
        "descending": {"type": "boolean", "description": "Default true (largest first)"},
    },
    ["records", "by"],
)
