"""
OpenBench Chat Layer.

Provides a complete backend for interactive chat UIs powered by A2UI v0.10
(Google's declarative JSON streaming UI protocol).

Public API:
    from openbench.chat import ChatEngine, ChatLayer, ChatSession
    from openbench.chat import A2UIMessageBuilder, A2UIComponent
    from openbench.chat import ContentRenderer, ContentRendererRegistry
"""

from openbench.chat import render_queue
from openbench.chat.a2ui import (
    A2UI_VERSION,
    OPENBENCH_CATALOG_ID,
    A2UIComponent,
    A2UIMessage,
    A2UIMessageBuilder,
)
from openbench.chat.engine import ChatEngine
from openbench.chat.layer import ChatFactory, ChatLayer
from openbench.chat.renderers import (
    CalloutRenderer,
    ChartRenderer,
    CodeRenderer,
    ContentRenderer,
    ContentRendererRegistry,
    FileRenderer,
    FormRenderer,
    ListRenderer,
    MediaRenderer,
    ModalRenderer,
    TableRenderer,
    TabsRenderer,
    TextRenderer,
)
from openbench.chat.session import (
    Attachment,
    ChatMessage,
    ChatSession,
    MessageRole,
)
from openbench.chat.session_store import SessionStore, SessionSummary

__all__ = [
    # Engine + Layer
    "ChatEngine",
    "ChatLayer",
    "ChatFactory",
    # Shared render-items queue for SDK skills
    "render_queue",
    # Session
    "ChatSession",
    "ChatMessage",
    "MessageRole",
    "Attachment",
    "SessionStore",
    "SessionSummary",
    # A2UI
    "A2UI_VERSION",
    "A2UIComponent",
    "A2UIMessage",
    "A2UIMessageBuilder",
    "OPENBENCH_CATALOG_ID",
    # Renderers
    "ContentRenderer",
    "ContentRendererRegistry",
    "TextRenderer",
    "ChartRenderer",
    "CodeRenderer",
    "FormRenderer",
    "FileRenderer",
    "MediaRenderer",
    "ListRenderer",
    "TabsRenderer",
    "ModalRenderer",
    "TableRenderer",
    "CalloutRenderer",
]
