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
from openbench.core.abstractions import (
    Agent,
    ExecutionContext,
    ExecutionResult,
    LLMProvider,
    LLMResponse,
)
from openbench.intelligence.base import AgentMemory, BaseAgent, Message, MessageRole
from openbench.intelligence.memory import PersistentMemory, SQLiteMemoryStore

if TYPE_CHECKING:
    from general_chat.sources import SourceRecord


_SOURCE_CONTEXT_ID = "general-chat-source-context"
_SOURCE_SYSTEM_MARKER = "[General Chat Source Handling]"
_SOURCE_SYSTEM_INSTRUCTIONS = f"""

{_SOURCE_SYSTEM_MARKER}
The current request may include uploaded source files in Context data under
`attachments`. Treat only these current-turn attachments as authoritative
user-provided sources. Do not use document text from earlier conversation turns,
cached client attachments, memory, or removed sources. When the user asks to
summarize, quote, extract, compare, or answer about a named file, use the
matching current attachment content directly. Do not claim you lack access to
the file when an attachment with that filename is present. If multiple source
files are present, use their `name` fields to identify which source supports
each part of the answer.

Answer document/source questions only from the current attachments. If no
current source is provided, ask the user to add a document/source first. If the
question is unrelated to the current source, refuse briefly. If the answer is
not found in the current source, say: "The answer is not in the provided
document."

For uploaded image sources, the attachment content may include an
`image_search MCP path`. When the user asks to find similar images, compare
visual similarity, or search from the uploaded image, call
`image_search.search_similar_images` with that path as `image_path`. Use the
requested top_k value when the user provides one; otherwise use `top_k=10`. Do
not run long indexing or rebuild tools during chat. Partial indexes are usable
for search. If the search tool reports an empty, uninitialized, or timed-out
index, tell the user to build the image search index outside chat, then retry.
Tool results with `preview_url` are rendered into the chat surface automatically.
""".strip()

_NO_SOURCE_REFUSAL = "Please add a document/source first."
_UNRELATED_REFUSAL = "I can only answer questions related to the current document/source."
_NOT_FOUND_INSTRUCTION = (
    'If the answer is not found in the current source, say exactly: '
    '"The answer is not in the provided document."'
)
_REDACTED_ATTACHMENT_CONTEXT = (
    "Context data: [previous General Chat source attachment content redacted; "
    "use only current-turn attachments]"
)
_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "answer",
    "based",
    "before",
    "brief",
    "current",
    "document",
    "documents",
    "does",
    "file",
    "from",
    "give",
    "have",
    "into",
    "only",
    "please",
    "provided",
    "question",
    "show",
    "source",
    "sources",
    "summarize",
    "summary",
    "tell",
    "that",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
}
_DOCUMENT_ACTION_TERMS = {
    "summarize",
    "summary",
    "compare",
    "extract",
    "quote",
    "list",
    "find",
    "image",
    "images",
    "key",
    "main",
    "claims",
    "dates",
    "milestones",
    "briefing",
    "action",
    "items",
    "similar",
    "similarity",
    "visual",
}


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

    def generate(self, prompt: str | list[dict[str, Any]], model: str = "", **params) -> LLMResponse:
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
                    "The following text is extracted from the user's uploaded source files. "
                    "Use it as source material for this turn.\n\n"
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
                    "The following text is extracted from this uploaded source file. "
                    "Use it as source material for this turn.\n\n"
                    f"## {name}\n\n{text}"
                ),
            )
        )
    return attachments


def _source_record_attachments(source_records: list[SourceRecord]) -> list[Attachment]:
    """Represent persisted ready sources as filename-preserving attachments."""
    attachments: list[Attachment] = []
    for record in source_records:
        if record.status != "ready" or not record.text.strip():
            continue
        metadata = record.metadata or {}
        image_search_path = metadata.get("imageSearchPath")
        extra_lines = ""
        if record.kind == "image" and isinstance(image_search_path, str):
            extra_lines = (
                f"Image search path: {image_search_path}\n"
                "Use this exact value as image_path when calling "
                "image_search.search_similar_images.\n\n"
            )
        attachments.append(
            Attachment(
                id=record.id,
                type="image" if record.kind == "image" else "file",
                name=record.name,
                url=record.url or "",
                mime_type=record.mime_type or "text/plain",
                size_bytes=record.size_bytes,
                path=image_search_path if isinstance(image_search_path, str) else None,
                extracted_text=(
                    f"Source name: {record.name}\n"
                    f"Source type: {record.kind}\n"
                    f"Source URL: {record.url or '(none)'}\n\n"
                    f"{extra_lines}"
                    "The following text is extracted from this user-added source. "
                    "Use it as source material for this turn.\n\n"
                    f"## {record.name}\n\n{record.text}"
                ),
            )
        )
    return attachments


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{3,}", text.lower())
        if token not in _STOPWORDS
    }


def _attachment_corpus(attachments: list[Attachment]) -> str:
    return "\n\n".join(
        f"{attachment.name}\n{attachment.extracted_text or ''}" for attachment in attachments
    )


def _is_related_to_sources(content: str, attachments: list[Attachment]) -> bool:
    question_tokens = _tokens(content)
    if not question_tokens:
        return True
    if question_tokens & _DOCUMENT_ACTION_TERMS:
        return True
    source_tokens = _tokens(_attachment_corpus(attachments))
    return bool(question_tokens & source_tokens)


def _with_grounding_instruction(content: str) -> str:
    if _NOT_FOUND_INSTRUCTION in content:
        return content
    return f"{content}\n\n{_NOT_FOUND_INSTRUCTION}"


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


class _SourceGroundedAgent(Agent):
    """Request wrapper that enforces current-source-only document grounding."""

    def __init__(self, inner: Agent):
        self.inner = inner

    @property
    def agent_type(self) -> str:
        return self.inner.agent_type

    def execute(
        self,
        context: ExecutionContext,
        on_chunk=None,
        on_progress=None,
    ) -> ExecutionResult:
        attachments = [
            item
            for item in (context.data or {}).get("attachments", [])
            if isinstance(item, dict) and str(item.get("content") or "").strip()
        ]
        if not attachments:
            return self._refuse(_NO_SOURCE_REFUSAL, on_chunk=on_chunk)

        source_attachments = [
            Attachment(
                id=str(item.get("id") or item.get("name") or "source"),
                type=str(item.get("type") or "file"),
                name=str(item.get("name") or "source"),
                url="",
                mime_type=str(item.get("mime_type") or "text/plain"),
                extracted_text=str(item.get("content") or ""),
            )
            for item in attachments
        ]
        if not _is_related_to_sources(context.goal, source_attachments):
            return self._refuse(_UNRELATED_REFUSAL, on_chunk=on_chunk)

        grounded_context = ExecutionContext(
            goal=_with_grounding_instruction(context.goal),
            data=context.data,
            tools=context.tools,
            memory=context.memory,
            constraints=context.constraints,
        )
        try:
            return self.inner.execute(
                grounded_context,
                on_chunk=on_chunk,
                on_progress=on_progress,
            )
        except TypeError:
            if on_chunk:
                try:
                    return self.inner.execute(grounded_context, on_chunk=on_chunk)  # type: ignore[call-arg]
                except TypeError:
                    pass
            return self.inner.execute(grounded_context)

    def estimate_cost(self, context: ExecutionContext) -> float:
        return self.inner.estimate_cost(context)

    @staticmethod
    def _refuse(message: str, *, on_chunk=None) -> ExecutionResult:
        if on_chunk:
            on_chunk(message)
        return ExecutionResult(
            output=message,
            status="success",
            metadata={"grounding_refusal": True},
        )


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
        messages = body.get("messages")
        if messages and isinstance(messages, list):
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    break
            else:
                content = ""
        else:
            content = body.get("content", "")
        attachments: list[Attachment] = []
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

        system_prompt = agent._system_prompt
        if _SOURCE_SYSTEM_MARKER not in system_prompt:
            system_prompt = f"{system_prompt}\n\n{_SOURCE_SYSTEM_INSTRUCTIONS}"

        if not agent_copy.memory.messages or agent_copy.memory.messages[0].role != MessageRole.SYSTEM:
            agent_copy.memory.add_system(system_prompt)
        elif _SOURCE_SYSTEM_MARKER not in agent_copy.memory.messages[0].content:
            agent_copy.memory.messages[0].content = (
                f"{agent_copy.memory.messages[0].content}\n\n{_SOURCE_SYSTEM_INSTRUCTIONS}"
            )

        agent_copy._llm = agent._llm
        if _debug_prompt_dir() is not None:
            agent_copy._llm = _DebugLLMProvider(
                agent_copy._llm or agent_copy._get_llm(),
                session_id=session_id,
            )
        agent_copy.tools = agent.tools
        return _SourceGroundedAgent(agent_copy)
