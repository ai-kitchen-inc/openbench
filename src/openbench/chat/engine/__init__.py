"""Chat engine package.

Split out of the former single ``engine.py`` module: orchestration entrypoints
live in ``engine.py`` and are assembled with agent-execution, content-rendering,
and session mixins. Public surface unchanged:
``from openbench.chat.engine import ChatEngine``.
"""

from __future__ import annotations

from openbench.chat.engine.engine import ChatEngine

__all__ = ["ChatEngine"]
