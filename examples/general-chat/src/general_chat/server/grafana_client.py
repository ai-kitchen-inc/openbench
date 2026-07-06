"""Push dashboards into the self-hosted Grafana over its HTTP API.

Companion to :mod:`general_chat.server.grafana` (ViewModel -> Grafana model).
This module owns the transport side: a thin ``requests``-based client for
``POST /api/dashboards/db``, discovery of which ``appdata`` Postgres tables can
back live panels, and the one-call ``deploy_view_model()`` used by the
``/dashboard/deploy/grafana`` route.

Environment:
    GRAFANA_URL             Internal base URL (default ``http://grafana:3000``).
    GRAFANA_ADMIN_USER      Basic-auth user (default ``admin``).
    GRAFANA_ADMIN_PASSWORD  Basic-auth password (required to deploy).
    GRAFANA_PUBLIC_URL      Browser-facing base URL for returned links
                            (e.g. ``https://host/grafana``; falls back to
                            GRAFANA_URL).
    MCP_DB_DATABASE_URL     Postgres URL used to list appdata tables (the same
                            read-only role the db_server MCP uses).
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

from general_chat.server.grafana import partition_datasets, view_model_to_grafana

logger = logging.getLogger(__name__)

# Must match the provisioned datasource UIDs in deploy/grafana/datasources.yaml.
_PG_DATASOURCE_UID = "appdata-postgres"
_TESTDATA_DATASOURCE_UID = "testdata"

_TABLE_SCHEMAS = ("public", "mart")
_REQUEST_TIMEOUT = 10  # seconds


class GrafanaDeployError(RuntimeError):
    """Deploy failed in a way the caller should surface (503)."""


class GrafanaClient:
    """Minimal Grafana HTTP API client (basic auth, sync requests)."""

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._auth = (username, password)

    def push_dashboard(self, model: dict[str, Any]) -> dict[str, Any]:
        """POST the dashboard model; overwrite an existing one with the same uid."""
        import requests

        payload = {"dashboard": model, "folderUid": "", "overwrite": True}
        try:
            response = requests.post(
                f"{self.base_url}/api/dashboards/db",
                json=payload,
                auth=self._auth,
                timeout=_REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise GrafanaDeployError(f"Grafana unreachable at {self.base_url}: {exc}") from exc
        if response.status_code != 200:
            detail = response.text[:300]
            raise GrafanaDeployError(
                f"Grafana rejected the dashboard ({response.status_code}): {detail}"
            )
        return response.json()


def list_appdata_tables() -> dict[str, str]:
    """Map dataset-name candidates to real ``schema.table`` in appdata.

    Bare table names are keyed directly (``products`` -> ``public.products``)
    and also as ``schema.table``. ``mart`` wins bare-name collisions because
    mart tables are purpose-built for dashboards. Any failure returns ``{}`` so
    a deploy degrades to all-inline panels instead of blocking.
    """
    url = os.getenv("MCP_DB_DATABASE_URL", "").strip()
    if not url:
        return {}
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=5) as conn:
            rows = conn.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE'",
                (list(_TABLE_SCHEMAS),),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - degrade, never block a deploy
        logger.warning("appdata table discovery failed; deploying inline-only: %s", exc)
        return {}

    tables: dict[str, str] = {}
    # public first so a later mart entry overrides the bare name.
    for schema in _TABLE_SCHEMAS:
        for row_schema, table in rows:
            if row_schema != schema:
                continue
            qualified = f"{row_schema}.{table}"
            tables[str(table)] = qualified
            tables[qualified] = qualified
    return tables


def dashboard_uid(title: str) -> str:
    """Stable uid from the title so re-deploys overwrite, not duplicate."""
    return hashlib.sha1(title.strip().lower().encode("utf-8")).hexdigest()[:12]


def deploy_view_model(view_model: dict[str, Any]) -> dict[str, Any]:
    """Convert + push a ViewModel; return ``{url, uid, live, inline}``."""
    password = os.getenv("GRAFANA_ADMIN_PASSWORD", "").strip()
    if not password:
        raise GrafanaDeployError("GRAFANA_ADMIN_PASSWORD is not configured")
    base_url = os.getenv("GRAFANA_URL", "http://grafana:3000").strip()
    username = os.getenv("GRAFANA_ADMIN_USER", "admin").strip()
    public_url = (os.getenv("GRAFANA_PUBLIC_URL", "").strip() or base_url).rstrip("/")

    tables = list_appdata_tables()
    model = view_model_to_grafana(
        view_model,
        live={
            "tables": tables,
            "pg_uid": _PG_DATASOURCE_UID,
            "testdata_uid": _TESTDATA_DATASOURCE_UID,
        },
    )
    uid = dashboard_uid(str(model.get("title") or "dashboard"))
    model["uid"] = uid
    model["id"] = None

    GrafanaClient(base_url, username, password).push_dashboard(model)

    live, inline = partition_datasets(view_model, tables)
    return {"url": f"{public_url}/d/{uid}", "uid": uid, "live": live, "inline": inline}
