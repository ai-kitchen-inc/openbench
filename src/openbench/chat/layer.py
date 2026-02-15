"""
ChatLayer -- L2 chat orchestrator.

Composable with DataLayer, IntelligenceLayer, and OutputLayer
following the same patterns as existing OpenBench L2 layers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

try:
    from typing import NotRequired, TypedDict
except ImportError:
    from typing_extensions import NotRequired, TypedDict

from openbench.chat.engine import ChatEngine
from openbench.core.chainable import Chainable, RunnableConfig

if TYPE_CHECKING:
    from openbench.chat.renderers.base import ContentRenderer
    from openbench.core.abstractions import Agent, FrameworkAdapter
from openbench.core.layers import _preserve_input_params

logger = logging.getLogger(__name__)


class ChatLayerOutput(TypedDict):
    """Type contract for ChatLayer output."""

    chat_output: dict[str, Any]
    metadata: dict[str, Any]
    goal: NotRequired[str]
    output_path: NotRequired[str]
    title: NotRequired[str]
    author: NotRequired[str]
    template: NotRequired[str]


class ChatLayer(Chainable[Any, dict[str, Any]]):
    """L2 chat orchestrator -- composable with all OpenBench layers.

    Usage:
        # Standalone
        chat = ChatLayer(agent=my_agent)
        result = chat.invoke({"content": "Hello"})

        # With data pipeline
        workflow = DataLayer(sources=[pdf]) | ChatLayer(agent=rag_agent)

        # With output
        workflow = ChatLayer(agent=agent) | OutputLayer(generators=[transcript])

        # Full E2E
        workflow = DataLayer(...) | ChatLayer(...) | OutputLayer(...)
    """

    def __init__(
        self,
        agent: Agent | FrameworkAdapter,
        renderers: list[ContentRenderer] | None = None,
        catalog_id: str | None = None,
    ):
        """Initialize ChatLayer.

        Args:
            agent: Agent or FrameworkAdapter to process messages.
            renderers: Content renderers (auto-detected if None).
            catalog_id: A2UI catalog ID (default: OPENBENCH_CATALOG_ID).
        """
        self.engine = ChatEngine(
            agent=agent,
            renderers=renderers,
            catalog_id=catalog_id,
        )

    def invoke(self, input: Any, config: RunnableConfig | None = None) -> dict[str, Any]:
        """Execute chat layer.

        Accepts input from any upstream layer:
        - Direct: {"content": "Hello"}
        - From DataLayer: {"raw_data": [...], "metadata": {...}}
        - From IntelligenceLayer: {"intelligence_output": ..., "metadata": {...}}

        Returns:
            {
                "chat_output": dict,     # ChatEngine result (messages, session, metadata)
                "metadata": {"layer": "chat", ...},
                # preserved keys: goal, output_path, title, author, template
            }
        """
        # Extract content from upstream layer output
        chat_input = self._prepare_input(input)

        # Run ChatEngine
        engine_result = self.engine.invoke(chat_input, config)

        output: dict[str, Any] = {
            "chat_output": engine_result,
            "metadata": {
                "layer": "chat",
                "num_messages": len(engine_result.get("messages", [])),
            },
        }

        _preserve_input_params(output, input)
        return output

    def _prepare_input(self, input: Any) -> dict[str, Any]:
        """Prepare input for ChatEngine from various upstream formats."""
        if isinstance(input, str):
            return {"content": input}

        if isinstance(input, dict):
            # Already chat-format input
            if "content" in input:
                return input

            # From DataLayer
            if "raw_data" in input:
                raw_data = input["raw_data"]
                content_parts = []
                for item in raw_data:
                    if hasattr(item, "content"):
                        content_parts.append(str(item.content))
                    else:
                        content_parts.append(str(item))
                return {
                    "content": ("\n\n".join(content_parts) if content_parts else str(input)),
                }

            # From IntelligenceLayer
            if "intelligence_output" in input:
                return {"content": str(input["intelligence_output"])}

        return {"content": str(input)}


class ChatFactory:
    """Factory for creating ChatLayer instances with common configurations."""

    @staticmethod
    def create(
        agent: Agent | FrameworkAdapter,
        renderers: list[ContentRenderer] | None = None,
        catalog_id: str | None = None,
    ) -> ChatLayer:
        """Create a ChatLayer instance.

        Args:
            agent: Agent or FrameworkAdapter.
            renderers: Optional content renderers.
            catalog_id: Optional custom catalog ID.

        Returns:
            Configured ChatLayer instance.
        """
        return ChatLayer(agent=agent, renderers=renderers, catalog_id=catalog_id)
