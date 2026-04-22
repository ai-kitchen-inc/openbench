"""Contract test base class for :class:`MemoryStore` implementations.

Third-party backend authors inherit :class:`MemoryStoreContract`,
override :meth:`make_store` to produce a fresh store instance, and
optionally override :meth:`cleanup_store` to reset state between
tests. Everything else — 10+ conformance tests — is inherited.

The same base is used by the SDK's own ``tests/test_memory_store_contract.py``
to validate the shipped SQLite and Drive impls against the identical
bar a third-party ``PostgresMemoryStore`` must meet.

Example:

    from openbench.testing import MemoryStoreContract
    from my_company.stores import MyPostgresMemoryStore

    class TestMyPostgresStore(MemoryStoreContract):
        def make_store(self):
            return MyPostgresMemoryStore(conn=test_db_conn())

        def cleanup_store(self, store):
            store._conn.execute("TRUNCATE messages")

Run ``pytest tests/test_my_postgres_store.py`` — all inherited tests
execute against your impl.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from openbench.intelligence.base import Message, MessageRole
from openbench.intelligence.memory import MemoryStore


class MemoryStoreContract(ABC):
    """Inherit to validate a :class:`MemoryStore` implementation.

    Subclasses must provide :meth:`make_store`; everything else is
    handled by the base class. The test methods are discovered by
    pytest via the standard ``test_*`` naming convention.
    """

    # ── Abstract surface implementers must provide ──

    @abstractmethod
    def make_store(self) -> MemoryStore:
        """Return a fresh, empty store instance for one test.

        Called once per test method. The store should start with no
        sessions — contract tests create their own.
        """

    def cleanup_store(self, store: MemoryStore) -> None:
        """Optional teardown hook.

        Default is a no-op — many backends can skip this (SQLite in a
        tmp file, Drive mock cleared by its own fixture). Override for
        backends that need explicit cleanup between tests (Postgres
        TRUNCATE, Redis FLUSHDB, …).
        """

    # ── Helper for test messages ──

    def _msg(
        self,
        role: MessageRole = MessageRole.USER,
        content: str = "hello",
        **extras: object,
    ) -> Message:
        """Build a :class:`Message` with defaults + optional overrides."""
        return Message(role=role, content=content, **extras)  # type: ignore[arg-type]

    # ── Contract tests — inherited by every subclass ──

    def test_save_load_roundtrip(self):
        """Save a message list, load it back, get the same list in order."""
        store = self.make_store()
        try:
            store.save("s1", [self._msg(content="first"), self._msg(content="second")])
            loaded = store.load("s1")
            assert [m.content for m in loaded] == ["first", "second"]
            assert [m.role for m in loaded] == [MessageRole.USER, MessageRole.USER]
        finally:
            self.cleanup_store(store)

    def test_load_unknown_session_returns_empty_list(self):
        """Loading a session that was never saved returns ``[]``."""
        store = self.make_store()
        try:
            assert store.load("never-saved") == []
        finally:
            self.cleanup_store(store)

    def test_save_is_append_not_replace(self):
        """Two separate ``save`` calls append, not overwrite."""
        store = self.make_store()
        try:
            store.save("s1", [self._msg(content="first")])
            store.save("s1", [self._msg(content="second")])
            loaded = store.load("s1")
            assert [m.content for m in loaded] == ["first", "second"]
        finally:
            self.cleanup_store(store)

    def test_delete_session_removes_all_messages(self):
        """After delete, load returns empty list."""
        store = self.make_store()
        try:
            store.save("s1", [self._msg(content="a"), self._msg(content="b")])
            store.delete_session("s1")
            assert store.load("s1") == []
        finally:
            self.cleanup_store(store)

    def test_delete_session_is_idempotent(self):
        """Deleting a session twice is safe."""
        store = self.make_store()
        try:
            store.save("s1", [self._msg(content="a")])
            store.delete_session("s1")
            store.delete_session("s1")  # second delete must not raise
            assert store.load("s1") == []
        finally:
            self.cleanup_store(store)

    def test_delete_unknown_session_does_not_raise(self):
        """Deleting a session that doesn't exist is a no-op."""
        store = self.make_store()
        try:
            store.delete_session("never-existed")  # must not raise
        finally:
            self.cleanup_store(store)

    def test_delete_tail_removes_last_n(self):
        """``delete_tail(session, n)`` removes the last n messages."""
        store = self.make_store()
        try:
            store.save(
                "s1",
                [
                    self._msg(content="one"),
                    self._msg(content="two"),
                    self._msg(content="three"),
                ],
            )
            store.delete_tail("s1", 2)
            loaded = store.load("s1")
            assert [m.content for m in loaded] == ["one"]
        finally:
            self.cleanup_store(store)

    def test_delete_tail_count_exceeding_length_clears_session(self):
        """``delete_tail(session, n)`` with n >= len clears entire session."""
        store = self.make_store()
        try:
            store.save("s1", [self._msg(content="a"), self._msg(content="b")])
            store.delete_tail("s1", 5)
            assert store.load("s1") == []
        finally:
            self.cleanup_store(store)

    def test_delete_tail_zero_or_negative_is_noop(self):
        """``delete_tail`` with count <= 0 leaves the session unchanged."""
        store = self.make_store()
        try:
            store.save("s1", [self._msg(content="keep")])
            store.delete_tail("s1", 0)
            store.delete_tail("s1", -3)
            loaded = store.load("s1")
            assert [m.content for m in loaded] == ["keep"]
        finally:
            self.cleanup_store(store)

    def test_list_sessions_returns_known_ids(self):
        """``list_sessions`` enumerates every session that has been saved."""
        store = self.make_store()
        try:
            store.save("s1", [self._msg(content="a")])
            store.save("s2", [self._msg(content="b")])
            store.save("s3", [self._msg(content="c")])
            sessions = sorted(store.list_sessions())
            assert "s1" in sessions
            assert "s2" in sessions
            assert "s3" in sessions
        finally:
            self.cleanup_store(store)

    def test_preserves_tool_call_fields(self):
        """``tool_calls`` / ``tool_call_id`` / ``name`` survive roundtrip.

        Critical for the Layer 1 validator: orphan detection requires
        these fields be preserved exactly through save/load.
        """
        store = self.make_store()
        try:
            store.save(
                "s1",
                [
                    Message(
                        role=MessageRole.ASSISTANT,
                        content="ran tool",
                        tool_calls=[{"id": "call_x", "name": "my_tool", "arguments": {}}],
                    ),
                    Message(
                        role=MessageRole.TOOL,
                        content='{"ok": true}',
                        name="my_tool",
                        tool_call_id="call_x",
                    ),
                ],
            )
            loaded = store.load("s1")
            assert len(loaded) == 2
            assert loaded[0].tool_calls is not None
            assert loaded[0].tool_calls[0]["id"] == "call_x"
            assert loaded[1].tool_call_id == "call_x"
            assert loaded[1].name == "my_tool"
        finally:
            self.cleanup_store(store)

    def test_empty_save_is_noop(self):
        """``save(session, [])`` is a no-op, not an error."""
        store = self.make_store()
        try:
            store.save("s1", [])
            assert store.load("s1") == []
        finally:
            self.cleanup_store(store)
