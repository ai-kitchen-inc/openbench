"""AG-UI protocol transport.

This package was split out of the former single ``agui.py`` module into focused
mixins (session lifecycle, event streaming, content extraction) assembled into
``AGUIHandler``. The public surface is unchanged:
``from openbench.chat.transport.agui import AGUIHandler, A2UIStreamMessage``.
"""

from __future__ import annotations

from openbench.chat.transport.agui.handler import AGUIHandler
from openbench.chat.transport.agui.messages import A2UIStreamMessage

__all__ = ["A2UIStreamMessage", "AGUIHandler"]
