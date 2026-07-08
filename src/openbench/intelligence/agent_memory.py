"""In-memory conversation buffer for OpenBench agents.

Provides :class:`AgentMemory` — a bounded, trimmable message buffer with an
atomic ``turn()`` context (a no-op here; :class:`PersistentMemory` overrides it
to flush writes atomically). Extracted from ``intelligence/base.py``; ``base``
still re-exports it for backward compatibility.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from openbench.intelligence.messages import Message, MessageRole

if TYPE_CHECKING:
    from collections.abc import Iterator

    from openbench.core.abstractions import MediaContent

logger = logging.getLogger(__name__)


@dataclass
class AgentMemory:
    """Agent conversation memory."""

    messages: list[Message] = field(default_factory=list)
    max_messages: int = 100
    max_tokens: int | None = None

    @contextmanager
    def turn(self) -> Iterator[None]:
        """Atomic turn context. Base ``AgentMemory`` is a no-op.

        :class:`PersistentMemory` overrides this to buffer writes during
        the turn and flush atomically at the end, so a process crash
        mid-turn cannot leave the backing store with orphan
        ``tool_calls`` that lack matching tool responses.
        """
        yield

    @staticmethod
    def _message_tokens(message: Message) -> int:
        """Rough token estimate for one message (~4 chars per token).

        Counts the text ``content`` plus serialized ``tool_calls`` — tool-call
        arguments are real prompt tokens, so ignoring them (as the original
        content-only estimate did) badly undercounts tool-heavy turns.
        """
        chars = len(message.content)
        if message.tool_calls:
            chars += len(json.dumps(message.tool_calls, default=str))
        return chars // 4

    def _estimate_tokens(self) -> int:
        """Rough token estimate across all messages (~4 chars per token)."""
        return sum(self._message_tokens(m) for m in self.messages)

    def _trim_oldest(self, keep_count: int) -> None:
        """Trim oldest messages, preserving system message."""
        if self.messages and self.messages[0].role == MessageRole.SYSTEM:
            self.messages = [self.messages[0], *self.messages[-(keep_count - 1) :]]
        else:
            self.messages = self.messages[-keep_count:]

    def add(self, role: MessageRole, content: str, **kwargs) -> None:
        """Add message to memory."""
        self.messages.append(Message(role=role, content=content, **kwargs))

        # Trim by message count
        if len(self.messages) > self.max_messages:
            self._trim_oldest(self.max_messages)

        # Trim by token budget
        if self.max_tokens and self._estimate_tokens() > self.max_tokens:
            # Remove oldest non-system messages until under budget
            while len(self.messages) > 1 and self._estimate_tokens() > self.max_tokens:
                # Find first non-system message to remove
                for i, m in enumerate(self.messages):
                    if m.role != MessageRole.SYSTEM:
                        self.messages.pop(i)
                        break
                else:
                    break
            # Warn if still over budget (system message alone exceeds limit)
            if self._estimate_tokens() > self.max_tokens:
                logger.warning(
                    "System message alone (~%d tokens) exceeds max_tokens (%d). "
                    "Consider increasing max_tokens or shortening the system prompt.",
                    self._estimate_tokens(),
                    self.max_tokens,
                )

    def add_system(self, content: str) -> None:
        """Add system message."""
        self.add(MessageRole.SYSTEM, content)

    def add_user(self, content: str, media: list[MediaContent] | None = None) -> None:
        """Add user message, optionally with provider-neutral media references."""
        self.add(MessageRole.USER, content, media=media)

    def add_assistant(
        self,
        content: str,
        tool_calls: list[dict] | None = None,
        raw_content: Any = None,
    ) -> None:
        """Add assistant message."""
        self.add(
            MessageRole.ASSISTANT,
            content,
            tool_calls=tool_calls,
            raw_content=raw_content,
        )

    def add_tool_result(self, tool_call_id: str, name: str, result: str) -> None:
        """Add tool result message."""
        self.add(MessageRole.TOOL, result, name=name, tool_call_id=tool_call_id)

    def get_messages(self, token_budget: int | None = None) -> list[dict[str, Any]]:
        """Get messages in LLM-compatible format.

        Args:
            token_budget: Optional soft cap on prompt tokens. When ``None``
                (default) the full history is returned unchanged — no behavior
                change for callers that don't opt in. When set, return a
                pairing-safe sliding window: leading system message(s) plus the
                most recent messages that fit the budget.

        The window is **read-only** — it does not mutate the stored buffer, so
        persistence and the execute-loop rollback are unaffected. It never
        starts on an orphan ``tool`` result (whose matching ``tool_calls``
        assistant turn fell outside the window), which Gemini rejects: because
        the kept messages are a contiguous suffix, every ``tool`` result still
        follows its call, and any ``tool`` messages left dangling at the front
        are trimmed. If the window would open on an assistant function-call
        turn (its triggering user message fell outside the budget), the most
        recent preceding user message is re-inserted as an anchor — Gemini
        rejects a function call that does not follow a user turn or a function
        response turn, and a slightly oversized prompt beats a hard 400.
        """
        if token_budget is None:
            return [m.to_dict() for m in self.messages]

        system = [m for m in self.messages if m.role == MessageRole.SYSTEM]
        rest = [m for m in self.messages if m.role != MessageRole.SYSTEM]

        used = sum(self._message_tokens(m) for m in system)
        window: list[Message] = []
        # Walk newest -> oldest; always keep the most recent message so the
        # current turn is never dropped, then keep older turns until the budget
        # is exhausted.
        for message in reversed(rest):
            cost = self._message_tokens(message)
            if window and used + cost > token_budget:
                break
            window.append(message)
            used += cost
        window.reverse()

        # Drop leading orphan tool results (their assistant call fell outside).
        while window and window[0].role == MessageRole.TOOL:
            window.pop(0)

        # Re-anchor a window that opens on an assistant function-call turn:
        # its user message fell outside the budget, and Gemini rejects a
        # function call that is not preceded by a user or function-response
        # turn. Insert the most recent user message from before the window.
        if window and window[0].role == MessageRole.ASSISTANT and window[0].tool_calls:
            before_window = rest[: len(rest) - len(window)]
            anchor = next(
                (m for m in reversed(before_window) if m.role == MessageRole.USER),
                None,
            )
            if anchor is not None:
                window.insert(0, anchor)

        return [m.to_dict() for m in (*system, *window)]

    def clear(self) -> None:
        """Clear all messages except system."""
        if self.messages and self.messages[0].role == MessageRole.SYSTEM:
            self.messages = [self.messages[0]]
        else:
            self.messages = []

    def truncate_to(self, length: int) -> None:
        """Truncate message history to the given length.

        Subclasses that persist messages (e.g. ``PersistentMemory``) must
        override this so the persistent store is kept in sync — otherwise
        rollback after a failed turn only affects the in-memory list and
        orphaned messages will resurface when the session is reloaded.

        Args:
            length: Number of messages to keep from the start. Must be >= 0.
                Values larger than the current length are a no-op.
        """
        if length < 0:
            length = 0
        if length < len(self.messages):
            self.messages = self.messages[:length]
