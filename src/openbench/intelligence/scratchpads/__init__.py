"""Concrete ScratchpadStore implementations.

- :class:`LocalMarkdownScratchpad` — filesystem-backed default.
"""

from __future__ import annotations

from openbench.intelligence.scratchpads.local_md import LocalMarkdownScratchpad

__all__ = ["LocalMarkdownScratchpad"]
