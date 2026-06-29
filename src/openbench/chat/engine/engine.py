"""ChatEngine -- main chat orchestrator.

Processes user input through an agent, auto-detects content types, runs content
renderers, and builds A2UI v0.10 JSONL output. The orchestration entrypoints
live here; agent execution, content rendering, and session persistence are
provided by focused mixins. Inherits from Chainable for layer composability.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from openbench.chat.a2ui.builder import A2UIMessageBuilder
from openbench.chat.a2ui.catalog import OPENBENCH_CATALOG_ID
from openbench.chat.a2ui.schema import (
    StepCompleteMessage,
    StepStartMessage,
    StreamMessage,
    StreamMessageType,
)
from openbench.chat.engine.content import _A2UIContentMixin
from openbench.chat.engine.defaults import _get_default_renderers
from openbench.chat.engine.execution import _AgentExecutionMixin
from openbench.chat.engine.session import _SessionMixin
from openbench.chat.session import ChatSession
from openbench.core.chainable import Chainable, RunnableConfig

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

    from openbench.chat.renderers.base import ContentRenderer
    from openbench.chat.session_store import SessionStore
    from openbench.core.abstractions import Agent, FrameworkAdapter

logger = logging.getLogger(__name__)


class ChatEngine(
    _A2UIContentMixin, _AgentExecutionMixin, _SessionMixin, Chainable[Any, dict[str, Any]]
):
    """Orchestrates: user input -> agent -> content renderers -> A2UI v0.10 JSONL.

    Composable with existing L1/L2 components:
        DataLayer(sources) | ChatEngine(agent=my_agent)
        ChatEngine(agent) | OutputLayer(generators=[transcript])

    Usage:
        engine = ChatEngine(agent=my_agent)
        result = engine.invoke({"content": "Show Q4 sales"})
    """

    def __init__(
        self,
        agent: Agent | FrameworkAdapter,
        renderers: list[ContentRenderer] | None = None,
        session: ChatSession | None = None,
        catalog_id: str | None = None,
        render_items_fn: Callable[[], list[dict]] | None = None,
        clear_render_items_fn: Callable[[], None] | None = None,
        session_store: SessionStore | None = None,
    ):
        """Initialize ChatEngine.

        Args:
            agent: Agent or FrameworkAdapter to process messages.
            renderers: Content renderers (auto-detected from registry if None).
            session: Existing chat session (creates new if None).
            catalog_id: A2UI catalog ID (default: OPENBENCH_CATALOG_ID).
            render_items_fn: Optional callback that returns structured render items
                (chart dicts, form dicts, file dicts) accumulated by agent tools.
                Called after agent execution to collect side-channel visualizations.
            clear_render_items_fn: Optional callback to clear render items queue.
                Called before each agent execution for per-request isolation.
            session_store: Optional persistent store for ChatSessions.
                When provided, the session is saved after every user and
                assistant message — so a server crash between the two
                still leaves the user's message on disk.
        """
        self.agent = agent
        self.renderers = renderers if renderers is not None else _get_default_renderers()
        self.session = session if session is not None else ChatSession()
        self.builder = A2UIMessageBuilder(catalog_id=catalog_id or OPENBENCH_CATALOG_ID)
        self._render_items_fn = render_items_fn
        self._clear_render_items_fn = clear_render_items_fn
        self.session_store = session_store

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
        self._persist_session()

        # 3. Clear per-request render items queue (stale items from previous
        #    turns would otherwise bleed into this response)
        self._clear_render_items()

        try:
            # 4. Execute agent
            agent_result = self._execute_agent(content, config, attachments=attachments)

            # 5. Extract agent output + render items from visualization tools
            agent_output = self._extract_output(agent_result)
            metadata = self._extract_metadata(agent_result)
            extra_items = self._render_items_fn() if self._render_items_fn else None

            # 6. Render content to A2UI components.
            # If the agent returned a failed ExecutionResult, surface the
            # error as an ObCallout instead of silently rendering an empty
            # message.
            failed, err_msg = self._result_failed(agent_result)
            if failed:
                components = self._build_error_components(err_msg)
                data_model = None
                if extra_items:
                    extra_components, data_model = self._render_content(None, extra_items)
                    components.extend(extra_components)
            else:
                components, data_model = self._render_content(agent_output, extra_items)

            # 7. Ensure root component
            components = self._ensure_root(components)

            # 8. Build A2UI JSONL messages
            surface_id = f"s-{uuid.uuid4().hex[:8]}"
            messages = self.builder.build_surface(surface_id, components, data_model=data_model)

            # 9. Build text content for session history
            text_content = self._extract_text_content(agent_output)

            # 10. Add assistant message to session
            self.session.add_assistant_message(
                content=text_content,
                surfaces=[{"surfaceId": surface_id}],
                metadata=metadata,
            )
            self._persist_session()

            return {
                "messages": messages,
                "session": self.session,
                "metadata": metadata,
            }
        except Exception as exc:
            # Agent blew up (network, Gemini 400, tool exception escaped,
            # process signal). Write a placeholder assistant message so the
            # session doesn't end on a dangling user turn — UI can key off
            # ``metadata["aborted"]`` to surface a retry button.
            self._write_aborted_placeholder(None, exc)
            raise

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
            yield json.dumps(StepStartMessage(sid, "Processing input", message_id).to_dict())
            content, attachments = self._parse_input(input)
            self.session.add_user_message(content, attachments=attachments)
            self._persist_session()
            # Clear per-request render items queue before executing the agent.
            self._clear_render_items()
            yield json.dumps(StepCompleteMessage(sid, message_id).to_dict())

            # ── Step 2: Thinking ──
            sid = _step_id()
            yield json.dumps(StepStartMessage(sid, "Thinking", message_id).to_dict())
            agent_result = self._execute_agent(content, config, attachments=attachments)
            agent_output = self._extract_output(agent_result)
            metadata = self._extract_metadata(agent_result)
            extra_items = self._render_items_fn() if self._render_items_fn else None
            yield json.dumps(StepCompleteMessage(sid, message_id).to_dict())

            # ── Step 3: Rendering response ──
            sid = _step_id()
            yield json.dumps(StepStartMessage(sid, "Rendering response", message_id).to_dict())
            failed, err_msg = self._result_failed(agent_result)
            if failed:
                components = self._build_error_components(err_msg)
                data_model = None
                if extra_items:
                    extra_components, data_model = self._render_content(None, extra_items)
                    components.extend(extra_components)
            else:
                components, data_model = self._render_content(agent_output, extra_items)
            components = self._ensure_root(components)
            surface_id = f"s-{uuid.uuid4().hex[:8]}"
            messages = self.builder.build_surface(surface_id, components, data_model=data_model)

            # Yield each A2UI message individually
            for msg in messages:
                yield json.dumps(msg)

            yield json.dumps(StepCompleteMessage(sid, message_id).to_dict())

            # Build text content for session history
            text_content = self._extract_text_content(agent_output)
            self.session.add_assistant_message(
                content=text_content,
                surfaces=[{"surfaceId": surface_id}],
                metadata=metadata,
            )
            self._persist_session()

            # Stream end (include content as fallback for frontend)
            end_metadata = dict(metadata) if metadata else {}
            end_metadata["content"] = text_content
            end = StreamMessage(
                type=StreamMessageType.STREAM_END,
                message_id=message_id,
                metadata=end_metadata,
            )
            yield json.dumps(end.to_dict())

        except Exception as e:
            logger.error(f"Stream error: {e}")
            # Drop the aborted-turn placeholder into the session before
            # emitting the error, so a reload after this crash shows the
            # user their "please retry" hint rather than a dangling user
            # message. Swallows its own errors — never mask the original.
            self._write_aborted_placeholder(None, e)
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
            StreamMessage(type=StreamMessageType.STREAM_START, message_id=message_id).to_dict()
        )

        try:
            # ── Step 1: Processing input ──
            sid = _step_id()
            yield json.dumps(StepStartMessage(sid, "Processing input", message_id).to_dict())
            content, attachments = self._parse_input(input)
            self.session.add_user_message(content, attachments=attachments)
            self._persist_session()
            # Clear per-request render items queue before executing the agent.
            self._clear_render_items()
            yield json.dumps(StepCompleteMessage(sid, message_id).to_dict())

            # ── Step 2: Thinking (run in thread pool) ──
            sid = _step_id()
            yield json.dumps(StepStartMessage(sid, "Thinking", message_id).to_dict())
            agent_result = await asyncio.to_thread(
                self._execute_agent, content, config, attachments
            )
            agent_output = self._extract_output(agent_result)
            metadata = self._extract_metadata(agent_result)
            extra_items = self._render_items_fn() if self._render_items_fn else None
            yield json.dumps(StepCompleteMessage(sid, message_id).to_dict())

            # ── Step 3: Rendering response ──
            sid = _step_id()
            yield json.dumps(StepStartMessage(sid, "Rendering response", message_id).to_dict())
            failed, err_msg = self._result_failed(agent_result)
            if failed:
                components = self._build_error_components(err_msg)
                data_model = None
                if extra_items:
                    extra_components, data_model = self._render_content(None, extra_items)
                    components.extend(extra_components)
            else:
                components, data_model = self._render_content(agent_output, extra_items)
            components = self._ensure_root(components)
            surface_id = f"s-{uuid.uuid4().hex[:8]}"
            messages = self.builder.build_surface(surface_id, components, data_model=data_model)

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
            self._persist_session()

            # Stream end (include content as fallback for frontend)
            end_metadata = dict(metadata) if metadata else {}
            end_metadata["content"] = text_content
            yield json.dumps(
                StreamMessage(
                    type=StreamMessageType.STREAM_END,
                    message_id=message_id,
                    metadata=end_metadata,
                ).to_dict()
            )

        except Exception as e:
            logger.error(f"Stream error: {e}")
            self._write_aborted_placeholder(None, e)
            yield json.dumps(
                StreamMessage(
                    type=StreamMessageType.ERROR,
                    message_id=message_id,
                    metadata={"error": str(e)},
                ).to_dict()
            )
