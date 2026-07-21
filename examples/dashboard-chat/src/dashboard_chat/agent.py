"""Shared BaseAgent for Dashboard Chat.

One agent instance serves every user; the handler swaps in an
owner-scoped toolset and per-user persistent memory on each request
(see :mod:`dashboard_chat.handler`), so the agent itself is built
without tools.
"""

from __future__ import annotations

import os
from pathlib import Path

from openbench.core.providers import ProviderType, configure_provider
from openbench.intelligence.base import BaseAgent

_DEFAULT_MODEL = "gemini-2.5-flash"

_GOAL = """You are the dashboard copilot: you design and maintain one live dashboard per user
on top of their own SQL database.

Workflow for every dashboard change:
1. Call get_database_schema to see the tables, columns, and types. This is your ONLY view
   of the database — you never see rows and must never invent data values.
2. Call get_dashboard to load the current spec so unchanged panels are preserved.
3. Draft or modify panels. Each panel is {id, type, title, sql, width, x?, y?, format?, unit?}
   with type in kpi|bar|line|area|pie|table and width in third|half|twothirds|full.
   Write SQL in the database's dialect (the schema text names it). KPI queries must return
   a single row with a single value column. Chart queries should return a label/x column
   plus one or more numeric columns, ordered sensibly, aggregated with GROUP BY.
4. Validate uncertain SQL with validate_sql and fix errors it reports.
5. Call save_dashboard with the FULL spec (all panels, not a diff). If it returns per-panel
   errors, fix them and save again.
6. Reply with a short summary of what changed. Do not paste the spec JSON into the reply.

When asked to create an initial dashboard, aim for 5-8 panels: a row of 2-3 KPIs first,
then the most insightful charts for this schema (trends over time, top categories,
distributions), and at most one table. Panel titles are short and human."""


def create_agent() -> BaseAgent:
    """Configure the Gemini provider and build the shared agent (no tools)."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is required")

    model = os.getenv("DASHBOARD_CHAT_MODEL", "").strip() or _DEFAULT_MODEL
    configure_provider(
        name="dashboard-chat-gemini",
        provider_type=ProviderType.LLM,
        provider="gemini",
        plugin_type="chat",
        credentials={"api_key": api_key},
        settings={"model": model},
        is_default=True,
    )

    soul_dir = os.getenv("DASHBOARD_CHAT_SOUL_DIR", "").strip()
    persona = soul_dir if soul_dir and Path(soul_dir).is_dir() else None

    return BaseAgent(
        goal=_GOAL,
        persona=persona,
        model=model,
        temperature=0.4,
        max_iterations=8,
    )
