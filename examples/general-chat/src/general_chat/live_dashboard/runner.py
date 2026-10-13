"""Run live dashboard queries through the ``db_server`` MCP.

One registry client is opened per refresh cycle and reused for every query of
the dashboard: a stdio ``db_server`` is a ``docker run`` whose cold start
dominates, so the per-query cost must stay at one tool call.

The fork's ``execute_sql_json`` tool is preferred (structured rows). Older
images only expose ``execute_sql``, whose text table is parsed as a fallback
so a dashboard keeps working until the image is rebuilt.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from general_chat.live_dashboard.models import LiveQuery

logger = logging.getLogger(__name__)

JSON_TOOL = "execute_sql_json"
TEXT_TOOL = "execute_sql"

_RESULTS_HEADER_RE = re.compile(r"^Results \((\d+) rows?\):\s*$")
_MORE_ROWS_RE = re.compile(r"^\.\.\. and (\d+) more rows?")
_ERROR_PREFIXES = ("Error executing SQL:", "Error executing query:", "Error:", "ERROR:")


@dataclass
class QueryOutcome:
    """Result of one query: ``rows`` on success, ``error`` otherwise."""

    rows: list[dict[str, Any]] | None = None
    error: str | None = None
    truncated: bool = False
    elapsed_ms: int = 0
    columns: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and self.rows is not None


def tool_result_text(result: Any) -> str:
    """Unwrap the text an MCP ``-> str`` tool returned, whatever the envelope.

    ``MCPClient.call_tool`` hands back ``structuredContent`` when present
    (FastMCP wraps a string result as ``{"result": "..."}``) and the raw
    ``{"content": [{"type": "text", "text": ...}]}`` otherwise.
    """
    if isinstance(result, str):
        return result
    if isinstance(result, Mapping):
        inner = result.get("result")
        if isinstance(inner, str):
            return inner
        content = result.get("content")
        if isinstance(content, list):
            parts = [
                str(item.get("text"))
                for item in content
                if isinstance(item, Mapping) and isinstance(item.get("text"), str)
            ]
            if parts:
                return "\n".join(parts)
        return json.dumps(result, ensure_ascii=False, default=str)
    if isinstance(result, list):
        return "\n".join(tool_result_text(item) for item in result)
    return str(result)


def parse_execute_sql_json(text: str) -> QueryOutcome:
    """Parse the ``execute_sql_json`` payload."""
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return QueryOutcome(error=f"execute_sql_json returned non-JSON output: {text[:200]!r}")
    if not isinstance(payload, dict):
        return QueryOutcome(error="execute_sql_json returned an unexpected payload")
    if payload.get("error"):
        return QueryOutcome(error=str(payload["error"]))
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return QueryOutcome(error="execute_sql_json payload has no rows")
    clean_rows = [row for row in rows if isinstance(row, dict)]
    columns = payload.get("columns")
    return QueryOutcome(
        rows=clean_rows,
        truncated=bool(payload.get("truncated")),
        columns=[str(col) for col in columns] if isinstance(columns, list) else [],
    )


def _coerce_cell(raw: str) -> Any:
    value = raw.strip()
    if value in {"", "None", "NULL", "null"}:
        return None
    if value in {"True", "true"}:
        return True
    if value in {"False", "false"}:
        return False
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            return value
    if re.fullmatch(r"-?\d+\.\d+(e-?\d+)?", value, flags=re.IGNORECASE):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def parse_execute_sql_text(text: str) -> QueryOutcome:
    """Parse the legacy ``execute_sql`` text table.

    Format produced by the fork::

        SQL Query: SELECT ...

        Results (2 rows):
        region | revenue
        ------ | -------
        EU | 1200
        US | 900

        ... and 3 more rows

    Cells containing `` | `` cannot be split unambiguously; that is why the
    JSON tool exists. Rows whose cell count differs from the header are kept
    by joining the overflow into the last column.
    """
    stripped = (text or "").strip()
    if not stripped:
        return QueryOutcome(error="execute_sql returned no output")
    for prefix in _ERROR_PREFIXES:
        if stripped.startswith(prefix):
            return QueryOutcome(error=stripped[:500])

    lines = stripped.splitlines()
    header_index = next(
        (index for index, line in enumerate(lines) if _RESULTS_HEADER_RE.match(line.strip())),
        None,
    )
    if header_index is None:
        return QueryOutcome(error=f"unrecognized execute_sql output: {stripped[:200]!r}")

    body = list(lines[header_index + 1 :])
    truncated = False
    table_lines: list[str] = []
    for line in body:
        if not line.strip():
            continue
        if line.strip() == "No results found.":
            return QueryOutcome(rows=[])
        more = _MORE_ROWS_RE.match(line.strip())
        if more:
            truncated = True
            continue
        table_lines.append(line)
    if not table_lines:
        return QueryOutcome(rows=[], truncated=truncated)

    columns = [cell.strip() for cell in table_lines[0].split(" | ")]
    rows: list[dict[str, Any]] = []
    for line in table_lines[1:]:
        cells = line.split(" | ")
        if all(re.fullmatch(r"-+", cell.strip() or "-") for cell in cells):
            continue
        if len(cells) > len(columns):
            cells = [*cells[: len(columns) - 1], " | ".join(cells[len(columns) - 1 :])]
        while len(cells) < len(columns):
            cells.append("")
        rows.append(
            {column: _coerce_cell(cell) for column, cell in zip(columns, cells, strict=False)}
        )
    return QueryOutcome(rows=rows, truncated=truncated, columns=columns)


class LiveQueryRunner:
    """Execute a dashboard's queries against one registry MCP server."""

    def __init__(
        self,
        registry: Any,
        *,
        default_namespace: str = "db_server",
        timeout_seconds: float = 60.0,
    ):
        self._registry = registry
        self._default_namespace = default_namespace
        self._timeout_seconds = float(timeout_seconds)

    @property
    def default_namespace(self) -> str:
        return self._default_namespace

    def default_server_id(self) -> str | None:
        """The enabled registry server exposing the default namespace, if any."""
        try:
            return self._registry.find_server_id(namespace=self._default_namespace)
        except Exception:  # registry unreadable -> treat as absent
            logger.exception("live-dashboard: failed to resolve the default MCP server")
            return None

    def run_queries(
        self, server_id: str, queries: Mapping[str, LiveQuery]
    ) -> dict[str, QueryOutcome]:
        """Run every query with one client; never raises for a single bad query."""
        if not queries:
            return {}
        try:
            client, namespace = self._registry.open_client(server_id)
        except KeyError:
            error = f"MCP server {server_id!r} is not registered or is disabled"
            return {key: QueryOutcome(error=error) for key in queries}
        except Exception as exc:  # connection config problems
            error = f"MCP server {server_id!r} could not be opened: {exc}"
            return {key: QueryOutcome(error=error) for key in queries}

        outcomes: dict[str, QueryOutcome] = {}
        try:
            try:
                tools = client.list_tools()
            except Exception as exc:
                error = f"MCP discovery failed for {namespace}: {exc}"
                return {key: QueryOutcome(error=error) for key in queries}
            json_tool = f"{namespace}.{JSON_TOOL}"
            text_tool = f"{namespace}.{TEXT_TOOL}"
            if json_tool in tools:
                tool_name, parser = json_tool, parse_execute_sql_json
            elif text_tool in tools:
                tool_name, parser = text_tool, parse_execute_sql_text
            else:
                error = f"{namespace} exposes neither {JSON_TOOL} nor {TEXT_TOOL}"
                return {key: QueryOutcome(error=error) for key in queries}

            for key, query in queries.items():
                started = time.perf_counter()
                try:
                    raw = client.call_tool_sync(
                        tool_name,
                        {"sql_query": query.sql},
                        timeout_seconds=self._timeout_seconds,
                        approved=True,
                    )
                    outcome = parser(tool_result_text(raw))
                except Exception as exc:
                    outcome = QueryOutcome(error=str(exc)[:500])
                outcome.elapsed_ms = int((time.perf_counter() - started) * 1000)
                if outcome.rows is not None and len(outcome.rows) > query.max_rows:
                    outcome.rows = outcome.rows[: query.max_rows]
                    outcome.truncated = True
                outcomes[key] = outcome
            return outcomes
        finally:
            try:
                client.close_sync()
            except Exception:
                logger.warning("live-dashboard: closing MCP client failed", exc_info=True)
