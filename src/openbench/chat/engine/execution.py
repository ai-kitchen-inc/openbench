"""Agent execution + input/result adapters for ChatEngine."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from openbench.chat.session import Attachment
from openbench.core.abstractions import (
    Agent,
    ExecutionContext,
    ExecutionResult,
    FrameworkAdapter,
    MediaContent,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from openbench.chat.session import ChatSession
    from openbench.core.chainable import RunnableConfig

logger = logging.getLogger(__name__)


class _AgentExecutionMixin:
    """Mixin for ChatEngine; not instantiated directly."""

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
        on_chunk: Callable[[str], None] | None = None,
        session: ChatSession | None = None,
        agent: Agent | FrameworkAdapter | None = None,
        on_progress: Callable | None = None,
    ) -> Any:
        """Execute the agent with the given content.

        Args:
            content: User message text.
            config: Optional runnable config.
            attachments: Optional file attachments.
            on_chunk: Optional callback for progressive token streaming.
                Called with each text delta as it arrives from the LLM.
            session: Optional per-request session override (default: self.session).
            agent: Optional per-request agent override (default: self.agent).
            on_progress: Optional callback for agent progress events.
                Called with ProgressEvent instances during agent execution.
        """
        active_session = session if session is not None else self.session
        active_agent = agent if agent is not None else self.agent
        if isinstance(active_agent, Agent):
            data: dict[str, Any] = {}
            # Only include session data if agent doesn't have persistent memory.
            # Agents with PersistentMemory already have full conversation history
            # in self.memory — including session.to_dict() would be redundant,
            # noisy, and can confuse the LLM (especially for generate_file).
            _has_persistent_memory = hasattr(active_agent, "memory") and hasattr(
                active_agent.memory, "store"
            )
            if not _has_persistent_memory:
                data["session"] = active_session.to_dict()
            if attachments:
                att_data = []
                for a in attachments:
                    if not a.extracted_text:
                        continue
                    entry: dict[str, Any] = {
                        "name": a.name,
                        "type": a.type,
                        "mime_type": a.mime_type,
                        "content": a.extracted_text,
                    }
                    # Include disk path if available so tools like
                    # extract_file_context can read the file directly.
                    path = getattr(a, "path", None)
                    if path:
                        entry["path"] = path
                    att_data.append(entry)
                if att_data:
                    data["attachments"] = att_data
                # Provider-neutral media references for native multimodal
                # understanding. Independent of extracted_text: audio/video
                # may have no text yet, but the model can still see/hear them.
                media_items: list[MediaContent] = []
                for a in attachments:
                    if a.type not in ("image", "audio", "video"):
                        continue
                    path = getattr(a, "path", None)
                    if not path:
                        continue
                    media_items.append(
                        MediaContent(
                            type=a.type,
                            mime_type=a.mime_type,
                            path=path,
                            metadata={"name": a.name},
                        )
                    )
                if media_items:
                    data["_media"] = media_items
            context = ExecutionContext(
                goal=content,
                data=data,
            )
            # Pass on_chunk and on_progress if agent supports them.
            # Tiered fallback: try all kwargs → on_chunk only → bare execute.
            if on_chunk or on_progress:
                kwargs: dict[str, Any] = {}
                if on_chunk:
                    kwargs["on_chunk"] = on_chunk
                if on_progress:
                    kwargs["on_progress"] = on_progress
                try:
                    return active_agent.execute(context, **kwargs)
                except TypeError:
                    # Agent might not support on_progress; retry with on_chunk only
                    if on_chunk:
                        try:
                            return active_agent.execute(context, on_chunk=on_chunk)  # type: ignore[call-arg]
                        except TypeError:
                            pass
                    return active_agent.execute(context)
            return active_agent.execute(context)
        elif isinstance(active_agent, FrameworkAdapter):
            return active_agent.invoke(content, config)
        else:
            return active_agent.invoke(content, config)

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
