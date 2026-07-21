"""Owner-scoped agent tools for Dashboard Chat.

``build_toolset(owner, ...)`` returns a fresh :class:`ToolExecutor`
whose four tools close over one user's connection and dashboard. The
handler rebuilds it per request, so the shared agent object never
carries user state.

Strict data rule: no tool can return row data. ``validate_sql`` probes
with LIMIT 0 (columns only), and ``save_dashboard`` validates every
panel the same way before persisting.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dashboard_chat.connections import introspect_schema, schema_as_text
from dashboard_chat.sqlguard import validate_select
from openbench.intelligence.tool_executor import ToolExecutor

if TYPE_CHECKING:
    from dashboard_chat.connections import ConnectionStore
    from dashboard_chat.dashboards import DashboardStore

GET_DATABASE_SCHEMA_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_database_schema",
        "description": (
            "Return the user's database schema as compact text: one line per table "
            "with columns, types, PK/FK markers. Never returns row data."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

VALIDATE_SQL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "validate_sql",
        "description": (
            "Validate a SELECT statement against the user's database without reading "
            "any rows (LIMIT 0). Returns ok plus the result column names, or the exact "
            "database error message to fix."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "A single SELECT (or WITH ... SELECT) statement.",
                }
            },
            "required": ["sql"],
        },
    },
}

GET_DASHBOARD_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_dashboard",
        "description": (
            "Return the user's current dashboard spec JSON, or null when none exists "
            "yet. Always call this before modifying so unchanged panels are preserved."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

SAVE_DASHBOARD_SCHEMA = {
    "type": "function",
    "function": {
        "name": "save_dashboard",
        "description": (
            "Validate and persist the FULL dashboard spec (not a diff). Every panel's "
            "SQL is validated with LIMIT 0; if any panel fails, nothing is saved and "
            "per-panel errors are returned so you can fix and retry."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "string",
                    "description": (
                        "The full dashboard spec as a JSON string: {title, description, "
                        "panels:[{id, type:kpi|bar|line|area|pie|table, title, sql, "
                        "width:third|half|twothirds|full, x?, y?, format?, unit?}]}"
                    ),
                }
            },
            "required": ["spec"],
        },
    },
}


def build_toolset(
    owner: str,
    connection_store: ConnectionStore,
    dashboard_store: DashboardStore,
) -> ToolExecutor:
    """Fresh per-request executor with tools closed over ``owner``."""

    def get_database_schema() -> dict:
        engine = connection_store.engine_for(owner)
        if engine is None:
            return {"ok": False, "error": "No database connected yet. Ask the user to connect one."}
        return {"ok": True, "schema": schema_as_text(introspect_schema(engine))}

    def validate_sql(sql: str) -> dict:
        engine = connection_store.engine_for(owner)
        if engine is None:
            return {"ok": False, "error": "No database connected yet. Ask the user to connect one."}
        return validate_select(engine, sql)

    def get_dashboard() -> dict:
        return {"ok": True, "dashboard": dashboard_store.get(owner)}

    def save_dashboard(spec: str) -> dict:
        engine = connection_store.engine_for(owner)
        if engine is None:
            return {"ok": False, "error": "No database connected yet. Ask the user to connect one."}
        try:
            parsed = json.loads(spec)
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"spec is not valid JSON: {exc}"}
        sql_errors = []
        for panel in parsed.get("panels", []) if isinstance(parsed, dict) else []:
            if not isinstance(panel, dict):
                continue
            verdict = validate_select(engine, str(panel.get("sql") or ""))
            if not verdict.get("ok"):
                sql_errors.append(
                    {"panelId": panel.get("id"), "error": verdict.get("error", "invalid SQL")}
                )
        if sql_errors:
            return {"ok": False, "errors": sql_errors}
        try:
            stamped = dashboard_store.save(owner, parsed)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "version": stamped["version"], "panelCount": len(stamped["panels"])}

    executor = ToolExecutor()
    executor.register("get_database_schema", get_database_schema, schema=GET_DATABASE_SCHEMA_SCHEMA)
    executor.register("validate_sql", validate_sql, schema=VALIDATE_SQL_SCHEMA)
    executor.register("get_dashboard", get_dashboard, schema=GET_DASHBOARD_SCHEMA)
    executor.register("save_dashboard", save_dashboard, schema=SAVE_DASHBOARD_SCHEMA)
    return executor
