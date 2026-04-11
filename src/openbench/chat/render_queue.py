"""Shared per-request render-items queue for SDK skills.

Tool functions in SDK skills (e.g. ``export-excel``, ``data-visualization``)
and project skills (e.g. ``xql``) push A2UI-shaped dicts into this queue
so ``ChatEngine`` can turn them into rich components (``ObFileCard``,
``ObChart``, ``ObTable``, etc.) via its ``render_items_fn`` hook.

Why it exists
-------------

Without a shared queue, every visualization-producing skill has to ship
its own push/get/clear helpers and every server has to wire ``ChatEngine``
to a specific module's functions (``xql_mod.get_render_items`` etc.).
That worked for one skill but scales badly — add a second skill and the
server has to juggle two queues, or the second skill's outputs silently
disappear.

This module centralizes it: all SDK skills push to ONE queue, and any
server can wire ``ChatEngine(render_items_fn=get_items)`` with a single
import. Project skills that still have their own queues can compose them
into a merged function on the server side.

Isolation
---------

Backed by ``contextvars.ContextVar`` so concurrent requests running under
``asyncio.to_thread`` or ``asyncio.gather`` don't share state across
turns. Each request gets its own empty queue on ``clear()``.

Example
-------

    from openbench.chat.render_queue import push, get_items, clear
    from openbench.chat import ChatEngine

    # Inside a tool function:
    def export_to_excel(...):
        item = {"name": "report.xlsx", "url": "/downloads/report.xlsx"}
        push(item)
        return item  # also returned to the LLM as tool result context

    # Inside server wiring:
    engine = ChatEngine(
        agent=my_agent,
        render_items_fn=get_items,
        clear_render_items_fn=clear,
    )
"""

from __future__ import annotations

import contextvars
from typing import Any

__all__ = ["push", "push_many", "get_items", "clear"]


_QUEUE: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "openbench_render_queue", default=None
)


def _get_or_init() -> list[dict[str, Any]]:
    """Return the mutable queue for the current context, creating it if needed."""
    items = _QUEUE.get()
    if items is None:
        items = []
        _QUEUE.set(items)
    return items


def push(item: dict[str, Any]) -> None:
    """Append one A2UI-shaped dict to the queue.

    The item must match one of the registered ``ContentRenderer`` detect
    contracts (chart, file, form, list, table, code, media, callout, etc.)
    or it will be ignored by ``ChatEngine``.
    """
    if not isinstance(item, dict):
        raise TypeError(f"push() requires a dict render item, got {type(item).__name__}")
    _get_or_init().append(item)


def push_many(items: list[dict[str, Any]]) -> None:
    """Append several render items at once."""
    if not isinstance(items, list):
        raise TypeError(f"push_many() requires a list, got {type(items).__name__}")
    queue = _get_or_init()
    for item in items:
        if not isinstance(item, dict):
            raise TypeError(f"push_many() items must be dicts, got {type(item).__name__}")
        queue.append(item)


def get_items() -> list[dict[str, Any]]:
    """Return a shallow copy of the current queue for ``ChatEngine`` to render.

    Returning a copy (not the live list) lets ``ChatEngine`` iterate
    without races against skills that might push more items mid-dedupe.
    """
    return list(_get_or_init())


def clear() -> None:
    """Reset the queue to empty. Called by ``ChatEngine`` before each request."""
    _QUEUE.set([])
