"""AG-UI handler with per-session persistent memory for Lici."""

from __future__ import annotations

import copy
import threading

from openbench.chat.transport import AGUIHandler
from openbench.intelligence.base import AgentMemory, BaseAgent, MessageRole
from openbench.intelligence.memory import PersistentMemory, SQLiteMemoryStore


class LiciAGUIHandler(AGUIHandler):
    """AG-UI handler that gives every threadId its own SQLite-backed memory.

    The persona-composed system prompt (loaded from ``soul/``) is re-attached
    to each new session so the agent's identity survives restarts.
    """

    def __init__(self, engine, db_path: str = "lci_mini_memory.db"):
        super().__init__(engine)
        self._memory_store = SQLiteMemoryStore(db_path=db_path)
        self._current_session_id: str | None = None
        self._session_lock = threading.Lock()

    def _get_or_create_session(self, session_id):
        with self._session_lock:
            self._current_session_id = session_id
        return super()._get_or_create_session(session_id)

    def _create_request_agent(self):
        agent = self.engine.agent
        if not isinstance(agent, BaseAgent):
            return agent

        agent_copy = copy.copy(agent)

        with self._session_lock:
            session_id = self._current_session_id

        if session_id and self._memory_store:
            agent_copy.memory = PersistentMemory(
                store=self._memory_store,
                session_id=session_id,
            )
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
