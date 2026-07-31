"""Build the per-turn source context: cards plus retrieved passages.

The old behaviour sends every ready source's full text on every turn.
That burns tokens on documents nobody asked about, and shreds large
corpora against the character budget.

This module replaces it with:

* a compact **card** per indexed source — name, id, kind, outline,
  summary, or table schema — so the model always knows what exists;
* the **top-k passages** retrieved for the current question, so the
  common single-fact question needs no tool call;
* a **scope** published on a :class:`~contextvars.ContextVar` that the
  source-retrieval and table-query skills read, so the agent can pull
  more without ever reaching outside this turn's sources.

Sources that are not indexed — because the feature is off, indexing
failed, or the record predates it — fall back to the previous full-text
attachment. Mixed sessions are expected and supported.

``GENERAL_CHAT_SOURCE_CONTEXT_MODE`` controls this: ``full`` (default)
reproduces the old behaviour exactly, ``auto`` uses cards for indexed
sources, ``cards`` additionally suppresses the full-text fallback.
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from openbench.chat.session import Attachment

logger = logging.getLogger(__name__)

MODE_FULL = "full"
MODE_AUTO = "auto"
MODE_CARDS = "cards"

RETRIEVED_CONTEXT_ID = "general-chat-retrieved-context"
SOURCE_CARD_PREFIX = "general-chat-source-card"

DEFAULT_RETRIEVAL_TOP_K = 6
DEFAULT_CARD_BUDGET = 24_000
#: Below this a message is a greeting or an acknowledgement, not a
#: question worth spending a retrieval round-trip on.
MIN_QUERY_CHARS = 12


@dataclass(frozen=True)
class SourceScope:
    """What the current turn is allowed to read.

    Carries explicit source ids rather than a session id: admin-curated
    global sources live under a different owner and session, and a
    session-only filter would silently drop them.
    """

    session_id: str = ""
    owner: str = ""
    source_ids: tuple[str, ...] = field(default_factory=tuple)


_SCOPE: ContextVar[SourceScope | None] = ContextVar("openbench_source_scope", default=None)


def set_source_scope(scope: SourceScope | None) -> None:
    """Publish the current turn's scope for the retrieval skills."""
    _SCOPE.set(scope)


def current_source_scope() -> SourceScope | None:
    """Read the current turn's scope.

    Bound once into the skills at agent construction and read per tool
    call, so a single shared ToolExecutor serves concurrent requests
    correctly — both ``ToolExecutor.execute`` and ``execute_parallel``
    copy the context into their worker threads.
    """
    return _SCOPE.get()


def source_context_mode() -> str:
    """Which prompt shape to build for this turn."""
    raw = (os.getenv("GENERAL_CHAT_SOURCE_CONTEXT_MODE") or "").strip().lower()
    return raw if raw in {MODE_FULL, MODE_AUTO, MODE_CARDS} else MODE_FULL


def retrieval_top_k() -> int:
    raw = (os.getenv("GENERAL_CHAT_RETRIEVAL_TOP_K") or "").strip()
    try:
        return max(1, int(raw)) if raw else DEFAULT_RETRIEVAL_TOP_K
    except ValueError:
        return DEFAULT_RETRIEVAL_TOP_K


def card_budget() -> int:
    raw = (os.getenv("GENERAL_CHAT_SOURCE_CARD_BUDGET") or "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_CARD_BUDGET
    except ValueError:
        return DEFAULT_CARD_BUDGET


def is_indexed(record: Any) -> bool:
    """Whether a record has usable chunks or tables."""
    metadata = record.metadata or {}
    return metadata.get("indexStatus") == "ready"


def _routing_lines(record: Any) -> str:
    """Preserve the existing tool-routing contracts on a card.

    These paths are how the image, dashboard, and template tools find
    their input. They are small and load-bearing — the card replaces the
    document *text*, not the routing.
    """
    metadata = record.metadata or {}
    lines: list[str] = []

    image_path = metadata.get("imageSearchPath")
    if record.kind == "image" and isinstance(image_path, str):
        lines.append(f"Image search path: {image_path}")

    sam_path = metadata.get("samSegmentationPath")
    if record.kind == "image" and isinstance(sam_path, str):
        lines.append(f"SAM 3 concept counting path: {sam_path}")

    dashboard_path = metadata.get("localFilePath")
    if record.kind == "spreadsheet" and isinstance(dashboard_path, str):
        lines.append(f"Dashboard source path: {dashboard_path}")
        lines.append(
            "For dashboard requests only: call aggregate_data.extract_metadata with "
            "this path, then dashboard_generator.search_dashboards before any "
            "aggregation; load a reusable match instead of regenerating. For every "
            "other numeric question use query_source_table."
        )

    template_path = metadata.get("dashboardTemplatePath")
    if record.kind == "dashboard_template" and isinstance(template_path, str):
        lines.append(f"Dashboard template path: {template_path}")
        lines.append(
            "For dashboard requests that should use this uploaded template, pass "
            "this path as generate_dashboard(template_path=...)."
        )

    return "\n".join(lines)


def _size_label(size_bytes: int) -> str:
    if size_bytes <= 0:
        return ""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def build_source_card(record: Any, *, label: str = "") -> Attachment:
    """Render one indexed source as a compact card.

    The card tells the model what the source is and how to read more; it
    deliberately does not carry the source's text.
    """
    metadata = record.metadata or {}
    lines = [f"Source: {record.name}   (id: {record.id})"]

    descriptors = [record.kind or "document"]
    size = _size_label(int(record.size_bytes or 0))
    if size:
        descriptors.append(size)
    chunk_count = metadata.get("chunkCount")
    if chunk_count:
        descriptors.append(f"{chunk_count} sections indexed")
    lines.append("Type: " + " · ".join(str(part) for part in descriptors))

    if record.url:
        lines.append(f"URL: {record.url}")

    outline = metadata.get("outline") or []
    if outline:
        headings = [str(entry.get("heading", "")).strip() for entry in outline[:8]]
        headings = [heading for heading in headings if heading]
        if headings:
            lines.append("Outline: " + "; ".join(headings))

    summary = (metadata.get("summary") or "").strip()
    if summary:
        lines.append(f"Summary: {summary}")

    tables = metadata.get("tables") or []
    for table in tables:
        card = table.get("schemaCard")
        if card:
            lines.append(card)
    if tables:
        names = ", ".join(f'"{table.get("table")}"' for table in tables if table.get("table"))
        lines.append(
            f"Answer numeric questions about {names} with query_source_table(sql=...) - "
            "aggregate in SQL rather than estimating from the sample rows."
        )

    routing = _routing_lines(record)
    if routing:
        lines.append(routing)

    if chunk_count:
        lines.append(
            f'Read it with: search_sources(query, source_ids=["{record.id}"]), then '
            "read_source_section(source_id, start_chunk, chunk_count) for surrounding text."
        )

    if label:
        lines.append(label)

    return Attachment(
        id=f"{SOURCE_CARD_PREFIX}-{record.id}",
        type="image" if record.kind == "image" else "file",
        name=record.name,
        url=record.url or "",
        mime_type=record.mime_type or "text/markdown",
        size_bytes=record.size_bytes,
        path=(
            metadata.get("dashboardTemplatePath")
            or metadata.get("localFilePath")
            or metadata.get("samSegmentationPath")
            or metadata.get("imageSearchPath")
        ),
        extracted_text="\n".join(lines),
    )


def build_retrieved_context_attachment(
    content: str,
    scope: SourceScope,
    *,
    index: Any,
    top_k: int | None = None,
    label: str = "",
) -> Attachment | None:
    """Retrieve the passages most relevant to this turn's question.

    Injected eagerly so the common single-fact question is answered
    without a tool call; the skills remain available for anything deeper.
    Returns ``None`` when there is nothing worth retrieving, and never
    raises — a retrieval outage degrades to a card-only turn.
    """
    if index is None or not scope.source_ids:
        return None
    if len((content or "").strip()) < MIN_QUERY_CHARS:
        return None

    try:
        from openbench.core.abstractions import Query

        result = index.search(
            Query(
                text=content,
                filters={"source_ids": list(scope.source_ids), "owner": scope.owner},
                limit=top_k or retrieval_top_k(),
            )
        )
    except Exception:
        logger.warning("Source retrieval failed; sending cards only", exc_info=True)
        return None

    items = list(getattr(result, "items", []) or [])
    if not items:
        return None

    blocks: list[str] = []
    for item in items:
        metadata = item.get("metadata") or {}
        heading = metadata.get("heading")
        location = f"{metadata.get('name') or metadata.get('source_id')}"
        if heading:
            location += f" — {heading}"
        page = metadata.get("page")
        if page is not None:
            location += f" (page {page})"
        location += f" [chunk {metadata.get('chunk_index')}]"
        blocks.append(f"### {location}\n\n{item.get('content', '')}")

    body = "\n\n".join(blocks)
    header = (
        "Passages retrieved from the user's sources for this question. "
        "They may be incomplete: if the answer is not here, call search_sources "
        "with different wording before saying the sources do not cover it."
    )
    text = f"{header}\n\n{label}\n\n{body}" if label else f"{header}\n\n{body}"

    return Attachment(
        id=RETRIEVED_CONTEXT_ID,
        type="file",
        name="retrieved-context.md",
        url="",
        mime_type="text/markdown",
        extracted_text=text,
    )


def apply_card_budget(attachments: list[Attachment], budget: int | None = None) -> list[Attachment]:
    """Trim the card list if it somehow grows past its advisory cap.

    Cards are small by construction, so this should never fire; it exists
    so a pathological session degrades instead of failing the request.
    """
    limit = card_budget() if budget is None else budget
    if limit <= 0:
        return attachments
    total = sum(len(a.extracted_text or "") for a in attachments)
    if total <= limit:
        return attachments

    logger.warning("Source cards exceeded the card budget (%d > %d chars); trimming", total, limit)
    kept: list[Attachment] = []
    used = 0
    for attachment in attachments:
        size = len(attachment.extracted_text or "")
        if used + size > limit and kept:
            continue
        used += size
        kept.append(attachment)
    return kept


def build_source_attachments(
    records: list,
    content: str,
    *,
    index: Any = None,
    label: str = "",
    legacy_builder: Any = None,
) -> list[Attachment]:
    """Build this turn's source attachments.

    Args:
        records: Ready source records for this turn, including any
            admin-curated global sources.
        content: The user's message, used as the retrieval query.
        index: The document index, or ``None``.
        label: Framing line for injected source material.
        legacy_builder: Callable rendering records the old way, used for
            ``full`` mode and for sources that are not indexed.

    Returns:
        Cards plus retrieved passages, plus full text for anything not
        indexed.
    """
    mode = source_context_mode()
    if mode == MODE_FULL or not records:
        set_source_scope(None)
        return list(legacy_builder(records)) if legacy_builder and records else []

    indexed = [record for record in records if is_indexed(record)]
    legacy = [record for record in records if not is_indexed(record)]

    scope = SourceScope(
        session_id=next((r.session_id for r in indexed), ""),
        owner=next((r.owner for r in indexed), ""),
        source_ids=tuple(record.id for record in indexed),
    )
    set_source_scope(scope if indexed else None)

    attachments = [build_source_card(record, label=label) for record in indexed]
    attachments = apply_card_budget(attachments)

    if indexed:
        retrieved = build_retrieved_context_attachment(content, scope, index=index, label=label)
        if retrieved is not None:
            attachments.append(retrieved)

    # An un-indexed source still has to reach the model somehow, and its
    # full text is the only representation available. In `cards` mode the
    # operator has opted out of that entirely.
    if legacy and legacy_builder and mode != MODE_CARDS:
        attachments.extend(legacy_builder(legacy))

    return attachments


__all__ = [
    "DEFAULT_CARD_BUDGET",
    "DEFAULT_RETRIEVAL_TOP_K",
    "MODE_AUTO",
    "MODE_CARDS",
    "MODE_FULL",
    "RETRIEVED_CONTEXT_ID",
    "SourceScope",
    "apply_card_budget",
    "build_retrieved_context_attachment",
    "build_source_attachments",
    "build_source_card",
    "current_source_scope",
    "is_indexed",
    "set_source_scope",
    "source_context_mode",
]
