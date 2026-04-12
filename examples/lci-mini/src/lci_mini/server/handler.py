"""AG-UI handler with per-session persistent memory for Lici."""

from __future__ import annotations

import copy
import threading

from openbench.chat.transport import AGUIHandler
from openbench.intelligence.base import AgentMemory, BaseAgent, Message, MessageRole
from openbench.intelligence.memory import PersistentMemory, SQLiteMemoryStore


def sanitize_messages(messages: list[Message]) -> list[Message]:
    """Remove invalid conversation-turn sequences.

    Gemini (and most function-calling LLMs) require strict turn ordering:

    - ``assistant(tool_calls)`` must be immediately followed by one
      ``tool(result)`` per call
    - ``tool(result)`` must be preceded by a matching ``assistant(tool_calls)``
    - Cannot have ``user → user`` or ``assistant → assistant`` runs

    When an earlier request fails mid-iteration (exception between adding
    the assistant tool-call message and adding all the tool-result
    messages), PersistentMemory ends up with orphaned turns that cause
    every *subsequent* request to fail with 400 INVALID_ARGUMENT. This
    helper walks the message list and drops anything that would violate
    Gemini's turn-ordering contract, keeping the rest of the history
    intact so the conversation can continue.

    Dropped:
    - ``assistant(tool_calls)`` whose responses are missing or incomplete
      (and any partial tool responses that followed it)
    - ``tool(result)`` with no preceding ``assistant(tool_calls)``
    - Duplicate consecutive user messages (keeps the latest)
    - Duplicate consecutive text-only assistant messages (keeps the latest)
    """
    if not messages:
        return messages

    def _collapse_tail(buf: list[Message], incoming: Message) -> None:
        """Append incoming to buf, collapsing consecutive same-role turns.

        Rules:
        - Consecutive USER messages: keep the incoming (latest)
        - Consecutive text-only ASSISTANT messages: keep the incoming
        - Everything else: append normally
        Tool-bearing assistants always append (they cannot collapse with
        a plain text assistant because we'd lose the tool call).
        """
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

        # System always passes through (only the first one is meaningful)
        if m.role == MessageRole.SYSTEM:
            _collapse_tail(out, m)
            i += 1
            continue

        # Assistant with tool_calls — require one matching tool message per call
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
                # Orphaned: drop the assistant and any partial tool responses
                i = j
            continue

        # Tool response with no preceding assistant(tool_calls) — drop
        if m.role == MessageRole.TOOL:
            i += 1
            continue

        # Plain user / text assistant / other — collapse-on-append
        _collapse_tail(out, m)
        i += 1

    return out


class LiciAGUIHandler(AGUIHandler):
    """AG-UI handler that gives every threadId its own SQLite-backed memory.

    The persona-composed system prompt (loaded from ``soul/``) is re-attached
    to each new session so the agent's identity survives restarts. Memory
    is sanitized on every load so orphaned tool turns from earlier failed
    requests don't poison subsequent ones.
    """

    def __init__(self, engine, db_path: str = "lci_mini_memory.db"):
        super().__init__(engine)
        self._memory_store = SQLiteMemoryStore(db_path=db_path)
        # Thread-local storage for session_id so concurrent requests
        # (each in its own thread via asyncio.to_thread) don't cross-
        # contaminate. The old approach stored session_id on the
        # instance — two concurrent requests could swap each other's
        # session memory.
        self._local = threading.local()

    def _get_or_create_session(self, session_id):
        self._local.session_id = session_id
        return super()._get_or_create_session(session_id)

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
            # Repair any corruption from earlier failed requests BEFORE the
            # agent sends the history to Gemini. PersistentMemory auto-saves
            # per-message, so a mid-iteration exception can leave dangling
            # tool-call messages; sanitize them out here.
            original = list(agent_copy.memory.messages)
            sanitized = sanitize_messages(original)
            if len(sanitized) != len(original):
                dropped = len(original) - len(sanitized)
                print(
                    f"  [lici] sanitized session {session_id}: "
                    f"dropped {dropped} orphaned/duplicate message(s)"
                )
                agent_copy.memory.messages = sanitized
        else:
            agent_copy.memory = AgentMemory()

        # Seed or refresh the system message so the persona is always present.
        if (
            not agent_copy.memory.messages
            or agent_copy.memory.messages[0].role != MessageRole.SYSTEM
        ):
            agent_copy.memory.add_system(agent._system_prompt)

        # Share read-only LLM + tools across request-scoped copies.
        agent_copy._llm = agent._llm
        agent_copy.tools = agent.tools
        return agent_copy
