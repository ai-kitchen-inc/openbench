"""AG-UI handler with per-session persistent memory for General Chat."""

from __future__ import annotations

import copy
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openbench.chat.session import Attachment
from openbench.chat.transport import AGUIHandler
from openbench.core.abstractions import LLMProvider, LLMResponse
from openbench.intelligence.base import AgentMemory, BaseAgent, Message, MessageRole
from openbench.intelligence.memory import PersistentMemory, SQLiteMemoryStore

if TYPE_CHECKING:
    from general_chat.sources import SourceRecord


_SOURCE_CONTEXT_ID = "general-chat-source-context"
_REDACTED_ATTACHMENT_CONTEXT = (
    "Context data: [previous General Chat source attachment content redacted]"
)


def _debug_prompt_dir() -> Path | None:
    """Return the prompt-debug output directory, if enabled."""
    configured = os.getenv("GENERAL_CHAT_DEBUG_PROMPT_DIR")
    enabled = os.getenv("GENERAL_CHAT_DEBUG_PROMPT", "").strip().lower()
    if not configured and enabled not in {"1", "true", "yes", "on"}:
        return None
    return Path(configured or "prompt-debug").resolve()


def _safe_session_id(session_id: str | None) -> str:
    if not session_id:
        return "unknown-session"
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in session_id)


def _dump_prompt(
    prompt: str | list[dict[str, Any]],
    *,
    model: str,
    params: dict[str, Any],
    session_id: str | None,
    stream: bool,
) -> None:
    """Write the exact messages passed to the LLM provider for debugging."""
    out_dir = _debug_prompt_dir()
    if out_dir is None:
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = out_dir / f"{stamp}-{_safe_session_id(session_id)}.json"
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "model": model,
        "stream": stream,
        "params": params,
        "prompt": prompt,
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"  [general-chat] wrote LLM prompt debug dump: {path}")


class _DebugLLMProvider(LLMProvider):
    """Thin provider wrapper that dumps prompts before delegating."""

    def __init__(self, inner: LLMProvider, session_id: str | None):
        self._inner = inner
        self._session_id = session_id

    @property
    def provider_name(self) -> str:
        return self._inner.provider_name

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def generate(
        self, prompt: str | list[dict[str, Any]], model: str = "", **params
    ) -> LLMResponse:
        _dump_prompt(
            prompt,
            model=model,
            params=params,
            session_id=self._session_id,
            stream=False,
        )
        return self._inner.generate(prompt, model, **params)

    def generate_stream(self, prompt: str | list[dict[str, Any]], model: str = "", **params):
        _dump_prompt(
            prompt,
            model=model,
            params=params,
            session_id=self._session_id,
            stream=True,
        )
        yield from self._inner.generate_stream(prompt, model, **params)


def _source_context_attachments(doc_context: str) -> list[Attachment]:
    """Represent persisted source context as filename-preserving attachments."""
    headings = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", doc_context))
    if not headings:
        return [
            Attachment(
                id=_SOURCE_CONTEXT_ID,
                type="file",
                name="uploaded_sources.md",
                url="",
                mime_type="text/markdown",
                extracted_text=(
                    "Optional context extracted from the user's uploaded source files.\n\n"
                    f"{doc_context}"
                ),
            )
        ]

    attachments: list[Attachment] = []
    for idx, heading in enumerate(headings):
        name = heading.group(1).strip() or f"source-{idx + 1}.md"
        start = heading.end()
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(doc_context)
        text = doc_context[start:end].strip()
        attachments.append(
            Attachment(
                id=f"{_SOURCE_CONTEXT_ID}-{idx}",
                type="file",
                name=name,
                url="",
                mime_type="text/markdown",
                extracted_text=(
                    f"Source filename: {name}\n\n"
                    "Optional context extracted from this uploaded source file.\n\n"
                    f"## {name}\n\n{text}"
                ),
            )
        )
    return attachments


def _image_attachment_mcp_path(attachment: Attachment) -> str | None:
    """Return the container path image MCP tools can read for a chat upload."""
    if attachment.type != "image" and not attachment.mime_type.startswith("image/"):
        return None
    if not attachment.url.startswith("/uploads/"):
        return None
    from general_chat.sources import image_search_metadata
    from openbench.chat.files import StoredFile

    stored = StoredFile(
        id=attachment.id,
        name=attachment.name,
        path=attachment.path or "",
        mime_type=attachment.mime_type,
        size_bytes=attachment.size_bytes or 0,
        stored_at="",
    )
    return image_search_metadata(stored)["samSegmentationPath"]


def _enrich_draft_attachments(attachments: list[Attachment] | None) -> list[Attachment]:
    """Preserve draft attachments and add MCP-readable context for images."""
    if not attachments:
        return []

    from general_chat.sources import image_search_metadata, image_search_text
    from openbench.chat.files import StoredFile

    enriched: list[Attachment] = []
    for attachment in attachments:
        image_path = _image_attachment_mcp_path(attachment)
        if image_path is None:
            enriched.append(attachment)
            continue

        stored = StoredFile(
            id=attachment.id,
            name=attachment.name,
            path=attachment.path or "",
            mime_type=attachment.mime_type,
            size_bytes=attachment.size_bytes or 0,
            stored_at="",
        )
        metadata = image_search_metadata(stored)
        existing_text = (attachment.extracted_text or "").strip()
        if (
            existing_text
            and metadata["samSegmentationPath"] in existing_text
            and "sam_segmentation.count_objects_with_sam3" in existing_text
        ):
            extracted_text = existing_text
        else:
            extracted_text = image_search_text(stored, parsed_text=existing_text)

        enriched.append(
            Attachment(
                id=attachment.id,
                type="image",
                name=attachment.name,
                url=attachment.url,
                mime_type=attachment.mime_type,
                size_bytes=attachment.size_bytes,
                extracted_text=extracted_text,
                path=metadata["samSegmentationPath"],
            )
        )
    return enriched


def _source_record_attachments(source_records: list[SourceRecord]) -> list[Attachment]:
    """Represent persisted ready sources as filename-preserving attachments."""
    attachments: list[Attachment] = []
    for record in source_records:
        if record.status != "ready" or not record.text.strip():
            continue
        metadata = record.metadata or {}
        image_search_path = metadata.get("imageSearchPath")
        sam_segmentation_path = metadata.get("samSegmentationPath")
        extra_lines = ""
        image_tool_path = image_search_path if isinstance(image_search_path, str) else None
        sam_tool_path = sam_segmentation_path if isinstance(sam_segmentation_path, str) else None
        if record.kind == "image" and image_tool_path:
            extra_lines = f"Image search path: {image_tool_path}\n\n"
        if record.kind == "image" and sam_tool_path:
            extra_lines += f"SAM 3 concept counting path: {sam_tool_path}\n\n"
        attachments.append(
            Attachment(
                id=record.id,
                type="image" if record.kind == "image" else "file",
                name=record.name,
                url=record.url or "",
                mime_type=record.mime_type or "text/plain",
                size_bytes=record.size_bytes,
                path=sam_tool_path or image_tool_path,
                extracted_text=(
                    f"Source name: {record.name}\n"
                    f"Source type: {record.kind}\n"
                    f"Source URL: {record.url or '(none)'}\n\n"
                    f"{extra_lines}"
                    "Optional context extracted from this user-added source.\n\n"
                    f"## {record.name}\n\n{record.text}"
                ),
            )
        )
    return attachments


def _redact_stale_source_context(messages: list[Message]) -> tuple[list[Message], bool]:
    changed = False
    redacted: list[Message] = []
    for message in messages:
        if message.role != MessageRole.USER or "Context data:" not in message.content:
            redacted.append(message)
            continue
        if '"attachments"' not in message.content and "user-added source" not in message.content:
            redacted.append(message)
            continue
        goal = message.content.split("\n\nContext data:", 1)[0].strip()
        redacted.append(
            Message(
                role=message.role,
                content=f"{goal}\n\n{_REDACTED_ATTACHMENT_CONTEXT}",
                name=message.name,
                tool_call_id=message.tool_call_id,
                tool_calls=message.tool_calls,
                raw_content=message.raw_content,
            )
        )
        changed = True
    return redacted, changed


def sanitize_messages(messages: list[Message]) -> list[Message]:
    """Remove invalid conversation-turn sequences that break Gemini's API."""
    if not messages:
        return messages

    def _collapse_tail(buf: list[Message], incoming: Message) -> None:
        if not buf:
            buf.append(incoming)
            return
        last = buf[-1]
        if incoming.role == MessageRole.USER and last.role == MessageRole.USER:
            buf[-1] = incoming
            return
        if (
            incoming.role == MessageRole.ASSISTANT
            and last.role == MessageRole.ASSISTANT
            and not incoming.tool_calls
            and not last.tool_calls
        ):
            buf[-1] = incoming
            return
        buf.append(incoming)

    out: list[Message] = []
    i = 0
    n = len(messages)
    while i < n:
        m = messages[i]

        if m.role == MessageRole.SYSTEM:
            _collapse_tail(out, m)
            i += 1
            continue

        if m.role == MessageRole.ASSISTANT and m.tool_calls:
            num_expected = len(m.tool_calls)
            responses: list[Message] = []
            j = i + 1
            while j < n and messages[j].role == MessageRole.TOOL and len(responses) < num_expected:
                responses.append(messages[j])
                j += 1
            if len(responses) == num_expected:
                out.append(m)
                out.extend(responses)
                i = j
            else:
                i = j
            continue

        if m.role == MessageRole.TOOL:
            i += 1
            continue

        _collapse_tail(out, m)
        i += 1

    return out


class GeneralChatHandler(AGUIHandler):
    """AG-UI handler with SQLite-backed persistent memory per session."""

    def __init__(
        self,
        engine,
        db_path: str = "general_chat_memory.db",
        doc_context: str | None = None,
        source_records: list[SourceRecord] | None = None,
    ):
        super().__init__(engine)
        self._memory_store = SQLiteMemoryStore(db_path=db_path)
        self._local = threading.local()
        self._doc_context = doc_context
        self._source_records = source_records or []

    def _extract_content(self, body):
        content, draft_attachments = super()._extract_content(body)
        attachments = _enrich_draft_attachments(draft_attachments)
        if self._source_records:
            source_attachments = _source_record_attachments(self._source_records)
            attachments = [*attachments, *source_attachments]
        if self._doc_context:
            source_attachments = _source_context_attachments(self._doc_context)
            attachments = [*attachments, *source_attachments]
        return content, attachments or None

    def _get_or_create_session(self, session_id):
        self._local.session_id = session_id
        return super()._get_or_create_session(session_id)

    def _on_session_resolved(self, session_id):
        self._local.session_id = session_id

    def _create_request_agent(self):
        agent = self.engine.agent
        if not isinstance(agent, BaseAgent):
            return agent

        agent_copy = copy.copy(agent)
        session_id = getattr(self._local, "session_id", None)

        if session_id and self._memory_store:
            agent_copy.memory = PersistentMemory(
                store=self._memory_store,
                session_id=session_id,
            )
            original = list(agent_copy.memory.messages)
            sanitized = sanitize_messages(original)
            redacted, redacted_changed = _redact_stale_source_context(sanitized)
            if len(sanitized) != len(original) or redacted_changed:
                dropped = len(original) - len(sanitized)
                print(
                    f"  [general-chat] sanitized session {session_id}: "
                    f"dropped {dropped} orphaned message(s), "
                    f"redacted_stale_sources={redacted_changed}"
                )
                agent_copy.memory.messages = redacted
                self._memory_store.delete_session(session_id)
                if redacted:
                    self._memory_store.save(session_id, redacted)
            else:
                agent_copy.memory.messages = sanitized
        else:
            agent_copy.memory = AgentMemory()

        if (
            not agent_copy.memory.messages
            or agent_copy.memory.messages[0].role != MessageRole.SYSTEM
        ):
            agent_copy.memory.add_system(agent._system_prompt)

        agent_copy._llm = agent._llm
        if _debug_prompt_dir() is not None:
            agent_copy._llm = _DebugLLMProvider(
                agent_copy._llm or agent_copy._get_llm(),
                session_id=session_id,
            )
        agent_copy.tools = agent.tools
        return agent_copy
