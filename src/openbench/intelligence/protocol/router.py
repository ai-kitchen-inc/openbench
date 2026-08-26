"""LLM-backed message routing over an agent directory.

:func:`route` performs one small non-streaming LLM classification: the
prompt lists every registered descriptor and demands a JSON-only reply
naming the best specialist (or ``null``). Parsing is defensive — any
failure degrades to "no specialist" so a router hiccup can never take
down a chat turn.

The LLM call itself is injected as a plain ``prompt -> text`` callable,
keeping this module free of provider dependencies and trivially testable.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from openbench.intelligence.protocol.descriptor import AgentDescriptor, AgentDirectory

logger = logging.getLogger(__name__)

DEFAULT_MAX_MESSAGE_CHARS = 2000

_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z0-9]*\s*|\s*```$")


@dataclass
class RouteDecision:
    """Outcome of one routing classification.

    Attributes:
        agent_id: Chosen specialist id, or None when no specialist fits
            (the caller should use its default agent).
        reason: Short human-readable note on how the decision was made.
        fallback_used: True when the LLM call failed or returned something
            unparseable and the decision defaulted to None.
    """

    agent_id: str | None
    reason: str = ""
    fallback_used: bool = False


def build_router_prompt(
    message: str,
    descriptors: Sequence[AgentDescriptor],
    max_message_chars: int = DEFAULT_MAX_MESSAGE_CHARS,
) -> str:
    """Compose the dispatcher prompt for one message + descriptor list."""
    lines = [
        "You are a dispatcher. Choose the single best specialist agent for the",
        "user's message, or null if none clearly fits.",
        "",
        "Agents:",
    ]
    for descriptor in descriptors:
        description = descriptor.description.strip() or "(no description)"
        lines.append(f"- {descriptor.id} — {descriptor.name}: {description}")
    truncated = message[:max_message_chars]
    lines += [
        "",
        "User message:",
        f'"""{truncated}"""',
        "",
        'Reply with JSON only, no code fences: {"agent": "<agent-id>"} or {"agent": null}',
    ]
    return "\n".join(lines)


def _parse_decision(raw: str, known_ids: set[str]) -> RouteDecision | None:
    """Parse the LLM reply; None means unparseable (caller falls back)."""
    text = raw.strip()
    if not text:
        return None
    text = _CODE_FENCE_RE.sub("", text).strip()
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        payload = None
    if isinstance(payload, dict) and "agent" in payload:
        chosen = payload["agent"]
        if chosen is None:
            return RouteDecision(None, reason="router: no specialist fits")
        if isinstance(chosen, str):
            candidate = chosen.strip()
            if candidate in known_ids:
                return RouteDecision(candidate, reason="router: JSON match")
            return None
    # Last resort: the reply mentioned exactly one known id in plain text.
    mentioned = [agent_id for agent_id in known_ids if agent_id in text]
    if len(mentioned) == 1:
        return RouteDecision(mentioned[0], reason="router: id scan match")
    return None


def route(
    message: str,
    directory: AgentDirectory,
    complete: Callable[[str], str],
    max_message_chars: int = DEFAULT_MAX_MESSAGE_CHARS,
) -> RouteDecision:
    """Classify ``message`` against the directory's descriptors.

    Args:
        message: The raw user message.
        directory: Registered specialists. Empty directory short-circuits
            to ``RouteDecision(None)`` without calling the LLM.
        complete: Injected LLM call, ``prompt -> reply text``.
        max_message_chars: Cap on message text sent to the router.

    Returns:
        A :class:`RouteDecision`; ``agent_id`` is None whenever the
        default agent should handle the turn.
    """
    descriptors = directory.descriptors()
    if not descriptors:
        return RouteDecision(None, reason="no agents registered")
    prompt = build_router_prompt(message, descriptors, max_message_chars)
    try:
        raw = complete(prompt)
    except Exception:
        logger.warning("Agent router LLM call failed; using default agent", exc_info=True)
        return RouteDecision(None, reason="router call failed", fallback_used=True)
    decision = _parse_decision(raw or "", {d.id for d in descriptors})
    if decision is None:
        logger.warning("Agent router reply unparseable (%.120r); using default agent", raw)
        return RouteDecision(None, reason="router reply unparseable", fallback_used=True)
    return decision
