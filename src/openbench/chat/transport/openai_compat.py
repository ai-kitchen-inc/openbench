"""OpenAI-compatible chat transport for OpenBench chat engines.

Open WebUI can connect to custom backends through the OpenAI Chat Completions
API. This module exposes a :class:`ChatEngine` as a small ``/v1`` provider
without replacing OpenBench's agent, memory, tool, or workflow internals.
"""

from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from collections.abc import Callable, Iterable
from typing import Any

from openbench.chat.session import Attachment, ChatSession
from openbench.intelligence.base import AgentMemory, BaseAgent, Message, MessageRole


OpenAIEngineFactory = Callable[[ChatSession], Any]
AttachmentResolver = Callable[[dict[str, Any], str | None], Iterable[Attachment | dict[str, Any]]]
SystemPromptFactory = Callable[[dict[str, Any]], str | None]
MessageSanitizer = Callable[[list[Message]], list[Message]]


def _message_content_to_text(content: Any) -> str:
    """Normalize OpenAI message content into plain text for OpenBench agents."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if not isinstance(block, dict):
                parts.append(str(block))
                continue

            block_type = str(block.get("type") or "")
            if block_type in {"text", "input_text"} or "text" in block:
                text = block.get("text")
                if text:
                    parts.append(str(text))
                continue

            if block_type == "image_url":
                image_url = block.get("image_url")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                if image_url:
                    parts.append(f"[Image: {image_url}]")
                continue

            if block_type == "file":
                name = block.get("name") or block.get("filename") or "file"
                text = block.get("content") or block.get("text") or ""
                parts.append(f"[File: {name}]\n{text}".strip())
                continue

            parts.append(json.dumps(block, ensure_ascii=False, default=str))
        return "\n\n".join(part for part in parts if part).strip()
    return str(content)


def _json_sse(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _usage_from_metadata(metadata: dict[str, Any]) -> dict[str, int]:
    prompt_tokens = int(metadata.get("prompt_tokens") or 0)
    completion_tokens = int(metadata.get("completion_tokens") or 0)
    tokens_used = int(metadata.get("tokens_used") or 0)
    if not completion_tokens and tokens_used:
        completion_tokens = tokens_used
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


class OpenAICompatHandler:
    """Expose an OpenBench ``ChatEngine`` through OpenAI Chat Completions.

    The handler is intentionally transport-only: Open WebUI owns the browser UI
    and sends history in each request, while OpenBench still executes the agent
    through ``ChatEngine._execute_agent`` so tools, personas, attachments, and
    framework adapters keep working.
    """

    def __init__(
        self,
        *,
        engine: Any | None = None,
        build_engine: OpenAIEngineFactory | None = None,
        base_agent: Any | None = None,
        model_id: str = "openbench-chat",
        attachment_resolver: AttachmentResolver | None = None,
        extra_system_prompt: str | SystemPromptFactory | None = None,
        message_sanitizer: MessageSanitizer | None = None,
    ) -> None:
        if engine is None and build_engine is None:
            raise ValueError("OpenAICompatHandler requires engine= or build_engine=.")
        self._engine = engine
        self._build_engine = build_engine
        self._base_agent = base_agent if base_agent is not None else getattr(engine, "agent", None)
        self._model_id = model_id
        self._attachment_resolver = attachment_resolver
        self._extra_system_prompt = extra_system_prompt
        self._message_sanitizer = message_sanitizer

    def models(self) -> dict[str, Any]:
        """Return an OpenAI-compatible model list."""
        return {
            "object": "list",
            "data": [
                {
                    "id": self._model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": "openbench",
                }
            ],
        }

    async def chat_completions(self, body: dict[str, Any]) -> Any:
        """Handle ``POST /v1/chat/completions``."""
        if not isinstance(body.get("messages"), list):
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="'messages' must be a list.")

        if body.get("stream"):
            from fastapi.responses import StreamingResponse

            return StreamingResponse(
                self._stream_chat(body),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        try:
            content, metadata = await asyncio.to_thread(self._run_turn, body, None)
        except ValueError as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self._model_id,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": _usage_from_metadata(metadata),
        }

    async def _stream_chat(self, body: dict[str, Any]):
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        emitted_parts: list[str] = []

        def on_chunk(delta: str) -> None:
            if not delta:
                return
            emitted_parts.append(delta)
            loop.call_soon_threadsafe(queue.put_nowait, delta)

        task = asyncio.create_task(asyncio.to_thread(self._run_turn, body, on_chunk))

        def on_done(_future: asyncio.Future) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, None)

        task.add_done_callback(on_done)

        yield _json_sse(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": self._model_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant"},
                        "finish_reason": None,
                    }
                ],
            }
        )

        while True:
            item = await queue.get()
            if item is None:
                break
            yield _json_sse(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": self._model_id,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": item},
                            "finish_reason": None,
                        }
                    ],
                }
            )

        try:
            content, metadata = await task
        except Exception as exc:
            content = f"OpenAI-compatible request failed: {exc}"
            metadata = {"error": str(exc)}

        if not emitted_parts and content:
            yield _json_sse(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": self._model_id,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": content},
                            "finish_reason": None,
                        }
                    ],
                }
            )

        final_chunk: dict[str, Any] = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": self._model_id,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop" if "error" not in metadata else "error",
                }
            ],
        }
        stream_options = body.get("stream_options")
        if isinstance(stream_options, dict) and stream_options.get("include_usage"):
            final_chunk["usage"] = _usage_from_metadata(metadata)
        yield _json_sse(final_chunk)
        yield _json_sse("[DONE]")

    def _run_turn(
        self,
        body: dict[str, Any],
        on_chunk: Callable[[str], None] | None,
    ) -> tuple[str, dict[str, Any]]:
        messages = body.get("messages")
        if not isinstance(messages, list):
            raise ValueError("'messages' must be a list.")

        last_user_index = self._last_user_index(messages)
        if last_user_index is None:
            raise ValueError("At least one user message is required.")

        user_message = messages[last_user_index]
        if not isinstance(user_message, dict):
            raise ValueError("User message must be an object.")
        content = _message_content_to_text(user_message.get("content")).strip()
        if not content:
            raise ValueError("The last user message is empty.")

        session_id = self._session_id_from_body(body)
        session = ChatSession(session_id=session_id or f"openwebui-{uuid.uuid4().hex[:8]}")
        engine = self._build_engine_for_session(session)
        base_agent = self._base_agent if self._base_agent is not None else getattr(engine, "agent", None)
        request_agent = self._build_request_agent(body, messages[:last_user_index], base_agent)
        attachments = self._attachments_from_body(body, session_id)

        result = engine._execute_agent(
            content,
            None,
            attachments=attachments,
            on_chunk=on_chunk,
            session=session,
            agent=request_agent,
        )
        metadata = engine._extract_metadata(result)
        failed, error_message = engine._result_failed(result)
        if failed:
            return error_message, metadata

        output = engine._extract_output(result)
        return engine._extract_text_content(output), metadata

    def _build_engine_for_session(self, session: ChatSession) -> Any:
        if self._build_engine is not None:
            return self._build_engine(session)
        return self._engine

    def _build_request_agent(
        self,
        body: dict[str, Any],
        history: list[Any],
        base_agent: Any,
    ) -> Any:
        if not isinstance(base_agent, BaseAgent):
            return base_agent

        agent_copy = copy.copy(base_agent)
        agent_copy.memory = AgentMemory()

        system_prompt = base_agent._system_prompt
        extra_prompt = self._resolve_extra_system_prompt(body)
        if extra_prompt and extra_prompt not in system_prompt:
            system_prompt = f"{system_prompt}\n\n{extra_prompt}"

        openwebui_system = self._system_context(history)
        if openwebui_system:
            system_prompt = (
                f"{system_prompt}\n\n"
                "[Open WebUI System Messages]\n"
                f"{openwebui_system}"
            )

        agent_copy.memory.add_system(system_prompt)
        self._append_history(agent_copy.memory, history)
        if self._message_sanitizer is not None:
            agent_copy.memory.messages = self._message_sanitizer(agent_copy.memory.messages)

        if isinstance(body.get("temperature"), (int, float)):
            agent_copy.temperature = float(body["temperature"])

        agent_copy._llm = base_agent._llm
        agent_copy.tools = base_agent.tools
        return agent_copy

    def _resolve_extra_system_prompt(self, body: dict[str, Any]) -> str | None:
        if callable(self._extra_system_prompt):
            return self._extra_system_prompt(body)
        return self._extra_system_prompt

    @staticmethod
    def _last_user_index(messages: list[Any]) -> int | None:
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if isinstance(message, dict) and message.get("role") == "user":
                return index
        return None

    @staticmethod
    def _system_context(messages: list[Any]) -> str:
        system_messages = []
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "system":
                continue
            content = _message_content_to_text(message.get("content")).strip()
            if content:
                system_messages.append(content)
        return "\n\n".join(system_messages)

    @staticmethod
    def _append_history(memory: AgentMemory, messages: list[Any]) -> None:
        role_map = {
            "user": MessageRole.USER,
            "assistant": MessageRole.ASSISTANT,
            "tool": MessageRole.TOOL,
        }
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "")
            if role == "system":
                continue
            mapped_role = role_map.get(role)
            if mapped_role is None:
                continue
            content = _message_content_to_text(message.get("content")).strip()
            if not content:
                continue
            memory.add(mapped_role, content)

    @staticmethod
    def _session_id_from_body(body: dict[str, Any]) -> str | None:
        metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        candidates = [
            metadata.get("session_id"),
            metadata.get("chat_id"),
            metadata.get("id"),
            body.get("session_id"),
            body.get("chat_id"),
            body.get("conversation_id"),
            body.get("user"),
        ]
        for value in candidates:
            if value:
                return str(value)
        return None

    def _attachments_from_body(
        self,
        body: dict[str, Any],
        session_id: str | None,
    ) -> list[Attachment] | None:
        attachments: list[Attachment] = []

        files = body.get("files")
        if not files and isinstance(body.get("metadata"), dict):
            files = body["metadata"].get("files")

        if isinstance(files, list):
            for index, item in enumerate(files):
                attachment = self._attachment_from_openwebui_file(item, index)
                if attachment is not None:
                    attachments.append(attachment)

        if self._attachment_resolver is not None:
            for item in self._attachment_resolver(body, session_id):
                attachment = self._coerce_attachment(item)
                if attachment is not None:
                    attachments.append(attachment)

        return attachments or None

    @classmethod
    def _coerce_attachment(cls, item: Attachment | dict[str, Any]) -> Attachment | None:
        if isinstance(item, Attachment):
            return item
        if not isinstance(item, dict):
            return None
        return Attachment(
            id=str(item.get("id") or uuid.uuid4().hex),
            type=str(item.get("type") or "file"),
            name=str(item.get("name") or item.get("filename") or "attachment"),
            url=str(item.get("url") or ""),
            mime_type=str(item.get("mimeType") or item.get("mime_type") or "text/plain"),
            size_bytes=item.get("sizeBytes") or item.get("size_bytes"),
            extracted_text=item.get("extractedText") or item.get("extracted_text"),
            path=item.get("path"),
        )

    @staticmethod
    def _attachment_from_openwebui_file(item: Any, index: int) -> Attachment | None:
        if not isinstance(item, dict):
            return None
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        content = (
            item.get("content")
            or item.get("text")
            or item.get("extracted_text")
            or item.get("extractedText")
            or data.get("content")
            or data.get("text")
        )
        if not content:
            return None

        name = (
            item.get("name")
            or item.get("filename")
            or item.get("file_name")
            or data.get("name")
            or f"openwebui-file-{index + 1}"
        )
        mime_type = (
            item.get("mime_type")
            or item.get("mimeType")
            or data.get("mime_type")
            or data.get("mimeType")
            or "text/plain"
        )
        return Attachment(
            id=str(item.get("id") or data.get("id") or f"openwebui-file-{index + 1}"),
            type="file",
            name=str(name),
            url=str(item.get("url") or data.get("url") or ""),
            mime_type=str(mime_type),
            extracted_text=str(content),
        )


def create_openai_compatible_router(
    handler: OpenAICompatHandler | None = None,
    *,
    engine: Any | None = None,
    build_engine: OpenAIEngineFactory | None = None,
    base_agent: Any | None = None,
    model_id: str = "openbench-chat",
    attachment_resolver: AttachmentResolver | None = None,
    extra_system_prompt: str | SystemPromptFactory | None = None,
    message_sanitizer: MessageSanitizer | None = None,
) -> Any:
    """Create a FastAPI router exposing ``/models`` and ``/chat/completions``.

    Mount it under ``/v1`` for Open WebUI:

    ``app.include_router(create_openai_compatible_router(engine=engine), prefix="/v1")``
    """
    from fastapi import APIRouter, Request

    compat = handler or OpenAICompatHandler(
        engine=engine,
        build_engine=build_engine,
        base_agent=base_agent,
        model_id=model_id,
        attachment_resolver=attachment_resolver,
        extra_system_prompt=extra_system_prompt,
        message_sanitizer=message_sanitizer,
    )
    router = APIRouter()

    @router.get("/models")
    async def openai_models() -> dict[str, Any]:
        return compat.models()

    async def openai_chat_completions(request) -> Any:
        body = await request.json()
        return await compat.chat_completions(body)

    # ``from __future__ import annotations`` stores annotations as strings.
    # Because this route is created inside a factory, a local ``Request`` import
    # is otherwise invisible to FastAPI's signature resolver and ``request`` is
    # treated as a required query parameter.
    openai_chat_completions.__annotations__["request"] = Request
    router.add_api_route(
        "/chat/completions",
        openai_chat_completions,
        methods=["POST"],
    )

    return router
