"""A2UI stream-message envelope emitted during an active agent run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class A2UIStreamMessage:
    """A2UI message emitted while an agent run is still active."""

    message: dict[str, Any]
