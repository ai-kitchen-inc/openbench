"""Tests for openbench.chat.render_queue.

This is the shared per-request queue that SDK skills push A2UI render
items into. ChatEngine reads from it via render_items_fn. The queue is
backed by contextvars.ContextVar so tests verify both the happy path
and basic isolation semantics.
"""

from __future__ import annotations

import asyncio
import contextvars
import unittest

from openbench.chat import render_queue


class TestRenderQueueBasics(unittest.TestCase):
    def setUp(self):
        render_queue.clear()

    def tearDown(self):
        render_queue.clear()

    def test_empty_after_clear(self):
        self.assertEqual(render_queue.get_items(), [])

    def test_push_one_item(self):
        item = {"name": "report.xlsx", "url": "/downloads/report.xlsx"}
        render_queue.push(item)
        self.assertEqual(render_queue.get_items(), [item])

    def test_push_multiple_items(self):
        a = {"name": "a.xlsx", "url": "/downloads/a.xlsx"}
        b = {"name": "b.xlsx", "url": "/downloads/b.xlsx"}
        render_queue.push(a)
        render_queue.push(b)
        self.assertEqual(render_queue.get_items(), [a, b])

    def test_push_many(self):
        items = [
            {"name": "a.xlsx", "url": "/downloads/a.xlsx"},
            {"name": "b.xlsx", "url": "/downloads/b.xlsx"},
            {"type": "bar", "title": "chart", "data": []},
        ]
        render_queue.push_many(items)
        self.assertEqual(render_queue.get_items(), items)

    def test_clear_empties_queue(self):
        render_queue.push({"name": "a.xlsx", "url": "/x"})
        render_queue.push({"name": "b.xlsx", "url": "/x"})
        render_queue.clear()
        self.assertEqual(render_queue.get_items(), [])

    def test_get_items_returns_copy(self):
        """get_items must return a defensive copy so callers mutating
        the returned list don't poison the queue."""
        render_queue.push({"name": "a.xlsx", "url": "/x"})
        snapshot = render_queue.get_items()
        snapshot.append({"leaked": True})
        # Queue is unchanged
        self.assertEqual(len(render_queue.get_items()), 1)


class TestRenderQueueValidation(unittest.TestCase):
    def setUp(self):
        render_queue.clear()

    def tearDown(self):
        render_queue.clear()

    def test_push_rejects_non_dict(self):
        with self.assertRaises(TypeError):
            render_queue.push("not a dict")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            render_queue.push(None)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            render_queue.push([{"name": "a"}])  # type: ignore[arg-type]

    def test_push_many_rejects_non_list(self):
        with self.assertRaises(TypeError):
            render_queue.push_many({"name": "a"})  # type: ignore[arg-type]

    def test_push_many_rejects_non_dict_element(self):
        with self.assertRaises(TypeError):
            render_queue.push_many([{"ok": True}, "bad"])  # type: ignore[list-item]


class TestRenderQueueIsolation(unittest.TestCase):
    """Queue is backed by ContextVar — verify basic isolation."""

    def test_contextvar_isolation_between_contexts(self):
        """Items pushed in one context do not leak into a fresh context."""
        render_queue.clear()
        render_queue.push({"name": "outer.xlsx", "url": "/x"})

        def inner() -> list[dict]:
            # New context: see the outer push (ContextVar copies parent state)
            # BUT our own clear() + push() only affects this context.
            existing = render_queue.get_items()
            render_queue.clear()
            render_queue.push({"name": "inner.xlsx", "url": "/y"})
            return list(existing), render_queue.get_items()  # type: ignore[return-value]

        ctx = contextvars.copy_context()
        outer_before, inner_view = ctx.run(inner)

        # Outer context still sees its original push
        self.assertEqual(len(render_queue.get_items()), 1)
        self.assertEqual(render_queue.get_items()[0]["name"], "outer.xlsx")

        # Inner context saw a copy of the outer state, then replaced it
        self.assertEqual(len(outer_before), 1)
        self.assertEqual(outer_before[0]["name"], "outer.xlsx")
        self.assertEqual(len(inner_view), 1)
        self.assertEqual(inner_view[0]["name"], "inner.xlsx")

    def test_asyncio_tasks_share_queue_within_same_context(self):
        """Tasks spawned without explicit context copy see the same queue."""
        render_queue.clear()

        async def task(name: str) -> None:
            render_queue.push({"name": name, "url": "/x"})

        async def runner() -> None:
            await asyncio.gather(task("a.xlsx"), task("b.xlsx"))

        # Use a fresh loop via run_until_complete (NOT asyncio.run) so we
        # don't close the default event loop — other tests (e.g.
        # test_chat_engine.TestChatEngineAsyncStream) still use the legacy
        # get_event_loop() pattern and break if we leave no default.
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(runner())
        finally:
            loop.close()

        names = {item["name"] for item in render_queue.get_items()}
        self.assertEqual(names, {"a.xlsx", "b.xlsx"})


class TestRenderQueueExposedFromChat(unittest.TestCase):
    def test_importable_from_chat_namespace(self):
        from openbench.chat import render_queue as rq

        self.assertTrue(hasattr(rq, "push"))
        self.assertTrue(hasattr(rq, "get_items"))
        self.assertTrue(hasattr(rq, "clear"))


if __name__ == "__main__":
    unittest.main()
