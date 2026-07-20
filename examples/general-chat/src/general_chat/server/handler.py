"""AG-UI handler with per-session persistent memory for General Chat."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openbench.chat.session import Attachment, ChatSession
from openbench.chat.transport import AGUIHandler
from openbench.core.abstractions import ExecutionContext, LLMProvider, LLMResponse
from openbench.intelligence.base import AgentMemory, BaseAgent, Message, MessageRole
from openbench.intelligence.memory import PersistentMemory, SQLiteMemoryStore
from openbench.mcp.permissions import MCPPermissionContext

from general_chat.server.mcp_permissions import GeneralChatMCPPermissionCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable

    from general_chat.sources import SourceRecord


logger = logging.getLogger(__name__)

_SOURCE_CONTEXT_ID = "general-chat-source-context"
_DEFAULT_SOURCE_CONTEXT_LABEL = "Optional context extracted from this user-added source."
_REDACTED_ATTACHMENT_CONTEXT = (
    "Context data: [previous General Chat source attachment content redacted]"
)


_source_context_label_override: str | None = None


def set_source_context_label_override(value: str | None) -> None:
    """Set (or clear) the runtime source-label override.

    Used by the admin-managed persona: applying a persona template with
    a ``source_context_label`` reframes injected sources without
    touching the process environment.
    """
    global _source_context_label_override
    _source_context_label_override = (value or "").strip() or None


def _source_context_label() -> str:
    """Framing line prepended to every injected source's text.

    Overridable so wrapper deployments can reframe sources as mandatory
    grounding (e.g. controlled-source mode) instead of optional context.
    Runtime override (admin persona) wins over the env override.
    """
    if _source_context_label_override:
        return _source_context_label_override
    return os.getenv("GENERAL_CHAT_SOURCE_CONTEXT_LABEL", "").strip() or (
        _DEFAULT_SOURCE_CONTEXT_LABEL
    )


_IMAGE_MCP_FILE_PATH_RE = re.compile(r"/general-chat/uploads/file-[^/\"'\s]+/[^\r\n\"']+")
_VISION_ATTACHMENT_ID = "general-chat-vision-observation"
_VEHICLE_PLATE_TERMS = (
    "plat",
    "plate",
    "nomor kendaraan",
    "license plate",
    "number plate",
    "vehicle plate",
)
_DEFAULT_SESSION_TITLE = "New Chat"


def _fallback_session_title(content: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", content.strip())
    if not words:
        return _DEFAULT_SESSION_TITLE
    title_words = words[:5]
    return " ".join(word[:1].upper() + word[1:24].lower() for word in title_words)


def _clean_session_title(value: str, fallback: str) -> str:
    title = value.strip().strip("\"'` ")
    title = re.sub(r"^(title|chat title)\s*:\s*", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"[\r\n]+", " ", title)
    title = re.sub(r"\s+", " ", title)
    title = re.sub(r"[.!?;:]+$", "", title).strip()
    if not title:
        title = fallback
    words = title.split()
    if len(words) > 6:
        title = " ".join(words[:6])
    return title[:64].strip() or fallback


def _generate_session_title(agent: Any, content: str) -> str:
    fallback = _fallback_session_title(content)
    if not isinstance(agent, BaseAgent):
        return fallback
    prompt = (
        "Generate a concise English chat session title from the user's first message.\n"
        "Rules: 2 to 5 words, Title Case, no quotes, no punctuation, no explanations.\n\n"
        f"User message:\n{content[:1200]}"
    )
    try:
        response = agent._get_llm().generate(
            prompt=prompt,
            model=agent.model,
            temperature=0.1,
        )
    except Exception:
        logger.warning("Session title generation failed; using fallback title", exc_info=True)
        return fallback
    return _clean_session_title(getattr(response, "text", ""), fallback)


def _example_root() -> Path:
    return Path(__file__).resolve().parents[3]


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
                    f"{_source_context_label()}\n\n"
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
                    f"{_source_context_label()}\n\n"
                    f"## {name}\n\n{text}"
                ),
            )
        )
    return attachments


def _image_attachment_mcp_path(attachment: Attachment) -> str | None:
    """Return the container path image MCP tools can read for a chat upload."""
    if attachment.type != "image" and not attachment.mime_type.startswith("image/"):
        return None
    if attachment.path and _IMAGE_MCP_FILE_PATH_RE.fullmatch(attachment.path):
        return attachment.path
    existing_match = _IMAGE_MCP_FILE_PATH_RE.search(attachment.extracted_text or "")
    if existing_match:
        return existing_match.group(0)
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


def _local_upload_path_from_attachment(attachment: Attachment) -> str | None:
    """Resolve a local upload path from a browser-facing /uploads URL."""
    if not attachment.url.startswith("/uploads/"):
        return None
    parts = attachment.url.strip("/").split("/", 2)
    if len(parts) != 3 or parts[0] != "uploads":
        return None
    upload_root = Path(
        os.getenv("GENERAL_CHAT_UPLOAD_DIR", str(_example_root() / "uploads"))
    ).resolve()
    candidate = (upload_root / parts[1] / Path(parts[2]).name).resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError:
        return None
    return str(candidate) if candidate.is_file() else None


def _is_image_attachment(attachment: Attachment) -> bool:
    return attachment.type == "image" or attachment.mime_type.startswith("image/")


def _attachment_to_vision_item(attachment: Attachment) -> dict[str, Any] | None:
    if not _is_image_attachment(attachment):
        return None

    local_path = _local_upload_path_from_attachment(attachment)
    path = local_path or attachment.path
    if not path:
        return None
    if path.startswith("/general-chat/uploads/") and local_path is None:
        return None

    return {
        "id": attachment.id,
        "name": attachment.name,
        "type": "image",
        "mime_type": attachment.mime_type,
        "path": path,
        "url": attachment.url,
    }


def _is_vehicle_plate_request(content: str) -> bool:
    lowered = content.lower()
    return any(term in lowered for term in _VEHICLE_PLATE_TERMS)


def _build_visual_observation_attachment(
    *,
    content: str,
    image_items: list[dict[str, Any]],
    output: str,
    metadata: dict[str, Any],
) -> Attachment:
    names = ", ".join(str(item.get("name") or "image") for item in image_items)
    provider = metadata.get("provider") or "unknown"
    model = metadata.get("model") or "unknown"
    text = (
        "Visual observation from the configured OpenBench VLM.\n\n"
        f"User request: {content}\n"
        f"Images: {names}\n"
        f"VLM: {provider} / {model}\n\n"
        f"{output.strip()}"
    ).strip()
    return Attachment(
        id=_VISION_ATTACHMENT_ID,
        type="file",
        name="visual-observations.md",
        url="",
        mime_type="text/markdown",
        extracted_text=text,
    )


def _augment_with_visual_observations(
    *,
    agent: Any,
    content: str,
    attachments: list[Attachment],
) -> list[Attachment]:
    vision_agent = getattr(agent, "_vision_agent", None)
    if vision_agent is None:
        return attachments

    image_items = [
        item for item in (_attachment_to_vision_item(attachment) for attachment in attachments) if item
    ]
    if not image_items:
        return attachments

    model = str(
        getattr(vision_agent, "model", "")
        or getattr(agent, "_vlm_summary", {}).get("model")
        or "unknown"
    )
    for item in image_items:
        print(f"[vision] running source={item.get('name') or 'image'} model={model}")

    plate_request = _is_vehicle_plate_request(content)
    if plate_request:
        for item in image_items:
            print(
                "[vehicle-plate-reading] invoked "
                f"source={item.get('name') or 'image'} model={model}"
            )

    goal = (
        "Analyze the uploaded image(s) for the user's request. "
        f"User request: {content}"
    )
    if plate_request:
        goal = (
            "Use the vehicle-plate-reading skill to read any visible vehicle "
            f"license plate. User request: {content}"
        )

    result = vision_agent.execute(
        ExecutionContext(
            goal=goal,
            data={"attachments": image_items},
        )
    )
    if result.status != "completed" or not result.output:
        error = result.metadata.get("error") if result.metadata else None
        if not error:
            return attachments
        output = f"Visual analysis unavailable: {error}"
    else:
        output = str(result.output)
    print(f"[vision] result chars={len(output)}")

    return [
        *attachments,
        _build_visual_observation_attachment(
            content=content,
            image_items=image_items,
            output=output,
            metadata=result.metadata,
        ),
    ]


def _enrich_draft_attachments(attachments: list[Attachment] | None) -> list[Attachment]:
    """Preserve draft attachments and add MCP-readable context for images."""
    if not attachments:
        return []

    from general_chat.sources import image_search_text
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
        existing_text = (attachment.extracted_text or "").strip()
        if (
            existing_text
            and image_path in existing_text
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
                path=image_path,
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
        dashboard_source_path = metadata.get("localFilePath")
        dashboard_template_path = metadata.get("dashboardTemplatePath")
        extra_lines = ""
        image_tool_path = image_search_path if isinstance(image_search_path, str) else None
        sam_tool_path = sam_segmentation_path if isinstance(sam_segmentation_path, str) else None
        dashboard_tool_path = (
            dashboard_source_path if isinstance(dashboard_source_path, str) else None
        )
        template_tool_path = (
            dashboard_template_path if isinstance(dashboard_template_path, str) else None
        )
        if record.kind == "image" and image_tool_path:
            extra_lines = f"Image search path: {image_tool_path}\n\n"
        if record.kind == "image" and sam_tool_path:
            extra_lines += f"SAM 3 concept counting path: {sam_tool_path}\n\n"
        if record.kind == "spreadsheet" and dashboard_tool_path:
            extra_lines += (
                f"Dashboard source path: {dashboard_tool_path}\n"
                "For general tabular aggregation, call aggregate_data.extract_metadata "
                "when needed and aggregate_data.aggregate_data with this path.\n"
                "For dashboard requests, call aggregate_data.extract_metadata "
                "with this path first.\n\n"
            )
            extracted_text = (
                f"Source name: {record.name}\n"
                f"Source type: {record.kind}\n"
                f"Source URL: {record.url or '(none)'}\n\n"
                f"{extra_lines}"
                f"{_source_context_label()}\n\n"
                f"## {record.name}\n\n"
                "Spreadsheet raw rows are intentionally omitted from the chat prompt. "
                "Use Aggregate Data MCP for table-only aggregation. Use "
                "dashboard_generator.search_dashboards with this Dashboard source path "
                "to answer whether this file already has a saved dashboard. Use "
                "dashboard_generator.search_dashboards and dashboard_generator.load_dashboard "
                "for previous-dashboard load requests before asking for another file. "
                "For dashboard creation requests, call aggregate_data.extract_metadata, "
                "then dashboard_generator.search_dashboards with this source path before "
                "any aggregation. If the result has reusable_match=true or exact_source_match=true "
                "and the user did not ask for a revision, new chart type, new template, or "
                "special change, call dashboard_generator.load_dashboard and do not regenerate. "
                "Only call aggregate_data.aggregate_data and dashboard_generator.generate_dashboard "
                "when no reusable match exists or the user explicitly asks for changes."
            )
        elif record.kind == "dashboard_template" and template_tool_path:
            extra_lines += (
                f"Dashboard template path: {template_tool_path}\n"
                f"Dashboard template format: {metadata.get('dashboardTemplateFormat') or 'auto'}\n"
                "For dashboard requests that should use this uploaded template, pass "
                "this path as generate_dashboard(template_path=...).\n\n"
            )
            extracted_text = (
                f"Source name: {record.name}\n"
                f"Source type: {record.kind}\n"
                f"Source URL: {record.url or '(none)'}\n\n"
                f"{extra_lines}"
                f"{_source_context_label()}\n\n"
                f"## {record.name}\n\n{record.text}"
            )
        else:
            extracted_text = (
                f"Source name: {record.name}\n"
                f"Source type: {record.kind}\n"
                f"Source URL: {record.url or '(none)'}\n\n"
                f"{extra_lines}"
                f"{_source_context_label()}\n\n"
                f"## {record.name}\n\n{record.text}"
            )
        attachments.append(
            Attachment(
                id=record.id,
                type="image" if record.kind == "image" else "file",
                name=record.name,
                url=record.url or "",
                mime_type=record.mime_type or "text/plain",
                size_bytes=record.size_bytes,
                path=template_tool_path or dashboard_tool_path or sam_tool_path or image_tool_path,
                extracted_text=extracted_text,
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
    """Remove invalid conversation-turn sequences that break Gemini's API.

    A completed tool exchange is not enough by itself: if a request fails after
    tool results are appended but before the model produces a final assistant
    turn, the next user message leaves a stale function_response in history.
    Gemini can reject that replay with ``400 INVALID_ARGUMENT``. Keep tool
    exchanges only when another assistant turn follows and consumes them.
    """
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
            has_followup_assistant = j < n and messages[j].role == MessageRole.ASSISTANT
            has_replayable_raw_content = m.raw_content is not None
            if len(responses) == num_expected and has_followup_assistant and has_replayable_raw_content:
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
        memory_store: Any | None = None,
        doc_context: str | None = None,
        source_records: list[SourceRecord] | None = None,
        on_stream_complete: Callable[[list[SourceRecord]], None] | None = None,
        mcp_permission_coordinator: GeneralChatMCPPermissionCoordinator | None = None,
    ):
        super().__init__(engine)
        self._memory_store = memory_store or SQLiteMemoryStore(db_path=db_path)
        self._local = threading.local()
        self._doc_context = doc_context
        self._source_records = source_records or []
        self._on_stream_complete = on_stream_complete
        self._mcp_permission_coordinator = mcp_permission_coordinator

    async def _event_stream(self, body: dict[str, Any], accept: str) -> Any:
        try:
            async for item in super()._event_stream(body, accept):
                yield item
        finally:
            if self._on_stream_complete and self._source_records:
                self._on_stream_complete(self._source_records)

    def _extract_content(self, body):
        content, draft_attachments = super()._extract_content(body)
        attachments = _enrich_draft_attachments(draft_attachments)
        if self._source_records:
            source_attachments = _source_record_attachments(self._source_records)
            attachments = [*attachments, *source_attachments]
        if self._doc_context:
            source_attachments = _source_context_attachments(self._doc_context)
            attachments = [*attachments, *source_attachments]
        if attachments:
            attachments = _augment_with_visual_observations(
                agent=self.engine.agent,
                content=content,
                attachments=attachments,
            )
        return content, attachments or None

    def _get_or_create_session(self, session_id):
        self._local.session_id = session_id
        return super()._get_or_create_session(session_id)

    def _on_session_resolved(self, session_id):
        self._local.session_id = session_id

    def _after_user_message(self, session: ChatSession, content: str) -> None:
        if len(session.messages) != 1:
            return
        if session.title.strip() != _DEFAULT_SESSION_TITLE:
            return
        session.title = _generate_session_title(self.engine.agent, content)
        session.updated_at = datetime.now(timezone.utc)

    def _create_permission_context(
        self,
        *,
        session_id: str,
        thread_id: str,
        run_id: str,
        queue,
        loop,
    ):
        if self._mcp_permission_coordinator is None:
            return None

        def provider(request):
            return self._mcp_permission_coordinator.request_permission(
                session_id=session_id,
                run_id=run_id,
                request=request,
                queue=queue,
                loop=loop,
            )

        return MCPPermissionContext(provider)

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

        if not agent_copy.memory.messages or agent_copy.memory.messages[0].role != MessageRole.SYSTEM:
            agent_copy.memory.add_system(agent._system_prompt)

        agent_copy._llm = agent._llm
        if _debug_prompt_dir() is not None:
            agent_copy._llm = _DebugLLMProvider(
                agent_copy._llm or agent_copy._get_llm(),
                session_id=session_id,
            )
        agent_copy.tools = agent.tools
        return agent_copy
