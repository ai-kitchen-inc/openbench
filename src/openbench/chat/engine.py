"""
ChatEngine -- main chat orchestrator.

Processes user input through an agent, auto-detects content types,
runs content renderers, and builds A2UI v0.10 JSONL output.

Inherits from Chainable for composability with OpenBench layers.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

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
from openbench.chat.session import Attachment, ChatSession
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
        render_items_fn: Callable[[], list[dict]] | None = None,
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
        """
        self.agent = agent
        self.renderers = renderers if renderers is not None else _get_default_renderers()
        self.session = session if session is not None else ChatSession()
        self.builder = A2UIMessageBuilder(catalog_id=catalog_id or OPENBENCH_CATALOG_ID)
        self._render_items_fn = render_items_fn

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
        agent_result = self._execute_agent(content, config, attachments=attachments)

        # 4. Extract agent output + render items from visualization tools
        agent_output = self._extract_output(agent_result)
        metadata = self._extract_metadata(agent_result)
        extra_items = self._render_items_fn() if self._render_items_fn else None

        # 5. Render content to A2UI components
        components = self._render_content(agent_output, extra_items)

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
            yield json.dumps(StepStartMessage(sid, "Processing input", message_id).to_dict())
            content, attachments = self._parse_input(input)
            self.session.add_user_message(content, attachments=attachments)
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
            components = self._render_content(agent_output, extra_items)
            components = self._ensure_root(components)
            surface_id = f"s-{uuid.uuid4().hex[:8]}"
            messages = self.builder.build_surface(surface_id, components)

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
            components = self._render_content(agent_output, extra_items)
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
            yield json.dumps(
                StreamMessage(
                    type=StreamMessageType.ERROR,
                    message_id=message_id,
                    metadata={"error": str(e)},
                ).to_dict()
            )

    def _parse_input(self, input: Any) -> tuple[str, list[Attachment] | None]:
        """Parse input into content string and optional attachments."""
        if isinstance(input, str):
            return input, None

        if isinstance(input, dict):
            # Direct chat input
            if "content" in input:
                raw = input.get("attachments")
                attachments = self._coerce_attachments(raw) if raw else None
                return input["content"], attachments
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

    @staticmethod
    def _coerce_attachments(raw: list) -> list[Attachment]:
        """Convert raw attachment dicts to Attachment objects."""
        result: list[Attachment] = []
        for item in raw:
            if isinstance(item, Attachment):
                result.append(item)
            elif isinstance(item, dict):
                result.append(Attachment.from_dict(item))
            else:
                logger.warning(f"Skipping unknown attachment type: {type(item)}")
        return result

    def _execute_agent(
        self,
        content: str,
        config: RunnableConfig | None,
        attachments: list[Attachment] | None = None,
    ) -> Any:
        """Execute the agent with the given content."""
        if isinstance(self.agent, Agent):
            data: dict[str, Any] = {"session": self.session.to_dict()}
            if attachments:
                att_data = [
                    {
                        "name": a.name,
                        "type": a.type,
                        "mime_type": a.mime_type,
                        "content": a.extracted_text,
                    }
                    for a in attachments
                    if a.extracted_text
                ]
                if att_data:
                    data["attachments"] = att_data
            context = ExecutionContext(
                goal=content,
                data=data,
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

    def _render_content(
        self, content: Any, extra_items: list[dict] | None = None
    ) -> list[A2UIComponent]:
        """Auto-detect content type and render to A2UI components.

        Args:
            content: Main agent output (text, chart dict, etc.).
            extra_items: Additional structured items from render queue
                (visualization tools). Each item is rendered through the
                renderer pipeline independently and combined with main content.
        """
        # Render main content
        main_components: list[A2UIComponent] = []
        for renderer in self.renderers:
            if renderer.detect(content):
                main_components = renderer.render(content, surface_id="")
                break
        if not main_components:
            main_components = [
                A2UIComponent(
                    id="txt-fallback",
                    component="Text",
                    properties={"text": str(content), "variant": "body"},
                )
            ]

        # Render extra items from render queue
        if not extra_items:
            return main_components

        # Deduplicate: agents may call visualization tools multiple times in
        # reasoning loops. Keep only the last item per content type to avoid
        # rendering the same form/chart/file card multiple times.
        deduped = self._deduplicate_render_items(extra_items)

        extra_components: list[A2UIComponent] = []
        for item in deduped:
            rendered = False
            for renderer in self.renderers:
                if renderer.detect(item):
                    extra_components.extend(renderer.render(item, surface_id=""))
                    rendered = True
                    break
            if not rendered:
                logger.warning(f"No renderer matched render item: {list(item.keys())}")

        if not extra_components:
            return main_components

        return main_components + extra_components

    def _ensure_root(self, components: list[A2UIComponent]) -> list[A2UIComponent]:
        """Ensure there's a component with id='root'.

        Identifies top-level components (not referenced as children by others)
        and wraps them in a root Column, or renames a single top-level to 'root'.
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

        # Find IDs referenced as children by other components
        referenced_ids: set[str] = set()
        for c in components:
            children = c.properties.get("children")
            if isinstance(children, list):
                referenced_ids.update(children)

        # Top-level = components not referenced as children of anything
        top_level_ids = [c.id for c in components if c.id not in referenced_ids]

        if len(top_level_ids) == 1:
            # Single top-level: rename it to root
            target_id = top_level_ids[0]
            result: list[A2UIComponent] = []
            for c in components:
                if c.id == target_id:
                    result.append(
                        A2UIComponent(
                            id="root",
                            component=c.component,
                            properties=c.properties,
                        )
                    )
                else:
                    result.append(c)
            return result

        # Multiple top-level components: wrap in Column
        root = A2UIComponent(
            id="root",
            component="Column",
            properties={"children": top_level_ids},
        )
        return [root, *components]

    @staticmethod
    def _deduplicate_render_items(items: list[dict]) -> list[dict]:
        """Deduplicate render items from visualization tools.

        Agents may call the same tool multiple times during reasoning
        iterations (e.g. refining a form). For forms, only keep the last one.
        For charts, keep multiple but deduplicate by title.
        For file cards, deduplicate by name.
        """
        forms: list[dict] = []
        charts: dict[str, dict] = {}  # keyed by title
        files: dict[str, dict] = {}  # keyed by name
        other: list[dict] = []

        for item in items:
            if isinstance(item, dict) and "fields" in item:
                forms.append(item)
            elif isinstance(item, dict) and "data" in item and "title" in item:
                charts[item["title"]] = item  # last one wins per title
            elif isinstance(item, dict) and "url" in item and "name" in item:
                files[item["name"]] = item  # last one wins per name
            else:
                other.append(item)

        result: list[dict] = []
        # Only keep the last form (one form per response)
        if forms:
            result.append(forms[-1])
        result.extend(charts.values())
        result.extend(files.values())
        result.extend(other)
        return result

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
