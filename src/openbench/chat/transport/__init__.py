"""
Chat transport layer (AG-UI and OpenAI-compatible protocols).

Public API:
    from openbench.chat.transport import AGUIHandler, AGUIActionHandler, ActionData
    from openbench.chat.transport import OpenAICompatHandler
"""

from openbench.chat.transport.agui import AGUIHandler
from openbench.chat.transport.agui_actions import ActionData, AGUIActionHandler
from openbench.chat.transport.openai_compat import (
    OpenAICompatHandler,
    create_openai_compatible_router,
)

__all__ = [
    "AGUIHandler",
    "AGUIActionHandler",
    "ActionData",
    "OpenAICompatHandler",
    "create_openai_compatible_router",
]
