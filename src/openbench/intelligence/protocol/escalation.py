"""Confidence marker protocol for low-confidence escalation.

Specialist agents are instructed (via :data:`CONFIDENCE_PROTOCOL_PROMPT`,
appended to their persona rules) to end every answer with a trailing
machine-readable marker::

    [[CONFIDENCE=0.8]]

:func:`extract_confidence` strips the marker and parses the value. A
missing marker means "confident" (returns ``None``) — a formatting miss
can only ever under-escalate, never loop or spuriously escalate. This
costs zero extra LLM calls, unlike judge-model approaches.
"""

from __future__ import annotations

import re

DEFAULT_CONFIDENCE_THRESHOLD = 0.5

#: Matches a trailing confidence marker (with optional surrounding
#: whitespace) at the very end of the answer. Values like ``1``, ``0.75``.
CONFIDENCE_MARKER_RE = re.compile(r"\s*\[\[CONFIDENCE=([01](?:\.\d+)?)\]\]\s*$")

#: Appended to a specialist's persona rules when its profile has an
#: escalation target. English instruction text is deliberate — the models
#: in use follow it regardless of the persona's answer language.
CONFIDENCE_PROTOCOL_PROMPT = """\
## Confidence Protocol
At the very end of every answer, on its own final line, append a machine-readable
confidence marker in exactly this form:

[[CONFIDENCE=0.8]]

- Use a value from 0.0 to 1.0 estimating how confident you are that the answer is
  correct and complete for THIS question.
- Below 0.5 means: the question falls outside your specialty, required data is
  missing, or you had to guess.
- The marker is stripped before the user sees the answer. Never mention it, never
  explain it, never place it anywhere except the final line."""


def extract_confidence(text: str) -> tuple[str, float | None]:
    """Strip the trailing confidence marker and parse its value.

    Args:
        text: Raw agent answer.

    Returns:
        ``(stripped_text, confidence)``. ``confidence`` is None when no
        valid trailing marker is present (the text is returned unchanged,
        modulo nothing — mid-text markers are left alone on purpose).
    """
    if not text:
        return text, None
    match = CONFIDENCE_MARKER_RE.search(text)
    if match is None:
        return text, None
    stripped = text[: match.start()].rstrip()
    value = float(match.group(1))
    # A syntactically-matched but out-of-range value (e.g. 1.5) is still
    # protocol junk the user must never see: strip it, report no confidence.
    if value > 1.0:
        return stripped, None
    return stripped, value
