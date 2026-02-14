"""
ChatEngine -- main chat orchestrator.

Processes user input through an agent, auto-detects content types,
runs content renderers, and builds A2UI v0.10 JSONL output.

Inherits from Chainable for composability with OpenBench layers.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

from openbench.chat.a2ui.builder import A2UIMessageBuilder
from openbench.chat.a2ui.catalog import OPENBENCH_CATALOG_ID
from openbench.chat.a2ui.schema import (
    A2UIComponent,
    StepCompleteMessage,
    StepStartMessage,
    StreamMessage,
    StreamMessageType,
)
from openbench.chat.renderers.base import ContentRenderer, ContentRendererRegistry
from openbench.chat.session import ChatSession
from openbench.core.abstractions import Agent, ExecutionContext, ExecutionResult, FrameworkAdapter
from openbench.core.chainable import Chainable, RunnableConfig

logger = logging.getLogger(__name__)


def _get_default_renderers() -> list[ContentRenderer]:
    """Create default renderer instances from registry."""
    renderers: list[ContentRenderer] = []
    for key in ContentRendererRegistry.list_plugins():
        try:
            plugin_type, provider = key.split(":", 1)
            renderer = ContentRendererRegistry.create(plugin_type, provider)
            renderers.append(renderer)
        except Exception:
            logger.warning(f"Failed to create renderer: {key}")
    return renderers


class ChatEngine(Chainable[Any, dict[str, Any]]):
    """Orchestrates: user input -> agent -> content renderers -> A2UI v0.10 JSONL.

    Composable with existing L1/L2 components:
        DataLayer(sources) | ChatEngine(agent=my_agent)
        ChatEngine(agent) | OutputLayer(generators=[transcript])

    Usage:
        engine = ChatEngine(agent=my_agent)
        result = engine.invoke({"content": "Show Q4 sales"})
        # result = {"messages": [...], "session": ChatSession, "metadata": {...}}
    """

    def __init__(
        self,
        agent: Agent | FrameworkAdapter,
        renderers: list[ContentRenderer] | None = None,
        session: ChatSession | None = None,
        catalog_id: str | None = None,
    ):
        """Initialize ChatEngine.

        Args:
            agent: Agent or FrameworkAdapter to process messages.
            renderers: Content renderers (auto-detected from registry if None).
            session: Existing chat session (creates new if None).
            catalog_id: A2UI catalog ID (default: OPENBENCH_CATALOG_ID).
        """
        self.agent = agent
        self.renderers = renderers if renderers is not None else _get_default_renderers()
        self.session = session if session is not None else ChatSession()
        self.builder = A2UIMessageBuilder(catalog_id=catalog_id or OPENBENCH_CATALOG_ID)

    def invoke(self, input: Any, config: RunnableConfig | None = None) -> dict[str, Any]:
        """Process a single message turn.

        Input: {"content": "...", "attachments": [...], "session_id": "..."}
              or a plain string
              or a dict from a previous layer (with "content" or "intelligence_output")

        Output: {
            "messages": [A2UI v0.10 message dicts],
            "session": ChatSession,
            "metadata": {"model": "...", "tokens_used": ..., ...}
        }
        """
        # 1. Parse input
        content, attachments = self._parse_input(input)

        # 2. Add user message to session
        self.session.add_user_message(content, attachments=attachments)

        # 3. Execute agent
        agent_result = self._execute_agent(content, config)

        # 4. Extract agent output
        agent_output = self._extract_output(agent_result)
        metadata = self._extract_metadata(agent_result)

        # 5. Render content to A2UI components
        components = self._render_content(agent_output)

        # 6. Ensure root component
        components = self._ensure_root(components)

        # 7. Build A2UI JSONL messages
        surface_id = f"s-{uuid.uuid4().hex[:8]}"
        messages = self.builder.build_surface(surface_id, components)

        # 8. Build text content for session history
        text_content = self._extract_text_content(agent_output)

        # 9. Add assistant message to session
        self.session.add_assistant_message(
            content=text_content,
            surfaces=[{"surfaceId": surface_id}],
            metadata=metadata,
        )

        return {
            "messages": messages,
            "session": self.session,
            "metadata": metadata,
        }

    def stream(self, input: Any, config: RunnableConfig | None = None) -> Iterator[str]:
        """Stream A2UI v0.10 JSONL lines with step-by-step progress.

        Yields JSON strings (one per line) with step indicators:
        stream_start → step_start("Processing input") → step_complete →
        step_start("Thinking") → step_complete →
        step_start("Rendering response") → A2UI messages → step_complete →
        stream_end
        """
        import json

        message_id = f"msg-{uuid.uuid4().hex[:8]}"

        def _step_id() -> str:
            return f"step-{uuid.uuid4().hex[:8]}"

        # Stream start
        start = StreamMessage(
            type=StreamMessageType.STREAM_START,
            message_id=message_id,
        )
        yield json.dumps(start.to_dict())

        try:
            # ── Step 1: Processing input ──
            sid = _step_id()
            yield json.dumps(
                StepStartMessage(sid, "Processing input", message_id).to_dict()
            )
            content, attachments = self._parse_input(input)
            self.session.add_user_message(content, attachments=attachments)
            yield json.dumps(
                StepCompleteMessage(sid, message_id).to_dict()
            )

            # ── Step 2: Thinking ──
            sid = _step_id()
            yield json.dumps(
                StepStartMessage(sid, "Thinking", message_id).to_dict()
            )
            agent_result = self._execute_agent(content, config)
            agent_output = self._extract_output(agent_result)
            metadata = self._extract_metadata(agent_result)
            yield json.dumps(
                StepCompleteMessage(sid, message_id).to_dict()
            )

            # ── Step 3: Rendering response ──
            sid = _step_id()
            yield json.dumps(
                StepStartMessage(sid, "Rendering response", message_id).to_dict()
            )
            components = self._render_content(agent_output)
            components = self._ensure_root(components)
            surface_id = f"s-{uuid.uuid4().hex[:8]}"
            messages = self.builder.build_surface(surface_id, components)

            # Yield each A2UI message individually
            for msg in messages:
                yield json.dumps(msg)

            yield json.dumps(
                StepCompleteMessage(sid, message_id).to_dict()
            )

            # Build text content for session history
            text_content = self._extract_text_content(agent_output)
            self.session.add_assistant_message(
                content=text_content,
                surfaces=[{"surfaceId": surface_id}],
                metadata=metadata,
            )

            # Stream end
            end = StreamMessage(
                type=StreamMessageType.STREAM_END,
                message_id=message_id,
                metadata=metadata,
            )
            yield json.dumps(end.to_dict())

        except Exception as e:
            logger.error(f"Stream error: {e}")
            error = StreamMessage(
                type=StreamMessageType.ERROR,
                message_id=message_id,
                metadata={"error": str(e)},
            )
            yield json.dumps(error.to_dict())

    async def async_stream(
        self, input: Any, config: RunnableConfig | None = None
    ) -> AsyncIterator[str]:
        """Async version of stream() for WebSocket handlers.

        Runs the blocking agent call in a thread pool so the event loop
        can flush WebSocket frames between steps.
        """
        import json

        message_id = f"msg-{uuid.uuid4().hex[:8]}"

        def _step_id() -> str:
            return f"step-{uuid.uuid4().hex[:8]}"

        # Stream start
        yield json.dumps(
            StreamMessage(
                type=StreamMessageType.STREAM_START, message_id=message_id
            ).to_dict()
        )

        try:
            # ── Step 1: Processing input ──
            sid = _step_id()
            yield json.dumps(
                StepStartMessage(sid, "Processing input", message_id).to_dict()
            )
            content, attachments = self._parse_input(input)
            self.session.add_user_message(content, attachments=attachments)
            yield json.dumps(StepCompleteMessage(sid, message_id).to_dict())

            # ── Step 2: Thinking (run in thread pool) ──
            sid = _step_id()
            yield json.dumps(
                StepStartMessage(sid, "Thinking", message_id).to_dict()
            )
            agent_result = await asyncio.to_thread(self._execute_agent, content, config)
            agent_output = self._extract_output(agent_result)
            metadata = self._extract_metadata(agent_result)
            yield json.dumps(StepCompleteMessage(sid, message_id).to_dict())

            # ── Step 3: Rendering response ──
            sid = _step_id()
            yield json.dumps(
                StepStartMessage(sid, "Rendering response", message_id).to_dict()
            )
            components = self._render_content(agent_output)
            components = self._ensure_root(components)
            surface_id = f"s-{uuid.uuid4().hex[:8]}"
            messages = self.builder.build_surface(surface_id, components)

            for msg in messages:
                yield json.dumps(msg)

            yield json.dumps(StepCompleteMessage(sid, message_id).to_dict())

            # Session history
            text_content = self._extract_text_content(agent_output)
            self.session.add_assistant_message(
                content=text_content,
                surfaces=[{"surfaceId": surface_id}],
                metadata=metadata,
            )

            # Stream end
            yield json.dumps(
                StreamMessage(
                    type=StreamMessageType.STREAM_END,
                    message_id=message_id,
                    metadata=metadata,
                ).to_dict()
            )

        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield json.dumps(
                StreamMessage(
                    type=StreamMessageType.ERROR,
                    message_id=message_id,
                    metadata={"error": str(e)},
                ).to_dict()
            )

    def _parse_input(self, input: Any) -> tuple[str, list | None]:
        """Parse input into content string and optional attachments."""
        if isinstance(input, str):
            return input, None

        if isinstance(input, dict):
            # Direct chat input
            if "content" in input:
                return input["content"], input.get("attachments")
            # From IntelligenceLayer or other layer
            if "intelligence_output" in input:
                output = input["intelligence_output"]
                if isinstance(output, ExecutionResult):
                    return str(output.output), None
                return str(output), None
            # From DataLayer
            if "raw_data" in input:
                return str(input), None

        return str(input), None

    def _execute_agent(self, content: str, config: RunnableConfig | None) -> Any:
        """Execute the agent with the given content."""
        if isinstance(self.agent, Agent):
            context = ExecutionContext(
                goal=content,
                data={"session": self.session.to_dict()},
            )
            return self.agent.execute(context)
        elif isinstance(self.agent, FrameworkAdapter):
            return self.agent.invoke(content, config)
        else:
            return self.agent.invoke(content, config)

    def _extract_output(self, result: Any) -> Any:
        """Extract the output content from agent result."""
        if isinstance(result, ExecutionResult):
            return result.output
        if isinstance(result, dict) and "output" in result:
            return result["output"]
        return result

    def _extract_metadata(self, result: Any) -> dict[str, Any]:
        """Extract metadata from agent result."""
        if isinstance(result, ExecutionResult):
            meta: dict[str, Any] = dict(result.metadata)
            if result.tokens_used:
                meta["tokens_used"] = result.tokens_used
            if result.cost:
                meta["cost"] = result.cost
            return meta
        if isinstance(result, dict) and "metadata" in result:
            return result["metadata"]
        return {}

    def _render_content(self, content: Any) -> list[A2UIComponent]:
        """Auto-detect content type and render to A2UI components."""
        for renderer in self.renderers:
            if renderer.detect(content):
                return renderer.render(content, surface_id="")

        # Fallback: render as text
        return [A2UIComponent(
            id="txt-fallback",
            component="Text",
            properties={"text": str(content), "variant": "body"},
        )]

    def _ensure_root(self, components: list[A2UIComponent]) -> list[A2UIComponent]:
        """Ensure there's a component with id='root'.

        If multiple components, wrap them in a Column root.
        If single component, rename its id to 'root'.
        """
        has_root = any(c.id == "root" for c in components)
        if has_root:
            return components

        if len(components) == 1:
            components[0] = A2UIComponent(
                id="root",
                component=components[0].component,
                properties=components[0].properties,
            )
            return components

        # Multiple components: wrap in Column
        child_ids = [c.id for c in components]
        root = A2UIComponent(
            id="root",
            component="Column",
            properties={"children": child_ids},
        )
        return [root] + components

    def _extract_text_content(self, output: Any) -> str:
        """Extract plain text content for session history."""
        if isinstance(output, str):
            return output
        if isinstance(output, dict):
            if "text" in output:
                return str(output["text"])
            if "content" in output:
                return str(output["content"])
        return str(output)
