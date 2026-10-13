"""Live, database-backed dashboards for General Chat.

Panels bind to SQL run through the ``db_server`` MCP; a scheduler re-runs the
queries on a per-dashboard interval and pushes changed ViewModels over SSE.
"""

from general_chat.live_dashboard.hub import (
    SSE_HEARTBEAT,
    SSE_HEARTBEAT_SECONDS,
    LiveDashboardHub,
    LiveEvent,
    format_sse,
)
from general_chat.live_dashboard.models import (
    LiveDashboardRecord,
    LiveDashboardValidationError,
    LiveQuery,
    ValidatedDashboardInput,
    clamp_refresh_interval,
    new_dashboard_id,
    validate_dashboard_input,
)
from general_chat.live_dashboard.runner import LiveQueryRunner, QueryOutcome
from general_chat.live_dashboard.scheduler import (
    LiveDashboardScheduler,
    hydrate_view_model,
    refresh_record,
)
from general_chat.live_dashboard.store import (
    JsonLiveDashboardStore,
    PostgresLiveDashboardStore,
    build_live_dashboard_store,
)

__all__ = [
    "SSE_HEARTBEAT",
    "SSE_HEARTBEAT_SECONDS",
    "JsonLiveDashboardStore",
    "LiveDashboardHub",
    "LiveDashboardRecord",
    "LiveDashboardScheduler",
    "LiveDashboardValidationError",
    "LiveEvent",
    "LiveQuery",
    "LiveQueryRunner",
    "PostgresLiveDashboardStore",
    "QueryOutcome",
    "ValidatedDashboardInput",
    "build_live_dashboard_store",
    "clamp_refresh_interval",
    "format_sse",
    "hydrate_view_model",
    "new_dashboard_id",
    "refresh_record",
    "validate_dashboard_input",
]
