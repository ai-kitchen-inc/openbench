"""Live dashboard record + input validation.

A live dashboard is a *template* (KPIs and panels that reference dataset
keys) plus the *queries* that produce those datasets. The scheduler re-runs
the queries, hydrates the template through the shared dashboard normalizer
(which inlines ``dataset`` references into panel ``data``) and stores the
result as the current ``snapshot``.

The template is kept un-normalized on purpose: the normalizer resolves KPI
values from ``dataset`` + ``value_column`` and drops the reference, so a
canonical ViewModel could not be re-hydrated with fresh rows.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from general_chat.live_dashboard.sqlguard import MAX_SQL_CHARS, is_select_only, is_valid_dataset_key

ID_RE = re.compile(r"^[0-9a-f]{12}$")

MIN_REFRESH_INTERVAL_SECONDS = 15
MAX_REFRESH_INTERVAL_SECONDS = 86_400
DEFAULT_REFRESH_INTERVAL_SECONDS = 60
MAX_QUERIES = 20
DEFAULT_QUERY_MAX_ROWS = 500
MAX_QUERY_MAX_ROWS = 5_000
MAX_TITLE_CHARS = 200
MAX_DESCRIPTION_CHARS = 2_000
# Shown to viewers instead of raw driver errors (owners see the detail).
PUBLIC_ERROR_TEXT = "query failed"

# Keys the dashboard normalizer / ObDashboardFrame accept as a dataset reference.
_DATASET_REF_KEYS = (
    "dataset",
    "dataset_id",
    "datasetId",
    "dataKey",
    "source_dataset",
    "sourceDataset",
    "source",
)
_ITEM_LIST_KEYS = ("items", "components", "widgets", "panels", "cards", "charts")
_TEMPLATE_STRIPPED_KEYS = frozenset({"datasets", "queries", "title", "description"})


class LiveDashboardValidationError(ValueError):
    """User-safe validation failure (message is shown to the agent / API caller)."""


def new_dashboard_id() -> str:
    """12 hex chars: the same shape ``PublishStore`` uses for ``/d/{id}``."""
    return uuid.uuid4().hex[:12]


def utc_now_iso(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def clamp_refresh_interval(value: Any) -> int:
    """0 means manual; anything else lands in [MIN, MAX]."""
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise LiveDashboardValidationError("refresh_interval_seconds must be an integer") from exc
    if seconds <= 0:
        return 0
    return max(MIN_REFRESH_INTERVAL_SECONDS, min(MAX_REFRESH_INTERVAL_SECONDS, seconds))


@dataclass
class LiveQuery:
    """One SQL statement feeding one dataset key."""

    sql: str
    max_rows: int = DEFAULT_QUERY_MAX_ROWS

    def to_dict(self) -> dict[str, Any]:
        return {"sql": self.sql, "maxRows": self.max_rows}

    @classmethod
    def from_value(cls, value: Any) -> LiveQuery:
        if isinstance(value, str):
            return cls(sql=value)
        if isinstance(value, dict):
            raw_rows = value.get("maxRows", value.get("max_rows", DEFAULT_QUERY_MAX_ROWS))
            try:
                max_rows = int(raw_rows)
            except (TypeError, ValueError):
                max_rows = DEFAULT_QUERY_MAX_ROWS
            return cls(
                sql=str(value.get("sql") or ""),
                max_rows=max(1, min(MAX_QUERY_MAX_ROWS, max_rows)),
            )
        raise LiveDashboardValidationError("each query must be a SQL string or {sql, maxRows}")


@dataclass
class LiveDashboardRecord:
    """Persisted live dashboard: definition + schedule + latest snapshot."""

    id: str
    owner: str
    title: str
    description: str = ""
    server_id: str = ""
    namespace: str = "db_server"
    queries: dict[str, LiveQuery] = field(default_factory=dict)
    template: dict[str, Any] = field(default_factory=dict)
    refresh_interval_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS
    enabled: bool = True
    public: bool = False
    version: int = 0
    data_hash: str = ""
    snapshot: dict[str, Any] = field(default_factory=dict)
    last_refresh_at: str | None = None
    last_error: str | None = None
    next_run_at: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    # -- serialization -------------------------------------------------------

    def to_dict(self, *, include_snapshot: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "owner": self.owner,
            "title": self.title,
            "description": self.description,
            "serverId": self.server_id,
            "namespace": self.namespace,
            "queries": {key: query.to_dict() for key, query in self.queries.items()},
            "template": self.template,
            "refreshIntervalSeconds": self.refresh_interval_seconds,
            "enabled": self.enabled,
            "public": self.public,
            "version": self.version,
            "dataHash": self.data_hash,
            "lastRefreshAt": self.last_refresh_at,
            "lastError": self.last_error,
            "nextRunAt": self.next_run_at,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        if include_snapshot:
            payload["snapshot"] = self.snapshot
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LiveDashboardRecord:
        raw_queries = data.get("queries") or {}
        queries = (
            {str(key): LiveQuery.from_value(value) for key, value in raw_queries.items()}
            if isinstance(raw_queries, dict)
            else {}
        )
        template = data.get("template")
        snapshot = data.get("snapshot")
        return cls(
            id=str(data.get("id") or ""),
            owner=str(data.get("owner") or ""),
            title=str(data.get("title") or "Dashboard"),
            description=str(data.get("description") or ""),
            server_id=str(data.get("serverId") or data.get("server_id") or ""),
            namespace=str(data.get("namespace") or "db_server"),
            queries=queries,
            template=template if isinstance(template, dict) else {},
            refresh_interval_seconds=clamp_refresh_interval(
                data.get("refreshIntervalSeconds", data.get("refresh_interval_seconds", 60))
            ),
            enabled=bool(data.get("enabled", True)),
            public=bool(data.get("public", False)),
            version=int(data.get("version") or 0),
            data_hash=str(data.get("dataHash") or data.get("data_hash") or ""),
            snapshot=snapshot if isinstance(snapshot, dict) else {},
            last_refresh_at=data.get("lastRefreshAt") or data.get("last_refresh_at"),
            last_error=data.get("lastError") or data.get("last_error"),
            next_run_at=data.get("nextRunAt") or data.get("next_run_at"),
            created_at=str(data.get("createdAt") or data.get("created_at") or utc_now_iso()),
            updated_at=str(data.get("updatedAt") or data.get("updated_at") or utc_now_iso()),
        )

    def public_payload(self) -> dict[str, Any]:
        """What viewers (SSE / public page) receive.

        Never queries, owner or server id. The ViewModel is sent WITHOUT its
        ``datasets`` map (panels already carry the rows they display; the map
        would hand every query's full result to anonymous visitors). Error
        text is reduced to a generic marker -- driver messages can leak
        schema or host details; owners read the detail via ``to_dict``.
        """
        raw_view_model = self.snapshot.get("viewModel")
        view_model = (
            {key: value for key, value in raw_view_model.items() if key != "datasets"}
            if isinstance(raw_view_model, dict)
            else {}
        )
        errors = self.snapshot.get("errors")
        public_errors = (
            {str(key): PUBLIC_ERROR_TEXT for key in errors} if isinstance(errors, dict) else {}
        )
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "viewModel": view_model,
            "version": self.version,
            "refreshedAt": self.snapshot.get("refreshedAt") or self.last_refresh_at,
            "refreshIntervalSeconds": self.refresh_interval_seconds,
            "enabled": self.enabled,
            "public": self.public,
            "errors": public_errors,
            "lastError": PUBLIC_ERROR_TEXT if self.last_error else None,
        }

    def summary(self) -> dict[str, Any]:
        """List-view shape: definition without the (large) snapshot."""
        payload = self.to_dict(include_snapshot=False)
        payload["rowCounts"] = {
            key: len(rows)
            for key, rows in (self.snapshot.get("datasets") or {}).items()
            if isinstance(rows, list)
        }
        return payload


# -- validation ---------------------------------------------------------------


@dataclass
class ValidatedDashboardInput:
    title: str
    description: str
    queries: dict[str, LiveQuery]
    template: dict[str, Any]
    refresh_interval_seconds: int
    public: bool


def _as_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _dataset_reference(item: dict[str, Any]) -> str | None:
    for key in _DATASET_REF_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    data = item.get("data")
    if isinstance(data, str) and data:
        return data
    if isinstance(data, dict):
        for key in ("dataset_id", "datasetId", "dataset"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _iter_template_panels(template: dict[str, Any]) -> list[dict[str, Any]]:
    """Every KPI / chart / table dict in the template, flattened."""
    panels: list[dict[str, Any]] = []
    panels.extend(_as_items(template.get("kpis")))
    panels.extend(_as_items(template.get("metrics")))
    for section in _as_items(template.get("sections")):
        for key in _ITEM_LIST_KEYS:
            panels.extend(_as_items(section.get(key)))
    for key in _ITEM_LIST_KEYS:
        panels.extend(_as_items(template.get(key)))
    return panels


def validate_queries(raw: Any) -> dict[str, LiveQuery]:
    if not isinstance(raw, dict) or not raw:
        raise LiveDashboardValidationError(
            "queries must be a non-empty object of {datasetKey: sql}"
        )
    if len(raw) > MAX_QUERIES:
        raise LiveDashboardValidationError(f"at most {MAX_QUERIES} queries per dashboard")
    queries: dict[str, LiveQuery] = {}
    for key, value in raw.items():
        if not is_valid_dataset_key(str(key)):
            raise LiveDashboardValidationError(
                f"invalid dataset key {key!r}: use lowercase letters, digits and underscores"
            )
        query = LiveQuery.from_value(value)
        sql = query.sql.strip()
        if not sql:
            raise LiveDashboardValidationError(f"query {key!r} is empty")
        if len(sql) > MAX_SQL_CHARS:
            raise LiveDashboardValidationError(f"query {key!r} is too long")
        if not is_select_only(sql):
            raise LiveDashboardValidationError(
                f"query {key!r} must be a single read-only SELECT statement (no ';', no DML/DDL)"
            )
        queries[str(key)] = LiveQuery(sql=sql, max_rows=query.max_rows)
    return queries


def validate_template(raw: Any, queries: dict[str, LiveQuery]) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        raise LiveDashboardValidationError("view_model must be an object with kpis and/or sections")
    template = {key: value for key, value in raw.items() if key not in _TEMPLATE_STRIPPED_KEYS}
    panels = _iter_template_panels(template)
    if not panels:
        raise LiveDashboardValidationError(
            "view_model has no panels: add kpis[] and/or sections[].items[]"
        )
    referenced: set[str] = set()
    for panel in panels:
        ref = _dataset_reference(panel)
        if ref is None:
            continue
        if ref not in queries:
            raise LiveDashboardValidationError(
                f"panel {panel.get('title') or panel.get('label') or '?'!r} references unknown "
                f"dataset {ref!r}; known keys: {', '.join(sorted(queries))}"
            )
        referenced.add(ref)
    if not referenced:
        raise LiveDashboardValidationError(
            "no panel references a query dataset; set `dataset` on at least one KPI/chart/table"
        )
    return template


def validate_dashboard_input(
    *,
    title: Any,
    queries: Any,
    view_model: Any,
    refresh_interval_seconds: Any = DEFAULT_REFRESH_INTERVAL_SECONDS,
    description: Any = "",
    public: Any = False,
) -> ValidatedDashboardInput:
    """Validate everything a create call needs; raise ``LiveDashboardValidationError``."""
    clean_title = " ".join(str(title or "").split())
    if not clean_title:
        raise LiveDashboardValidationError("title is required")
    clean_description = str(description or "").strip()
    validated_queries = validate_queries(queries)
    template = validate_template(view_model, validated_queries)
    return ValidatedDashboardInput(
        title=clean_title[:MAX_TITLE_CHARS],
        description=clean_description[:MAX_DESCRIPTION_CHARS],
        queries=validated_queries,
        template=template,
        refresh_interval_seconds=clamp_refresh_interval(refresh_interval_seconds),
        public=bool(public),
    )


def apply_record_changes(
    record: LiveDashboardRecord,
    *,
    queries: Any = None,
    view_model: Any = None,
    refresh_interval_seconds: Any = None,
    title: Any = None,
    description: Any = None,
    public: Any = None,
    enabled: Any = None,
) -> bool:
    """Apply a partial update in place; return True when queries/template changed.

    Shared by the chat tool and the REST ``PATCH`` route so both validate the
    same way. Raises ``LiveDashboardValidationError`` on bad input; the record
    is left untouched in that case because validation runs before assignment.
    """
    new_queries = validate_queries(queries) if queries is not None else None
    effective_queries = new_queries if new_queries is not None else record.queries
    new_template = (
        validate_template(
            view_model if view_model is not None else record.template, effective_queries
        )
        if (view_model is not None or new_queries is not None)
        else None
    )
    new_interval = (
        clamp_refresh_interval(refresh_interval_seconds)
        if refresh_interval_seconds is not None
        else None
    )
    clean_title = " ".join(str(title).split())[:MAX_TITLE_CHARS] if title is not None else None
    if title is not None and not clean_title:
        raise LiveDashboardValidationError("title cannot be empty")

    definition_changed = False
    if new_queries is not None:
        record.queries = new_queries
        definition_changed = True
    if new_template is not None:
        record.template = new_template
        definition_changed = True
    if new_interval is not None:
        record.refresh_interval_seconds = new_interval
        record.next_run_at = None  # reschedule from now
    if clean_title:
        record.title = clean_title
    if description is not None:
        record.description = str(description).strip()[:MAX_DESCRIPTION_CHARS]
    if public is not None:
        record.public = bool(public)
    if enabled is not None:
        record.enabled = bool(enabled)
    return definition_changed
