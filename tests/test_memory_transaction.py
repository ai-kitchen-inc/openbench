"""Tests for :meth:`PersistentMemory.turn` — atomic per-turn commit.

The contract we're validating: when a crash (exception or process kill)
happens between ``add_assistant(tool_calls=...)`` and its matching
``add_tool_result`` calls, the SQLite-backed store must not have
persisted the orphan assistant row. The in-memory list must also roll
back to the pre-turn state so a subsequent retry starts clean.
"""

from __future__ import annotations

import pytest

from openbench.intelligence.base import MessageRole
from openbench.intelligence.memory import PersistentMemory, SQLiteMemoryStore


@pytest.fixture
def store(tmp_path):
    return SQLiteMemoryStore(db_path=str(tmp_path / "memory.db"))


@pytest.fixture
def memory(store):
    return PersistentMemory(store=store, session_id="sess-1")


class TestTurnCommit:
    def test_commit_persists_all_messages(self, memory, store):
        """Normal exit from turn — every buffered add reaches the store."""
        with memory.turn():
            memory.add_user("hello")
            memory.add_assistant("hi", tool_calls=[{"id": "c1", "name": "t"}])
            memory.add_tool_result("c1", "t", '{"ok": true}')

        persisted = store.load("sess-1")
        assert [m.role for m in persisted] == [
            MessageRole.USER,
            MessageRole.ASSISTANT,
            MessageRole.TOOL,
        ]
        assert persisted[2].tool_call_id == "c1"

    def test_store_untouched_during_turn(self, memory, store):
        """While inside the turn, the store must NOT see partial writes."""
        with memory.turn():
            memory.add_user("hello")
            memory.add_assistant("working", tool_calls=[{"id": "c1", "name": "t"}])
            # Mid-turn snapshot: store still empty
            assert store.load("sess-1") == []

        # After turn exits normally, everything flushed.
        assert len(store.load("sess-1")) == 2


class TestTurnRollback:
    def test_rollback_on_exception_discards_writes(self, memory, store):
        """Exception during turn → store state unchanged."""

        class Boom(Exception):
            pass

        with pytest.raises(Boom), memory.turn():
            memory.add_user("hello")
            memory.add_assistant("thinking", tool_calls=[{"id": "c1", "name": "t"}])
            raise Boom("tool exec died")

        # Nothing persisted
        assert store.load("sess-1") == []

    def test_rollback_syncs_in_memory_list(self, memory):
        """In-memory ``messages`` must be truncated back to pre-turn length
        on rollback, so a retry doesn't see the dead turn."""
        memory.add_user("pre-existing")
        pre_len = len(memory.messages)

        with pytest.raises(RuntimeError), memory.turn():
            memory.add_assistant("working", tool_calls=[{"id": "c1", "name": "t"}])
            memory.add_tool_result("c1", "t", '{"x": 1}')
            assert len(memory.messages) == pre_len + 2
            raise RuntimeError("simulated")

        assert len(memory.messages) == pre_len
        assert memory.messages[-1].content == "pre-existing"

    def test_rollback_handles_truncate_to_during_turn(self, memory, store):
        """``BaseAgent``'s tool-exec except-handler calls ``truncate_to``
        before re-raising. Validator test: that path must play nicely
        with the turn — in-memory list stays consistent, store untouched,
        turn's final rollback is a no-op (everything already cleaned)."""
        memory.add_user("pre")
        pre_len = len(memory.messages)

        with pytest.raises(Exception, match="tool died"), memory.turn():
            memory.add_assistant("calling", tool_calls=[{"id": "c1", "name": "t"}])
            assert len(memory.messages) == pre_len + 1
            # Simulate BaseAgent's rollback before re-raise
            memory.truncate_to(pre_len)
            assert len(memory.messages) == pre_len
            raise Exception("tool died")

        # Store never saw the orphan
        assert store.load("sess-1") == [memory.messages[0]]
        # In-memory list still correct
        assert len(memory.messages) == pre_len


class TestTurnMisc:
    def test_nested_turn_raises(self, memory):
        """Nested turns are not supported — explicit failure beats silent
        inconsistency if someone accidentally nests."""
        with memory.turn(), pytest.raises(RuntimeError, match=r"[Nn]ested"), memory.turn():
            pass

    def test_disabled_by_env_falls_back_to_autocommit(self, memory, store, monkeypatch):
        """``OPENBENCH_TURN_TRANSACTION=0`` reverts to per-message commit.

        Demonstrates the rollback lever: an exception mid-turn leaves
        the orphan in the store, matching pre-Layer-2a behaviour.
        """
        monkeypatch.setenv("OPENBENCH_TURN_TRANSACTION", "0")

        class Boom(Exception):
            pass

        with pytest.raises(Boom), memory.turn():  # no-op context
            memory.add_user("hello")
            # With flag off, add() autocommits each message
            assert len(store.load("sess-1")) == 1
            memory.add_assistant("working", tool_calls=[{"id": "c1", "name": "t"}])
            raise Boom("no transaction to roll back")

        # With flag off, the orphan assistant reaches the store —
        # this is exactly the bug Layer 2a prevents when the flag is on.
        persisted = store.load("sess-1")
        assert [m.role for m in persisted] == [
            MessageRole.USER,
            MessageRole.ASSISTANT,
        ]
        assert persisted[1].tool_calls == [{"id": "c1", "name": "t"}]

    def test_survives_process_restart_simulation(self, tmp_path):
        """Simulates a process kill mid-turn: drop the PersistentMemory
        instance without ever reaching turn-commit, then open a fresh
        instance against the same SQLite file. The store must NOT
        resurrect the orphan assistant row."""
        store = SQLiteMemoryStore(db_path=str(tmp_path / "memory.db"))

        memory1 = PersistentMemory(store=store, session_id="sess-1")
        memory1.add_user("hello")  # autocommitted (outside turn)

        # Enter turn manually so we can simulate dying mid-turn without
        # unwinding the context. A `with memory1.turn(): ...` block would
        # automatically rollback via its finally — we want the "process
        # dies before finally" case.
        turn_ctx = memory1.turn()
        turn_ctx.__enter__()
        try:
            memory1.add_assistant("working", tool_calls=[{"id": "c1", "name": "t"}])
            # Pretend the process died here — drop reference without
            # exiting the context.
        finally:
            # In a real crash this wouldn't run. Here we simulate the
            # crash by NOT exiting the generator; just abandon the object.
            pass
        del memory1
        del turn_ctx

        # Fresh instance — same pattern as next process startup
        memory2 = PersistentMemory(store=store, session_id="sess-1")
        assert [m.role for m in memory2.messages] == [MessageRole.USER]
        assert memory2.messages[0].content == "hello"
