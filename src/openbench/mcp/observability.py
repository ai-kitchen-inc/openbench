"""Small observability helpers for MCP calls.

The module avoids mandatory telemetry dependencies. If OpenTelemetry is
installed, spans are created; otherwise the context manager is a no-op.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger("openbench.mcp")

_CORRELATION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "openbench_mcp_correlation_id", default=None
)


def new_correlation_id() -> str:
    """Generate a short request correlation ID."""
    return f"mcp-{uuid.uuid4().hex[:12]}"


def get_correlation_id() -> str:
    """Return current correlation ID, creating one if needed."""
    existing = _CORRELATION_ID.get()
    if existing:
        return existing
    created = new_correlation_id()
    _CORRELATION_ID.set(created)
    return created


@contextlib.contextmanager
def correlation_context(correlation_id: str | None = None) -> Iterator[str]:
    """Set a correlation ID for the current context."""
    cid = correlation_id or new_correlation_id()
    token = _CORRELATION_ID.set(cid)
    try:
        yield cid
    finally:
        _CORRELATION_ID.reset(token)


def log_event(event: str, **fields: Any) -> None:
    """Emit a structured MCP log event."""
    payload = {"event": event, "correlation_id": get_correlation_id(), **fields}
    logger.info("%s", payload)


@dataclass
class MCPMetrics:
    """In-memory metrics sink suitable for tests and lightweight apps."""

    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    timings_ms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def inc(self, name: str, value: int = 1) -> None:
        self.counters[name] += value

    def observe_ms(self, name: str, value: float) -> None:
        self.timings_ms[name].append(value)

    def snapshot(self) -> dict[str, Any]:
        return {
            "counters": dict(self.counters),
            "timings_ms": {k: list(v) for k, v in self.timings_ms.items()},
        }


metrics = MCPMetrics()


@contextlib.contextmanager
def trace_span(name: str, **attrs: Any) -> Iterator[None]:
    """Create an optional OpenTelemetry span."""
    try:
        from opentelemetry import trace
    except Exception:
        yield
        return

    tracer = trace.get_tracer("openbench.mcp")
    with tracer.start_as_current_span(name) as span:
        for key, value in attrs.items():
            if value is not None:
                span.set_attribute(key, value)
        yield


@contextlib.contextmanager
def timed_operation(metric_name: str, **log_fields: Any) -> Iterator[None]:
    """Record duration and structured log status for an operation."""
    start = time.perf_counter()
    try:
        yield
    except Exception:
        duration = (time.perf_counter() - start) * 1000
        metrics.observe_ms(metric_name, duration)
        log_event("mcp.operation", duration_ms=round(duration, 3), status="failed", **log_fields)
        raise
    else:
        duration = (time.perf_counter() - start) * 1000
        metrics.observe_ms(metric_name, duration)
        log_event("mcp.operation", duration_ms=round(duration, 3), status="ok", **log_fields)
