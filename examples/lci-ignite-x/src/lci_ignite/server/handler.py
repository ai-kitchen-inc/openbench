"""LCI AG-UI Handler with per-session persistent memory.

Extends AGUIHandler to provide persistent conversation memory
per AG-UI thread using SQLiteMemoryStore.
"""

from __future__ import annotations

import copy
import threading

from openbench.chat.transport import AGUIHandler
from openbench.intelligence.base import AgentMemory, BaseAgent, MessageRole
from openbench.intelligence.memory import PersistentMemory, SQLiteMemoryStore


class LCIAGUIHandler(AGUIHandler):
    """AG-UI handler with per-session persistent memory.

    Each AG-UI threadId maps to a persistent memory session backed by
    SQLite. Conversations persist across server restarts.

    Args:
        engine: ChatEngine instance.
        db_path: Path to SQLite database for memory storage.
    """

    def __init__(self, engine, db_path: str = "lci_memory.db"):
        super().__init__(engine)
        self._memory_store = SQLiteMemoryStore(db_path=db_path)
        self._current_session_id: str | None = None
        self._session_lock = threading.Lock()

    def _get_or_create_session(self, session_id):
        """Track current session_id for agent creation, then delegate."""
        with self._session_lock:
            self._current_session_id = session_id
        return super()._get_or_create_session(session_id)

    def _create_request_agent(self):
        """Create a request-scoped agent with persistent memory."""
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

        # Add system prompt if not already present
        if (
            not agent_copy.memory.messages
            or agent_copy.memory.messages[0].role != MessageRole.SYSTEM
        ):
            agent_copy.memory.add_system(agent._system_prompt)

        # Share LLM provider and tools (thread-safe, read-only)
        agent_copy._llm = agent._llm
        agent_copy.tools = agent.tools
        return agent_copy
