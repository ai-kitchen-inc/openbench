"""Tools for the source-retrieval SDK skill.

The document index and the current turn's scope are injected by the host
application via :func:`bind`. Nothing here reaches the filesystem or a
database directly, and every requested source id is intersected with the
bound scope, so a model that guesses an id gets an error rather than
another user's data.

Every tool returns a plain dict and never raises: an unavailable index or
an out-of-scope id is reported as ``{"error": ...}`` so the agent can
recover in the same turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "OUTLINE_SOURCE_SCHEMA",
    "READ_SOURCE_SECTION_SCHEMA",
    "SEARCH_SOURCES_SCHEMA",
    "bind",
    "outline_source",
    "read_source_section",
    "search_sources",
]

#: Hard ceilings so a single tool call cannot refill the context window
#: with the document text this skill exists to keep out of the prompt.
MAX_TOP_K = 12
MAX_SECTION_CHUNKS = 12
MAX_SECTION_CHARS = 24_000


# ---------------------------------------------------------------------------
# Bound dependencies (populated by skill.bind() at agent build)
# ---------------------------------------------------------------------------

_source_index: Any | None = None
_source_scope_provider: Callable[[], Any] | None = None


def bind(
    source_index: Any = None,
    source_scope_provider: Callable[[], Any] | None = None,
    **_: object,
) -> None:
    """Inject the document index and the turn-scope accessor.

    Called by :meth:`SkillRegistry.bind` during :class:`BaseAgent`
    construction. Extra kwargs are ignored so other bindings can layer on.

    Args:
        source_index: A ``DocumentIndexStore``-shaped object exposing
            ``search``, ``read_range``, ``outline``, and ``summarize_source``.
        source_scope_provider: Zero-argument callable returning the current
            turn's scope, with ``source_ids``, ``session_id``, and ``owner``
            attributes. Read per call so one registration serves every
            request without mutating shared state.
    """
    global _source_index, _source_scope_provider
    _source_index = source_index
    _source_scope_provider = source_scope_provider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error(message: str) -> dict[str, Any]:
    return {"error": message}


def _scope() -> Any | None:
    if _source_scope_provider is None:
        return None
    try:
        return _source_scope_provider()
    except Exception:
        return None


def _scoped_ids() -> list[str]:
    """Source ids the current turn is allowed to read."""
    scope = _scope()
    ids = getattr(scope, "source_ids", None) or []
    return [str(value) for value in ids]


def _resolve_ids(requested: list[str] | None) -> tuple[list[str], str | None]:
    """Intersect requested ids with the turn's scope.

    Returns:
        ``(ids, error)``. ``error`` is set when a requested id is not in
        scope, so the caller reports it rather than silently widening or
        narrowing the search.
    """
    allowed = _scoped_ids()
    if not allowed:
        return [], "No sources are available in this conversation."
    if not requested:
        return allowed, None

    wanted = [str(value) for value in requested]
    unknown = [value for value in wanted if value not in allowed]
    if unknown:
        return [], (
            f"Unknown source id(s): {', '.join(unknown)}. "
            f"Use an id from the source cards in this conversation: {', '.join(allowed)}"
        )
    return wanted, None


def _hit(item: dict[str, Any], score: float) -> dict[str, Any]:
    """Flatten an index item into a compact result row."""
    metadata = item.get("metadata") or {}
    hit = {
        "source_id": metadata.get("source_id"),
        "source_name": metadata.get("name") or metadata.get("source_id"),
        "chunk_index": metadata.get("chunk_index"),
        "total_chunks": metadata.get("total_chunks"),
        "score": round(float(score), 4),
        "content": item.get("content", ""),
    }
    for key in ("heading", "page", "sheet"):
        if metadata.get(key) is not None:
            hit[key] = metadata[key]
    return hit


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def search_sources(
    query: str,
    source_ids: list[str] | None = None,
    top_k: int = 6,
) -> dict[str, Any]:
    """Find the passages most relevant to a query.

    Args:
        query: What to look for, in the user's own wording.
        source_ids: Restrict to these sources. Omit to search all
            sources available in this conversation.
        top_k: Maximum passages to return (capped at 12).

    Returns:
        ``{"query", "results": [...], "count"}`` or ``{"error": ...}``.
    """
    if _source_index is None:
        return _error("Source search is not available in this deployment.")
    if not (query or "").strip():
        return _error("Provide a search query.")

    ids, scope_error = _resolve_ids(source_ids)
    if scope_error:
        return _error(scope_error)

    limit = max(1, min(int(top_k or 6), MAX_TOP_K))

    try:
        from openbench.core.abstractions import Query

        # ids already carry the turn's authorization (intersection with the
        # scope above), and they may span owners — session sources plus
        # admin-curated globals. An owner filter on top would silently drop
        # every source that does not share the scope's single owner value.
        result = _source_index.search(
            Query(
                text=query,
                filters={"source_ids": ids},
                limit=limit,
            )
        )
    except Exception as exc:
        return _error(f"Search failed: {exc}")

    items = list(getattr(result, "items", []) or [])
    scores = list(getattr(result, "scores", []) or [])
    scores += [0.0] * (len(items) - len(scores))
    # scores is padded to at least len(items) above; a store that returns
    # extra scores should not cost the user their results.
    hits = [_hit(item, score) for item, score in zip(items, scores, strict=False)]

    return {"query": query, "results": hits, "count": len(hits)}


def read_source_section(
    source_id: str,
    start_chunk: int = 0,
    chunk_count: int = 4,
) -> dict[str, Any]:
    """Read consecutive passages from one source.

    Use after ``search_sources`` when a hit is cut off or you need the
    text around it.

    Args:
        source_id: Id from a source card.
        start_chunk: Zero-based passage index to start at.
        chunk_count: How many consecutive passages to read (capped at 12).

    Returns:
        ``{"source_id", "sections": [...], "count", "truncated"}`` or
        ``{"error": ...}``.
    """
    if _source_index is None:
        return _error("Source reading is not available in this deployment.")

    ids, scope_error = _resolve_ids([source_id] if source_id else None)
    if scope_error:
        return _error(scope_error)
    if not ids:
        return _error("Provide a source_id from one of the source cards.")

    start = max(0, int(start_chunk or 0))
    count = max(1, min(int(chunk_count or 4), MAX_SECTION_CHUNKS))

    try:
        items = _source_index.read_range(ids[0], start_index=start, chunk_count=count)
    except Exception as exc:
        return _error(f"Could not read that section: {exc}")

    sections: list[dict[str, Any]] = []
    used = 0
    truncated = False
    for item in items:
        content = item.get("content", "")
        if used + len(content) > MAX_SECTION_CHARS and sections:
            truncated = True
            break
        used += len(content)
        sections.append(_hit(item, 1.0))

    if not sections:
        return {
            "source_id": ids[0],
            "sections": [],
            "count": 0,
            "truncated": False,
            "note": f"No passages at index {start}; the document may be shorter than that.",
        }

    return {
        "source_id": ids[0],
        "sections": sections,
        "count": len(sections),
        "truncated": truncated,
    }


def outline_source(source_id: str) -> dict[str, Any]:
    """List a document's headings and the passage index each begins at.

    Args:
        source_id: Id from a source card.

    Returns:
        ``{"source_id", "outline": [...], "count"}`` or ``{"error": ...}``.
    """
    if _source_index is None:
        return _error("Source outlines are not available in this deployment.")

    ids, scope_error = _resolve_ids([source_id] if source_id else None)
    if scope_error:
        return _error(scope_error)
    if not ids:
        return _error("Provide a source_id from one of the source cards.")

    try:
        outline = _source_index.outline(ids[0])
    except Exception as exc:
        return _error(f"Could not read that outline: {exc}")

    return {"source_id": ids[0], "outline": outline, "count": len(outline)}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


SEARCH_SOURCES_SCHEMA = _schema(
    "search_sources",
    "Search the user's uploaded documents for passages relevant to a query. "
    "Call this before answering any question about an uploaded document whose "
    "answer is not already in context.",
    {
        "query": {
            "type": "string",
            "description": "What to look for, in the user's own wording.",
        },
        "source_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Restrict the search to these source ids (from the source cards). "
                "Omit to search every source in this conversation."
            ),
        },
        "top_k": {
            "type": "integer",
            "description": "Maximum passages to return. Default 6, maximum 12.",
        },
    },
    ["query"],
)

READ_SOURCE_SECTION_SCHEMA = _schema(
    "read_source_section",
    "Read consecutive passages from one document. Use after search_sources "
    "when a result is cut off or you need the surrounding context.",
    {
        "source_id": {
            "type": "string",
            "description": "Source id from a source card.",
        },
        "start_chunk": {
            "type": "integer",
            "description": "Zero-based passage index to start reading at.",
        },
        "chunk_count": {
            "type": "integer",
            "description": "How many consecutive passages to read. Default 4, maximum 12.",
        },
    },
    ["source_id"],
)

OUTLINE_SOURCE_SCHEMA = _schema(
    "outline_source",
    "List a document's headings and the passage index where each begins, "
    "to decide what to read next.",
    {
        "source_id": {
            "type": "string",
            "description": "Source id from a source card.",
        },
    },
    ["source_id"],
)
