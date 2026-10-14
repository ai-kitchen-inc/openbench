"""Tools for the live-dashboard project skill.

Dependencies (store, query runner, event hub, owner accessor) are injected by
the host through :func:`bind` at agent construction. Every tool returns a
plain dict and never raises: a validation or SQL failure comes back as
``{"error": ...}`` so the agent can correct it within the same turn.

Results sent back to the model are deliberately trimmed -- the ViewModel is
pushed to the render queue for the UI only (echoing it bloats the history and
drives regenerate loops, see ``_DashboardGeneratorRenderTool`` in
``general_chat.agent``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from general_chat.live_dashboard.hub import LiveEvent
from general_chat.live_dashboard.models import (
    DEFAULT_REFRESH_INTERVAL_SECONDS,
    LiveDashboardRecord,
    LiveDashboardValidationError,
    apply_record_changes,
    new_dashboard_id,
    validate_dashboard_input,
)
from general_chat.live_dashboard.scheduler import refresh_record

from openbench.chat import render_queue as shared_render_queue

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = [
    "CREATE_LIVE_DASHBOARD_SCHEMA",
    "LIST_LIVE_DASHBOARDS_SCHEMA",
    "REFRESH_LIVE_DASHBOARD_SCHEMA",
    "UPDATE_LIVE_DASHBOARD_SCHEMA",
    "bind",
    "create_live_dashboard",
    "list_live_dashboards",
    "refresh_live_dashboard",
    "update_live_dashboard",
]

# ---------------------------------------------------------------------------
# Bound dependencies (populated by skill.bind() at agent build)
# ---------------------------------------------------------------------------

_store: Any | None = None
_runner: Any | None = None
_hub: Any | None = None
_owner_provider: Callable[[], str | None] | None = None
_public_base_url: str = ""


def bind(
    live_dashboard_store: Any = None,
    live_dashboard_runner: Any = None,
    live_dashboard_hub: Any = None,
    live_dashboard_owner_provider: Callable[[], str | None] | None = None,
    live_dashboard_public_base_url: str | None = None,
    **_: object,
) -> None:
    """Inject the host's store, runner, hub and per-turn owner accessor.

    Called by :meth:`SkillRegistry.bind`. Extra kwargs are ignored so other
    skills' bindings can share the same call.
    """
    global _store, _runner, _hub, _owner_provider, _public_base_url
    _store = live_dashboard_store
    _runner = live_dashboard_runner
    _hub = live_dashboard_hub
    _owner_provider = live_dashboard_owner_provider
    _public_base_url = (live_dashboard_public_base_url or "").rstrip("/")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error(message: str, **extra: Any) -> dict[str, Any]:
    return {"error": message, **extra}


def _owner() -> str | None:
    if _owner_provider is None:
        return None
    try:
        return _owner_provider()
    except Exception:
        return None


def _ready() -> dict[str, Any] | None:
    if _store is None or _runner is None:
        return _error("live dashboards are not configured on this server")
    return None


def _public_url(record: LiveDashboardRecord) -> str | None:
    if not record.public:
        return None
    return f"{_public_base_url}/d/{record.id}"


def _render(record: LiveDashboardRecord) -> None:
    """Show the current snapshot in the chat side panel."""
    snapshot = record.snapshot or {}
    view_model = snapshot.get("viewModel")
    shared_render_queue.push(
        {
            "type": "dashboard",
            "title": record.title,
            "description": record.description,
            "viewModel": view_model if isinstance(view_model, dict) else {"title": record.title},
            "dashboardId": record.id,
            "live": True,
            "refreshIntervalSeconds": record.refresh_interval_seconds,
            "version": record.version,
            "refreshedAt": snapshot.get("refreshedAt") or record.last_refresh_at,
            "render_mode": "a2ui",
        }
    )


def _publish(record: LiveDashboardRecord, event: Any) -> None:
    if _hub is None or event is None:
        return
    try:
        _hub.publish_threadsafe(record.id, event)
    except Exception:
        logger.warning("live-dashboard: publish failed for %s", record.id, exc_info=True)


def _result(record: LiveDashboardRecord, status: str) -> dict[str, Any]:
    snapshot = record.snapshot or {}
    datasets = snapshot.get("datasets") or {}
    errors = snapshot.get("errors") or {}
    result: dict[str, Any] = {
        "type": "live_dashboard",
        "status": status,
        "id": record.id,
        "title": record.title,
        "url": f"/d/{record.id}",
        "version": record.version,
        "refreshIntervalSeconds": record.refresh_interval_seconds,
        "enabled": record.enabled,
        "public": record.public,
        "rowCounts": {key: len(rows) for key, rows in datasets.items() if isinstance(rows, list)},
        "errors": errors,
        "lastError": record.last_error,
    }
    public_url = _public_url(record)
    if public_url:
        result["publicUrl"] = public_url
    if errors:
        failed = ", ".join(sorted(errors))
        result["final_answer_hint"] = (
            f"Some queries failed ({failed}); see `errors`. Fix the SQL and call "
            "update_live_dashboard with the corrected `queries` for THIS dashboard id -- "
            "do not create another dashboard. Then summarize in the user's language."
        )
    else:
        result["final_answer_hint"] = (
            "The live dashboard is rendered in the side panel and will refresh on its "
            "schedule. Do NOT call create_live_dashboard again for this request and do "
            "not paste the ViewModel. Summarize briefly in the user's language: what it "
            "shows, the refresh interval" + (", and the public link." if public_url else ".")
        )
    return result


def _owned(dashboard_id: Any, owner: str) -> LiveDashboardRecord | dict[str, Any]:
    record = _store.get(str(dashboard_id or "").strip())
    if record is None or record.owner != owner:
        return _error(f"live dashboard {dashboard_id!r} not found")
    return record


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

CREATE_LIVE_DASHBOARD_SCHEMA = {
    "name": "create_live_dashboard",
    "description": (
        "Create a database-bound dashboard that refreshes itself. `queries` maps dataset "
        "keys to read-only SELECT statements run through the db_server MCP; `view_model` "
        "is a template whose KPIs/charts/tables reference those dataset keys (never inline "
        "rows). Runs every query once, renders the dashboard in the side panel and starts "
        "the refresh schedule. Returns per-dataset row counts and errors."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Dashboard title shown to the user."},
            "queries": {
                "type": "object",
                "description": (
                    "{datasetKey: SQL}. Keys: lowercase letters, digits, underscores. "
                    "Each value a single SELECT/WITH statement."
                ),
                "additionalProperties": {"type": "string"},
            },
            "view_model": {
                "type": "object",
                "description": (
                    "Template: {kpis: [{label, dataset, value_column, format?}], sections: "
                    "[{title, items: [{type: 'chart'|'table', chart_type?, title, dataset, "
                    "x_field?, y_field?, columns?}]}]}. Panels reference `dataset` keys from "
                    "`queries`."
                ),
            },
            "refresh_interval_seconds": {
                "type": "integer",
                "description": "Refresh every N seconds (min 15, default 60). 0 = manual only.",
            },
            "description": {"type": "string", "description": "Optional one-line description."},
            "public": {
                "type": "boolean",
                "description": "Expose a shareable /d/{id} page without sign-in (default false).",
            },
        },
        "required": ["title", "queries", "view_model"],
    },
}


def create_live_dashboard(
    title: str,
    queries: dict[str, Any],
    view_model: dict[str, Any],
    refresh_interval_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS,
    description: str = "",
    public: bool = False,
) -> dict[str, Any]:
    """Validate, run once, persist, render, and return a trimmed summary."""
    not_ready = _ready()
    if not_ready:
        return not_ready
    owner = _owner()
    if not owner:
        return _error("cannot resolve the current user; live dashboards need a signed-in owner")
    try:
        validated = validate_dashboard_input(
            title=title,
            queries=queries,
            view_model=view_model,
            refresh_interval_seconds=refresh_interval_seconds,
            description=description,
            public=public,
        )
    except LiveDashboardValidationError as exc:
        return _error(str(exc))

    # Always the registry's db_server entry: the model never picks a server.
    resolved_server = _runner.default_server_id()
    if not resolved_server:
        return _error(
            "the db_server MCP is not registered or is disabled; enable it in the MCP panel first"
        )

    record = LiveDashboardRecord(
        id=new_dashboard_id(),
        owner=owner,
        title=validated.title,
        description=validated.description,
        server_id=resolved_server,
        namespace=_runner.default_namespace,
        queries=validated.queries,
        template=validated.template,
        refresh_interval_seconds=validated.refresh_interval_seconds,
        public=validated.public,
    )
    record, event = refresh_record(record, _runner, now=datetime.now(timezone.utc), force=True)
    _store.save(record)
    _render(record)
    _publish(record, event)
    return _result(record, "created")


UPDATE_LIVE_DASHBOARD_SCHEMA = {
    "name": "update_live_dashboard",
    "description": (
        "Change an existing live dashboard: replace queries and/or the view_model template, "
        "rename it, change the refresh interval, publish/unpublish, pause/resume. Re-runs the "
        "queries when they or the template changed and re-renders in the side panel."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dashboard_id": {
                "type": "string",
                "description": "Id returned by create_live_dashboard.",
            },
            "queries": {
                "type": "object",
                "description": "Full replacement {datasetKey: SQL} map (all queries, not a diff).",
                "additionalProperties": {"type": "string"},
            },
            "view_model": {"type": "object", "description": "Full replacement template."},
            "refresh_interval_seconds": {"type": "integer"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "public": {"type": "boolean"},
            "enabled": {
                "type": "boolean",
                "description": "false pauses the schedule (manual refresh still works).",
            },
        },
        "required": ["dashboard_id"],
    },
}


def update_live_dashboard(
    dashboard_id: str,
    queries: dict[str, Any] | None = None,
    view_model: dict[str, Any] | None = None,
    refresh_interval_seconds: int | None = None,
    title: str | None = None,
    description: str | None = None,
    public: bool | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Apply a partial update; re-run queries when the definition changed."""
    not_ready = _ready()
    if not_ready:
        return not_ready
    owner = _owner()
    if not owner:
        return _error("cannot resolve the current user")
    found = _owned(dashboard_id, owner)
    if isinstance(found, dict):
        return found
    record = found

    was_public = record.public
    try:
        definition_changed = apply_record_changes(
            record,
            queries=queries,
            view_model=view_model,
            refresh_interval_seconds=refresh_interval_seconds,
            title=title,
            description=description,
            public=public,
            enabled=enabled,
        )
    except LiveDashboardValidationError as exc:
        return _error(str(exc))

    event = None
    if definition_changed:
        record.data_hash = ""  # force a new version even if rows are identical
        record, event = refresh_record(record, _runner, now=datetime.now(timezone.utc), force=True)
    _store.save(record)
    if definition_changed or title is not None or description is not None:
        _render(record)
    if event is not None:
        _publish(record, event)
    if was_public and not record.public:
        _publish(record, LiveEvent("closed", {"id": record.id, "reason": "unpublished"}))
    return _result(record, "updated")


LIST_LIVE_DASHBOARDS_SCHEMA = {
    "name": "list_live_dashboards",
    "description": "List the current user's live dashboards (id, title, interval, status, last refresh).",
    "parameters": {"type": "object", "properties": {}},
}


def list_live_dashboards() -> dict[str, Any]:
    not_ready = _ready()
    if not_ready:
        return not_ready
    owner = _owner()
    if not owner:
        return _error("cannot resolve the current user")
    items = [
        {
            "id": record.id,
            "title": record.title,
            "description": record.description,
            "refreshIntervalSeconds": record.refresh_interval_seconds,
            "enabled": record.enabled,
            "public": record.public,
            "publicUrl": _public_url(record),
            "version": record.version,
            "lastRefreshAt": record.last_refresh_at,
            "lastError": record.last_error,
            "datasets": sorted(record.queries),
        }
        for record in _store.list(owner)
    ]
    return {"dashboards": items, "count": len(items)}


REFRESH_LIVE_DASHBOARD_SCHEMA = {
    "name": "refresh_live_dashboard",
    "description": "Re-run a live dashboard's queries now and push the result to all viewers.",
    "parameters": {
        "type": "object",
        "properties": {"dashboard_id": {"type": "string"}},
        "required": ["dashboard_id"],
    },
}


def refresh_live_dashboard(dashboard_id: str) -> dict[str, Any]:
    not_ready = _ready()
    if not_ready:
        return not_ready
    owner = _owner()
    if not owner:
        return _error("cannot resolve the current user")
    found = _owned(dashboard_id, owner)
    if isinstance(found, dict):
        return found
    record, event = refresh_record(found, _runner, now=datetime.now(timezone.utc), force=True)
    _store.save(record)
    _render(record)
    _publish(record, event)
    return _result(record, "refreshed")
